"""RERA project scraper — UPRERA (Uttar Pradesh, server-rendered postback grid).

The live portal is ``up-rera.in``. The older ``uprera.up.gov.in`` host no longer
resolves (NXDOMAIN), so every request to it fails before a single row is parsed.

Flow: the home page's *Registered Projects* menu entry is an ASP.NET postback
(``ctl00$ContentPlaceHolder1$lnkRegisteredProjects``). Posting it lands on
``/projects``, which renders the whole register as one server-side GridView
(``#grdPojDetail``) — 3,800+ rows, no pagination, no JavaScript-built table. The
postback still needs the home page's view state and session cookie, and that
view state alone is ~3 MB, so a browser performs the round trip.

Four decisions worth knowing:

* **The grid is the whole register, not a search result.** A plain
  ``GET /projects`` answers with ``servermaintenance.aspx``; only the postback
  reaches the grid. One response carries every registered project, so one page
  is fetched and no pagination is followed. ``records_parsed`` in the coverage
  block makes register drift visible.
* **``EndDate`` becomes ``possession_date``.** The portal labels the project's
  declared completion date ``EndDate``; that is the date by which the promoter
  must hand over possession. UPRERA publishes no registration-validity date, so
  ``expiry_date`` stays null rather than being filled from a neighbouring field.
* **``status`` is ``registered``.** This grid is the registered-projects
  register; the portal publishes de-registered, NCLT, abeyance and withdrawn
  projects on separate pages that this scraper never loads.
* **No ``portal_project_id``.** The row's detail link is
  ``Projectsummary?<opaque params>``: every parameter is a per-session encrypted
  token, so the same project gets a different URL on every load. That column sits
  under a unique partial index, so storing one of those tokens would collide with
  the row this run just wrote. ``rera_number`` (``UPRERAPRJ13276``) is the
  portal's stable key and is captured instead.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import ReraProject
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult
from app.services.data_hub.rera_project_detail import project_slug
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_UPRERA_HOME = "https://up-rera.in/"
_UPRERA_URL = "https://up-rera.in/projects"
_AUTHORITY = "Uttar Pradesh Real Estate Regulatory Authority"
_JURISDICTION = "Uttar Pradesh, India"
# The register is filtered by district on the portal, but the unfiltered grid
# carries the district in its own column. This is the fallback for a row whose
# district cell is empty: the state, never a district the row does not name.
_DEFAULT_DISTRICT = "Uttar Pradesh"
_REGISTERED_STATUS = "registered"
_GRID_ROW_SELECTOR = "table#grdPojDetail tr"
# The portal is a government service behind an ASP.NET postback: the grid takes
# seconds to arrive after the form posts. Wait budgets, not sleep constants.
_GRID_WAIT_ATTEMPTS = 15
_GRID_WAIT_SECONDS = 2.0
# The postback response is a ~15 MB streamed document, so the grid grows while the
# browser parses it. Reading as soon as any row exists captures a partial register
# and reports success: a measured run read 2315 of 3823 rows that way. The row
# count is therefore read until it repeats, which is the honest signal that the
# document has finished arriving.
_GRID_STABLE_READS = 2
_NAVIGATION_TIMEOUT_MS = 90_000

# The home page's form posts the menu entry; the browser supplies the view state.
_OPEN_REGISTERED_PROJECTS_JS = """
() => {
    const form = document.forms['aspnetForm'] || document.forms['form1'] || document.forms[0];
    if (!form) { return false; }
    if (form.__EVENTTARGET) { form.__EVENTTARGET.value = 'ctl00$ContentPlaceHolder1$lnkRegisteredProjects'; }
    if (form.__EVENTARGUMENT) { form.__EVENTARGUMENT.value = ''; }
    form.submit();
    return true;
}
"""

_DATE_FIELDS = frozenset({"registration_date", "possession_date"})


def _clean(value: str) -> str:
    """Grid cells wrap their value in spans and break lines; collapse the noise."""
    return re.sub(r"\s+", " ", value).strip()


def _parse_dmy(value: str) -> date | None:
    """UPRERA dates are ``dd-mm-yyyy``; ``30-08-2016`` rules out a month-first read."""
    match = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", value)
    if match is None:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _field_for_header(header: str) -> str | None:
    """Which record field a grid column feeds, or None when nothing consumes it.

    The grid ships ten columns: S.No, Promoter Name, Project Name, RERA Reg.No.,
    ProjectType, District, StartDate, EndDate, Registration Date, Details.
    ``S.No`` and ``Details`` feed nothing, and ``StartDate`` has no column on
    ``rera_projects``; all three stay in ``raw_data`` rather than being forced
    into a field that means something else.
    """
    if "rera" in header and ("reg" in header or "no" in header):
        return "rera_number"
    if "project" in header and "name" in header:
        return "project_name"
    if "promoter" in header or "developer" in header:
        return "developer_name"
    if "project" in header and "type" in header:
        return "project_type"
    if "district" in header:
        return "district"
    if "registration" in header and "date" in header:
        return "registration_date"
    if "end" in header and "date" in header:
        return "possession_date"
    if "location" in header or "address" in header:
        return "location"
    return None


def _is_project_grid(headers: list[str]) -> bool:
    """Only the register grid carries both a RERA number and a project name."""
    fields = {_field_for_header(header) for header in headers}
    return "rera_number" in fields and "project_name" in fields


def _is_filter_row(row: Any) -> bool:
    """tablesorter renders a per-column search row and a sticky clone of it."""
    classes = row.get("class") or []
    return any(
        "tablesorter-filter-row" in name or "tablesorter-ignoreRow" in name for name in classes
    )


def _assign(record: dict[str, Any], field: str, value: str) -> None:
    if field not in _DATE_FIELDS:
        record[field] = value
        return
    parsed = _parse_dmy(value)
    if parsed is not None:
        record[field] = parsed


class UpreraProjectScraper(BaseScraper):
    name = "uprera_projects"
    requires_playwright = True

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {"status": "disabled", "run_id": None, "reason": "hrera_disabled_by_configuration"}
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _scrape(self) -> ScrapeResult:
        if not settings.HRERA_DATA_ENABLED:
            return ScrapeResult()
        result = ScrapeResult()
        coverage: dict[str, Any] = {
            "source_url": _UPRERA_URL,
            "pages_attempted": 0,
            "pages_checked": 0,
            "pages_parsed": 0,
            "records_parsed": 0,
            "status": "failed",
        }
        try:
            async with self._playwright_browser() as browser:
                page = await browser.new_page()
                page.set_default_timeout(60000)
                coverage["pages_attempted"] = 1
                await page.goto(_UPRERA_HOME, timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(_GRID_WAIT_SECONDS)
                # Submitting the form starts a navigation. Without waiting for it,
                # the row count below is polled against a document that is still
                # streaming in, and the grid is read while it is still growing.
                try:
                    async with page.expect_navigation(timeout=_NAVIGATION_TIMEOUT_MS):
                        await page.evaluate(_OPEN_REGISTERED_PROJECTS_JS)
                except PlaywrightTimeoutError:
                    # The grid can already be present when the submit is a no-op
                    # (an already-loaded register). The stability poll decides.
                    logger.info("UPRERA postback did not navigate; checking for a grid")
                grid_rows = await self._wait_for_grid(page)
                coverage["grid_rows"] = grid_rows
                html = await page.content()
                coverage["pages_checked"] = 1
                checked_at = datetime.now(UTC)
                content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
                source_key = f"{_UPRERA_URL}#{content_hash}"
                result.source_documents.append(
                    {
                        "source_key": source_key,
                        "authority": _AUTHORITY,
                        "title": "UPRERA registered project register",
                        "canonical_url": _UPRERA_URL,
                        "source_record_id": None,
                        "jurisdiction": _JURISDICTION,
                        "document_type": "registry_page",
                        "language": "en",
                        "license_name": None,
                        "reuse_terms": None,
                        "terms_url": None,
                        "published_at": None,
                        "effective_from": None,
                        "effective_to": None,
                        "fetched_at": checked_at,
                        "checked_at": checked_at,
                        "content_sha256": content_hash,
                        "artifact_reference": None,
                    }
                )
                if not BeautifulSoup(html, "html.parser").find("table"):
                    result.errors.append(
                        {
                            "source_url": _UPRERA_URL,
                            "stage": "parse",
                            "error_type": "ExpectedTableNotFound",
                            "message": "UPRERA register page contained no table",
                        }
                    )
                else:
                    page_records = self._parse_registered_projects_html(html)
                    if not page_records:
                        result.errors.append(
                            {
                                "source_url": _UPRERA_URL,
                                "stage": "parse",
                                "error_type": "NoReraRecordsParsed",
                                "message": "UPRERA register page produced no project records",
                            }
                        )
                    else:
                        for record in page_records:
                            record["_source_key"] = source_key
                            record["_locator_page"] = 1
                        result.records.extend(page_records)
                        coverage["pages_parsed"] = 1
                        coverage["records_parsed"] = len(page_records)
                await page.close()
        except Exception as exc:
            logger.warning("UPRERA projects Playwright scrape failed: %s", exc)
            result.errors.append(
                {
                    "source_url": _UPRERA_URL,
                    "stage": "fetch",
                    "error_type": type(exc).__name__,
                    "message": "Source page fetch failed",
                }
            )

        result.successful_sources = int(coverage["pages_parsed"] > 0)
        coverage["status"] = (
            "failed"
            if coverage["pages_parsed"] == 0
            else "partial"
            if result.errors
            else "success"
        )
        result.source_coverage.append(coverage)
        return result

    def _parse_registered_projects_html(self, html: str) -> list[dict]:
        """Every registered project the grid carries, keyed by its RERA number."""
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        seen: set[str] = set()
        for table_index, table in enumerate(soup.find_all("table"), start=1):
            headers = [_clean(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
            if not _is_project_grid(headers):
                continue
            for row_index, row in enumerate(table.find_all("tr"), start=1):
                if _is_filter_row(row):
                    continue
                cells = [_clean(td.get_text(" ", strip=True)) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                rec: dict[str, Any] = {
                    "district": _DEFAULT_DISTRICT,
                    "status": _REGISTERED_STATUS,
                    "raw_data": {"headers": headers, "cells": cells},
                }
                for index, header in enumerate(headers):
                    if index >= len(cells):
                        break
                    value = cells[index]
                    if not value:
                        continue
                    field = _field_for_header(header)
                    if field is None:
                        continue
                    _assign(rec, field, value)
                rera_number = rec.get("rera_number")
                project_name = rec.get("project_name")
                if not rera_number or not project_name:
                    continue
                # The page renders the register grid and a tablesorter sticky clone
                # of its header. A clone that ever carried rows would repeat
                # projects, and the upsert rejects a duplicated key in one batch.
                if rera_number in seen:
                    continue
                seen.add(rera_number)
                rec["developer_slug"] = generate_slug(rec.get("developer_name") or "unknown")
                rec["slug"] = project_slug(project_name, rera_number)
                rec["source_url"] = _UPRERA_URL
                rec["_locator_table"] = table_index
                rec["_locator_row"] = row_index
                records.append(rec)
        return records

    async def _wait_for_grid(self, page: Any) -> int:
        """Wait until the register has finished arriving, and report its size.

        The grid is one server-rendered table inside a streamed multi-megabyte
        document, so its row count climbs while the browser parses the body. A
        single "are there rows yet" check is not enough: it is satisfied by a
        partial grid. The count is therefore read repeatedly and accepted only
        once it repeats, which means the document stopped growing.
        """
        previous = -1
        stable = 0
        for _ in range(_GRID_WAIT_ATTEMPTS):
            count: int = await page.locator(_GRID_ROW_SELECTOR).count()
            if count > 1 and count == previous:
                stable += 1
                if stable >= _GRID_STABLE_READS:
                    return count
            else:
                stable = 0
            previous = count
            await asyncio.sleep(_GRID_WAIT_SECONDS)
        return previous if previous > 0 else 0

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {"found": 0, "upserted": 0, "failed": 0}
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            rec["_upsert_succeeded"] = False
            try:
                source_checked_at = rec.get("_source_checked_at")
                if not isinstance(source_checked_at, datetime):
                    failed += 1
                    continue
                values = {
                    key: value
                    for key, value in rec.items()
                    if hasattr(ReraProject, key)
                    and key
                    not in (
                        "id",
                        "created_at",
                        "updated_at",
                        "last_checked_at",
                        "last_successful_run_id",
                    )
                }
                async with db.begin_nested():
                    stmt = pg_insert(ReraProject).values(**values)
                    update_fields = {
                        key: getattr(stmt.excluded, key)
                        for key in values
                        if key
                        not in (
                            "rera_number",
                            "last_checked_at",
                            "last_successful_run_id",
                        )
                    }
                    result = await db.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["rera_number"],
                            set_=update_fields,
                            where=or_(
                                ReraProject.last_checked_at.is_(None),
                                ReraProject.last_checked_at <= source_checked_at,
                            ),
                        ).returning(ReraProject.id)
                    )
                    if result.scalar_one_or_none() is None:
                        continue
                upserted += 1
                rec["_upsert_succeeded"] = True
            except Exception as e:
                logger.warning("Failed to upsert UPRERA project %s: %s", rec.get("rera_number"), e)
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}
