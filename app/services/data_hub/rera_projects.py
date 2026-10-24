"""RERA project scraper — HRERA register rows.

**This scraper cannot currently produce records, and it says so.**

The HRERA project search at ``view_project/search_project`` is CAPTCHA-gated and
the server validates the answer: posting the form with any captcha value returns
"Please enter CAPTCHA". The form also requires authority, case number, and year
together, so it is an exact-match lookup rather than a browsable index.
``view_project/project_list`` serves the portal homepage, not a list, and the
portal exposes no JSON or AJAX listing endpoint. There is therefore no headless
path from this page to register rows.

Discovery now happens in ``rera_portal_scan.ReraPortalIdScanner``, which walks
the open filing pages at ``view_project/project_preview_open/{portal_project_id}``
directly. This scraper is kept because it still owns the ``rera_projects`` name
in the admin trigger map, and because a future HRERA release may reopen a
listing route. Until then it reports the blocker instead of quietly returning
zero rows, which is what it did when it targeted a district selector that does
not exist on the page.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import ReraProject
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)

_HRERA_URL = "https://haryanarera.gov.in/view_project/search_project"
_DETAIL_LINK = re.compile(r"project_preview_open/(\d+)")

# The search form's real field names, read from the served markup. The authority
# select offers RERA-PKL, RERA-GRG, and H-REAT; the year select runs 2018 onward.
_SEARCH_FIELDS = ("t_case_type", "t_case_no", "t_case_year", "captcha")
_CAPTCHA_BLOCKED = "HRERA_SEARCH_REQUIRES_CAPTCHA"


def _portal_project_id(row: Any) -> str | None:
    """The portal's project id, read from the filing link in a result row."""
    for anchor in row.find_all("a", href=True):
        match = _DETAIL_LINK.search(anchor["href"])
        if match:
            return match.group(1)
    return None


class ReraProjectScraper(BaseScraper):
    name = "rera_projects"
    requires_playwright = True

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {"status": "disabled", "run_id": None, "reason": "hrera_disabled_by_configuration"}
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _scrape(self) -> ScrapeResult:
        """Report the CAPTCHA blocker instead of returning an empty success.

        The form's real fields are ``t_case_type``, ``t_case_no``, ``t_case_year``
        and ``captcha``; the server rejects a submission whose captcha it did not
        issue. No district selector exists, so the previous navigation step was
        targeting markup that is not on the page.
        """
        if not settings.HRERA_DATA_ENABLED:
            return ScrapeResult()
        result = ScrapeResult()
        coverage: dict[str, Any] = {
            "source_url": _HRERA_URL,
            "pages_attempted": 0,
            "pages_checked": 0,
            "pages_parsed": 0,
            "records_parsed": 0,
            "status": "failed",
        }
        result.errors.append(
            {
                "source_url": _HRERA_URL,
                "stage": "navigation",
                "error_type": _CAPTCHA_BLOCKED,
                "message": (
                    "HRERA project search is CAPTCHA-gated and server-validated; "
                    "there is no headless path to register rows. Use "
                    "rera_portal_scan to walk filing pages by portal id instead."
                ),
            }
        )
        result.source_coverage.append(coverage)
        return result

    # A listing parser used to live here. It targeted a district selector that is
    # not on the page and could never pass the CAPTCHA, so it silently produced
    # zero records. It is gone rather than kept: code that cannot run implies the
    # scraper works. When HRERA exposes a listing route, write the parser against
    # the markup that route actually serves, with a captured page as its fixture.

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
                        )
                        .returning(ReraProject.id)
                    )
                    if result.scalar_one_or_none() is None:
                        continue
                upserted += 1
                rec["_upsert_succeeded"] = True
            except Exception as e:
                logger.warning("Failed to upsert RERA project %s: %s", rec.get("rera_number"), e)
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}
