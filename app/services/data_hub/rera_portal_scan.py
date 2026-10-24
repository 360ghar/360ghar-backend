"""HRERA portal-id scanner: the only automated way to discover Haryana projects.

Why this exists
---------------
HRERA's project search (`view_project/search_project`) is CAPTCHA-gated and the
server validates the answer, so it cannot be driven headlessly. The search form
also requires all three of authority, case number, and year, so it is an
exact-match lookup rather than a browsable index. `view_project/project_list`
serves the portal homepage, not a list, and the portal exposes no JSON or AJAX
listing endpoint.

What *is* open is the filing page itself:
``view_project/project_preview_open/{portal_project_id}`` returns the full FORM
REP-I as server-rendered HTML with no CAPTCHA. That is what this scanner walks.

It is deliberately not on a schedule. Walking a government portal's identifier
space is a bulk operation, so an operator starts it explicitly, states the id
range, and the scanner paces itself. ``DEFAULT_MAX_IDS`` caps a single run so a
mistyped range cannot turn into an unbounded crawl.

A page is a filing when it carries the ``Temp Project Id`` marker; a page
without it is a gap (the id is unused or retired) and is counted, not treated as
an error. A request that fails outright is an error and is retried on the next
run, because the range is re-walked from ``start_id``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import ReraProject
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult
from app.services.data_hub.rera_project_detail import (
    ReraProjectDetailScraper,
    filing_source_document,
    parse_rep_i,
    project_slug,
)
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_PORTAL_BASE = "https://haryanarera.gov.in"
_DETAIL_URL = f"{_PORTAL_BASE}/view_project/project_preview_open/{{portal_project_id}}"

# A run walks at most this many ids unless an operator raises it deliberately.
DEFAULT_MAX_IDS = 250
# Seconds between filing fetches. The portal is a public service; this is a
# courtesy pace, not a technical limit.
DEFAULT_DELAY_SECONDS = 1.5
# Ids below this have never produced a filing in testing, so a default range
# starts here rather than at 1.
DEFAULT_START_ID = 1

# A filing page always carries this marker. A gap page does not.
_FILING_MARKER = "Temp Project Id"

# The fallback for a filing whose District label is missing or unreadable: the
# state, never a district the filing does not name. HRERA registers only Haryana
# projects, so the state is a fact of the register while "Gurugram" would be a
# guess. A fabricated district is not a cosmetic problem: micro-markets and the
# market pulse both use the district as the city, so a Faridabad project filed as
# Gurugram inflates Gurugram's numbers and disappears from Faridabad's. UPRERA
# takes the same position with its own state default.
_DEFAULT_DISTRICT = "Haryana"


def _filed_district(header: Mapping[str, Any]) -> str:
    """The district the filing names, or the state when it names none.

    The portal writes the district in capitals (``GURUGRAM``), so the value is
    title-cased for display. A filing that names no district gets the state, not
    a district picked for it — see ``_DEFAULT_DISTRICT``.
    """
    return str(header.get("district") or _DEFAULT_DISTRICT).title()


def _json_scalar(value: Any) -> Any:
    """A value that survives a JSONB round trip.

    Dates come off the filing as ``date`` objects, which the JSONB column cannot
    take. An ISO string keeps the value readable without losing its ordering.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class ReraPortalIdScanner(BaseScraper):
    """Walk a portal-id range and write every filing found."""

    name = "rera_portal_scan"
    requires_playwright = True

    def __init__(
        self,
        *,
        start_id: int | None = None,
        end_id: int | None = None,
        delay_seconds: float | None = None,
    ) -> None:
        self.start_id = start_id if start_id is not None else DEFAULT_START_ID
        self.end_id = end_id
        self.delay_seconds = (
            delay_seconds if delay_seconds is not None else DEFAULT_DELAY_SECONDS
        )

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {
                "status": "disabled",
                "run_id": None,
                "reason": "hrera_disabled_by_configuration",
            }
        if self.end_id is None:
            # Without an end id there is nothing to walk. Fail loudly rather than
            # silently defaulting to an open-ended crawl.
            return {
                "status": "failed",
                "run_id": None,
                "error": "end_id is required: state the portal-id range to walk",
            }
        span = self.end_id - self.start_id + 1
        if span < 1 or span > DEFAULT_MAX_IDS:
            # The cap bounds the id span, not the ids left after skipping stored
            # ones. Truncating silently would re-walk the same prefix every run
            # and report success while later ids were never checked.
            return {
                "status": "failed",
                "run_id": None,
                "error": (
                    f"id range must hold 1 to {DEFAULT_MAX_IDS} ids; "
                    f"got {self.start_id}..{self.end_id}. Split it into smaller runs."
                ),
            }
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _known_portal_ids(self) -> set[int]:
        """Portal ids already stored, so a re-walk skips them cheaply."""
        from app.core.database import get_bg_session_factory

        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(ReraProject.raw_data["portal_project_id"].astext).where(
                        ReraProject.raw_data["portal_project_id"].astext.isnot(None)
                    )
                )
            ).scalars().all()
        found: set[int] = set()
        for value in rows:
            try:
                found.add(int(value))
            except (TypeError, ValueError):
                continue
        return found

    def _id_range(self, known: set[int]) -> list[int]:
        """Every id in the range that is not stored yet. ``run`` bounds the span."""
        assert self.end_id is not None
        return [
            portal_id
            for portal_id in range(self.start_id, self.end_id + 1)
            if portal_id not in known
        ]

    async def _scrape(self) -> ScrapeResult:
        result = ScrapeResult()
        coverage: dict[str, Any] = {
            "source_url": _PORTAL_BASE,
            "pages_attempted": 0,
            "pages_checked": 0,
            "pages_parsed": 0,
            "records_parsed": 0,
            "ids_skipped_known": 0,
            "ids_skipped_gap": 0,
            # A page that carried the filing marker but whose sections did not
            # parse. It is a third outcome next to "gap" and "record", and without
            # it the three counts do not add up to pages_checked.
            "pages_unparsed": 0,
            # Where the next run of a longer walk starts. Set only when the walk
            # completes; a failed walk leaves it None so no id is skipped.
            "next_start_id": None,
            "status": "failed",
        }
        try:
            known = await self._known_portal_ids()
        except Exception as exc:
            logger.warning("Portal scan could not read known ids: %s", exc)
            result.errors.append(
                {
                    "source_url": _PORTAL_BASE,
                    "stage": "work_list",
                    "error_type": type(exc).__name__,
                    "message": "Known portal ids could not be read",
                }
            )
            result.source_coverage.append(coverage)
            return result

        pending = self._id_range(known)
        coverage["ids_skipped_known"] = len(
            known.intersection(range(self.start_id, (self.end_id or 0) + 1))
        )
        if not pending:
            # Every id in the range was already stored. The walk had nothing to
            # do and did it, which is a success — not a failed run. Leaving
            # ``successful_sources`` at 0 here marked it "failed" while this very
            # coverage block said "success".
            result.successful_sources = 1
            coverage["status"] = "success"
            coverage["next_start_id"] = self.end_id + 1 if self.end_id is not None else None
            result.source_coverage.append(coverage)
            return result

        session_failed = False
        try:
            async with self._playwright_browser() as browser:
                page = await browser.new_page()
                page.set_default_timeout(60000)
                for index, portal_id in enumerate(pending):
                    if index:
                        await asyncio.sleep(self.delay_seconds)
                    url = _DETAIL_URL.format(portal_project_id=portal_id)
                    coverage["pages_attempted"] += 1
                    try:
                        response = await page.goto(url, timeout=60000)
                        if response is not None and not response.ok:
                            # A blocked or throttled portal answers with an error
                            # status and no filing. That is a fetch failure, not a gap.
                            result.errors.append(
                                {
                                    "source_url": url,
                                    "stage": "fetch",
                                    "error_type": "HTTPStatus",
                                    "message": f"Filing page returned HTTP {response.status}",
                                }
                            )
                            continue
                        html = await page.content()
                    except Exception as exc:
                        result.errors.append(
                            {
                                "source_url": url,
                                "stage": "fetch",
                                "error_type": type(exc).__name__,
                                "message": "Filing page fetch failed",
                            }
                        )
                        continue
                    coverage["pages_checked"] += 1
                    if _FILING_MARKER not in html:
                        coverage["ids_skipped_gap"] += 1
                        continue
                    filing = parse_rep_i(html, portal_project_id=str(portal_id))
                    if not filing.ok:
                        # The page WAS a filing but its sections did not parse, so
                        # it is neither a gap nor a record. Counting it as neither
                        # left pages_checked > pages_parsed + ids_skipped_gap, which
                        # made a run look like it had silently lost pages.
                        coverage["pages_unparsed"] += 1
                        for error in filing.errors:
                            result.errors.append({"source_url": url, **error})
                        continue
                    document = filing_source_document(html, portal_project_id=str(portal_id))
                    document["source_key"] = f"{url}#{document['content_sha256']}"
                    record = filing.to_dict()
                    record["_source_key"] = document["source_key"]
                    record["_source_document"] = document
                    result.source_documents.append(document)
                    result.records.append(record)
                    coverage["pages_parsed"] += 1
                    coverage["records_parsed"] += 1
                await page.close()
        except Exception as exc:
            session_failed = True
            logger.warning("Portal scan browser session failed: %s", exc)
            result.errors.append(
                {
                    "source_url": _PORTAL_BASE,
                    "stage": "fetch",
                    "error_type": type(exc).__name__,
                    "message": "Browser session failed",
                }
            )

        # A walk succeeds when the browser session did not fail. How many ids
        # turned out to be filings is a finding, not a verdict: a range whose ids
        # are all unused or retired is a successful walk that found nothing, and
        # the module's own rule is that a gap "is counted, not treated as an
        # error". Deriving this from ``pages_parsed`` made the coverage status and
        # the run status disagree — a gap-only range reported coverage "success"
        # while the run row said "failed" — so a normal empty walk looked like a
        # broken run and a page that fetched fine but did not parse was reported
        # as a failed walk.
        result.successful_sources = int(not session_failed)
        if not session_failed and self.end_id is not None:
            coverage["next_start_id"] = self.end_id + 1
        coverage["status"] = (
            "failed"
            if session_failed
            else "partial"
            if result.errors
            else "success"
        )
        result.source_coverage.append(coverage)
        return result

    async def _upsert(self, db: AsyncSession, records: list[dict[str, Any]]) -> dict:
        """Create the register row when it is new, then write its filing.

        The register row is created from the filing itself, because the filing is
        the only source this scanner reads. Everything a listing page would have
        supplied is either on the filing page or left null.

        The conflict target is the portal project id, not the RERA number. The
        filing page states exactly one identifier — the pre-registration temp id,
        such as ``RERA-GRG-PROJ-1540-2024`` — and never the registration number
        that other paths key on. Keying on ``rera_number`` would mean inventing
        one, and it would also fail to recognise a row another source had already
        created for the same filing.
        """
        if not settings.HRERA_DATA_ENABLED:
            return {"found": 0, "upserted": 0, "failed": 0}
        found = len(records)
        upserted = 0
        failed = 0
        detail = ReraProjectDetailScraper()
        for rec in records:
            rec["_upsert_succeeded"] = False
            try:
                source_checked_at = rec.get("_source_checked_at")
                if not isinstance(source_checked_at, datetime):
                    failed += 1
                    continue
                async with db.begin_nested():
                    header = rec["header"]
                    profile = rec["profile"]
                    portal_project_id = rec.get("portal_project_id")
                    if not portal_project_id:
                        raise ValueError("filing carried no portal project id")
                    # The portal's own name for this filing. It is a filing
                    # identifier, not a registration number, and it is recorded
                    # verbatim rather than reshaped into one.
                    filing_number = rec.get("rera_number") or header.get("temp_project_id")
                    if not filing_number:
                        raise ValueError("filing carried no project identifier")
                    promoter = header.get("promoter_name")
                    values = {
                        "rera_number": filing_number,
                        "slug": project_slug(header.get("project_name"), filing_number),
                        "project_name": header.get("project_name") or "Unknown project",
                        "developer_name": promoter,
                        # The developer pages group projects by this slug, and the
                        # developer dossier derives the same value from the same
                        # name, so the two agree. Without it a developer page shows
                        # a score but no projects: the score matches on the name
                        # while the project list matches on the slug.
                        "developer_slug": generate_slug(promoter) if promoter else None,
                        "district": _filed_district(header),
                        "location": header.get("site_address"),
                        "total_units": profile.get("total_units"),
                        "possession_date": profile.get("proposed_completion_date"),
                        # The filing page states the licence the promoter holds,
                        # not a RERA registration date: it is the pre-registration
                        # FORM REP-I and names the project only by its temp id.
                        # The date it carries is Part B row 5's
                        # ``DTCP 219 of 2023 25.10.2023 valid upto 24.10.2028``,
                        # which ``_write_filing`` already files on
                        # ``rera_statutory_approvals.licence_date``. Publishing it
                        # here put a licence date on the public
                        # ``GET /data-hub/rera-projects`` response under the name
                        # ``registration_date``: the stored rows read 2009-11-19
                        # for RERA-PKL-PROJ-628-2019 and 2013-12-11 for
                        # RERA-GRG-PROJ-1182-2022, both before the RERA Act came
                        # into force. ``None`` rather than an omitted key, so a
                        # re-scan also clears a date an earlier run wrote.
                        "registration_date": None,
                        "status": "registered",
                        "source_url": rec["_source_document"]["canonical_url"],
                        # raw_data is JSONB, so a date has to be stringified here.
                        # It also has to stay JSON-native: the detail scraper's work
                        # list filters on raw_data["portal_project_id"], and the
                        # unique index that makes this upsert idempotent is on that
                        # same expression.
                        "raw_data": {
                            "portal_project_id": str(portal_project_id),
                            "identifier_kind": "temp_project_id",
                            "tehsil": header.get("tehsil"),
                            "applicant_type": header.get("applicant_type"),
                            "project_type": header.get("project_type"),
                            "submitted_on": _json_scalar(header.get("submitted_on")),
                        },
                    }
                    stmt = pg_insert(ReraProject).values(**values)
                    # Four fields are deliberately absent from the update set.
                    # ``rera_number`` and ``status`` are registration facts other
                    # paths own: re-reading a filing must not rename a project back
                    # to its filing id, nor flip a lapsed or revoked project to
                    # registered (which would also pin derive_stage to the wrong
                    # answer). ``slug`` is a published URL key, so rewriting it on a
                    # re-scan would break existing links. ``raw_data`` is left alone
                    # so this scan cannot clobber keys another writer put there.
                    # ``developer_slug`` is included on purpose: it is a derived
                    # grouping key, so a re-scan repairs a row written before it
                    # existed.
                    update_fields = {
                        key: getattr(stmt.excluded, key)
                        for key in values
                        if key not in ("rera_number", "slug", "raw_data", "status")
                    }
                    row = await db.execute(
                        stmt.on_conflict_do_update(
                            # Postgres matches ON CONFLICT against the index
                            # expression literally, so the key is written out as
                            # SQL. A bound parameter (``raw_data ->> $1``) is
                            # rejected as a syntax error.
                            index_elements=[text("(raw_data ->> 'portal_project_id')")],
                            index_where=text(
                                "raw_data ->> 'portal_project_id' IS NOT NULL"
                            ),
                            set_=update_fields,
                        ).returning(ReraProject.id, ReraProject.status)
                    )
                    project_id, register_status = row.one()
                    rec["rera_project_id"] = project_id
                    rec["rera_number"] = filing_number
                    rec["project_name"] = values["project_name"]
                    rec["register_status"] = register_status
                    await detail._write_filing(db, rec, source_checked_at)
                upserted += 1
                rec["_upsert_succeeded"] = True
            except Exception as exc:
                logger.warning(
                    "Portal scan failed to write filing for id %s: %s",
                    rec.get("portal_project_id"),
                    exc,
                )
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}
