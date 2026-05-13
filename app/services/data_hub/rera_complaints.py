"""RERA complaints/orders scraper — HRERA (Playwright) with builder scoring."""
import asyncio
import logging
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import ReraComplaint, ReraProject
from app.models.enums import ComplaintNature
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_HRERA_ORDERS_URL = "https://hrera.haryana.gov.in/Public/OrderSearch"

_NATURE_KEYWORDS = {
    ComplaintNature.delay: ["delay", "possession", "handover", "completion"],
    ComplaintNature.quality: ["quality", "defect", "construction", "structure"],
    ComplaintNature.refund: ["refund", "return", "cancellation", "withdrawal"],
    ComplaintNature.compensation: ["compensation", "damages", "penalty", "interest"],
}


def _classify_complaint_nature(text: str) -> ComplaintNature:
    text_lower = text.lower()
    for nature, keywords in _NATURE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return nature
    return ComplaintNature.other


class ReraComplaintScraper(BaseScraper):
    name = "rera_complaints"
    requires_playwright = True

    async def _scrape(self) -> list[dict]:
        results = []
        try:
            async with self._playwright_browser() as browser:
                page = await browser.new_page()
                page.set_default_timeout(60000)
                await page.goto(_HRERA_ORDERS_URL, timeout=60000)
                await asyncio.sleep(3)
                try:
                    # Filter by Gurugram district
                    district_sel = page.locator("select[name*='district'], select[id*='district']")
                    if await district_sel.count() > 0:
                        await district_sel.first.select_option(label="Gurugram")
                        await asyncio.sleep(1)
                    submit = page.locator("button[type='submit'], input[type='submit']")
                    if await submit.count() > 0:
                        await submit.first.click()
                        await asyncio.sleep(3)
                    for _page_num in range(5):  # up to 5 pages
                        html = await page.content()
                        results.extend(self._parse_complaints_html(html))
                        next_btn = page.locator("a:has-text('Next'), .pagination .next")
                        if await next_btn.count() == 0:
                            break
                        await next_btn.first.click()
                        await asyncio.sleep(2)
                except Exception as nav_e:
                    logger.warning("HRERA complaints navigation failed: %s", nav_e)
                    html = await page.content()
                    results.extend(self._parse_complaints_html(html))
                await page.close()
        except Exception as e:
            logger.warning("RERA complaints Playwright scrape failed: %s", e)
        return results

    def _parse_complaints_html(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        records = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                rec: dict[str, Any] = {"raw_data": {"headers": headers, "cells": cells}}
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i].strip()
                    if not val:
                        continue
                    if "order" in h and ("no" in h or "number" in h):
                        rec["order_number"] = val
                    elif "builder" in h or "respondent" in h or "promoter" in h:
                        rec["respondent_builder"] = val
                    elif "project" in h:
                        rec["respondent_project"] = val
                    elif "rera" in h and "number" in h:
                        rec["rera_number"] = val
                    elif "summary" in h or "subject" in h:
                        rec["order_summary"] = val
                    elif "penalty" in h or "amount" in h:
                        try:
                            rec["penalty_amount"] = float(val.replace(",", "").replace("₹", ""))
                        except ValueError:
                            pass
                    elif "date" in h:
                        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", val)
                        if m:
                            try:
                                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                                if y < 100:
                                    y += 2000
                                rec["order_date"] = date(y, mo, d)
                            except ValueError:
                                pass
                if rec.get("order_number"):
                    text_for_nature = f"{rec.get('order_summary', '')} {rec.get('respondent_project', '')}"
                    rec["complaint_nature"] = _classify_complaint_nature(text_for_nature)
                    if rec.get("respondent_builder"):
                        rec["builder_slug"] = generate_slug(rec["respondent_builder"])
                    rec["source_url"] = _HRERA_ORDERS_URL
                    records.append(rec)
        return records

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                values = {k: v for k, v in rec.items()
                          if hasattr(ReraComplaint, k) and k not in ("id", "created_at", "updated_at")}
                stmt = pg_insert(ReraComplaint).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["order_number"],
                    set_={
                        "order_summary": stmt.excluded.order_summary,
                        "penalty_amount": stmt.excluded.penalty_amount,
                        "complaint_nature": stmt.excluded.complaint_nature,
                        "raw_data": stmt.excluded.raw_data,
                    }
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert RERA complaint %s: %s", rec.get("order_number"), e)
                await db.rollback()
                failed += 1
        await db.commit()
        # Update builder complaint_count on ReraProject
        try:
            await self._update_builder_scores(db)
            await db.commit()  # commit the score updates
        except Exception as e:
            logger.warning("Failed to update builder scores: %s", e)
            await db.rollback()
        return {"found": found, "upserted": upserted, "failed": failed}

    async def _update_builder_scores(self, db: AsyncSession) -> None:
        """Update complaint_count on ReraProject rows based on builder_slug matches."""
        from sqlalchemy import func as sqlfunc
        try:
            # Get complaint counts per builder_slug
            result = await db.execute(
                select(
                    ReraComplaint.builder_slug,
                    sqlfunc.count(ReraComplaint.id).label("cnt")
                ).where(ReraComplaint.builder_slug.isnot(None))
                .group_by(ReraComplaint.builder_slug)
            )
            for row in result:
                await db.execute(
                    update(ReraProject)
                    .where(ReraProject.developer_slug == row.builder_slug)
                    .values(complaint_count=row.cnt)
                )
        except Exception as e:
            logger.warning("Failed to update builder scores: %s", e)
            raise
