"""RERA project scraper — HRERA Gurugram (Playwright, JS-rendered tables)."""
import asyncio
import logging
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import ReraProject
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_HRERA_URL = "https://hrera.haryana.gov.in/Public/ProjectSearch"


class ReraProjectScraper(BaseScraper):
    name = "rera_projects"
    requires_playwright = True

    async def _scrape(self) -> list[dict]:
        results = []
        try:
            async with self._playwright_browser() as browser:
                page = await browser.new_page()
                page.set_default_timeout(60000)
                await page.goto(_HRERA_URL, timeout=60000)
                await asyncio.sleep(3)
                # Search for Gurugram projects
                try:
                    # Try district dropdown
                    district_sel = page.locator("select[name*='district'], select[id*='district']")
                    if await district_sel.count() > 0:
                        await district_sel.first.select_option(label="Gurugram")
                        await asyncio.sleep(1)
                    # Submit search
                    submit = page.locator("button[type='submit'], input[type='submit']")
                    if await submit.count() > 0:
                        await submit.first.click()
                        await asyncio.sleep(3)
                    html = await page.content()
                    results.extend(self._parse_rera_html(html))
                    # Try to paginate (up to 5 pages)
                    for _ in range(4):
                        next_btn = page.locator("a:has-text('Next'), a:has-text('>'), .pagination .next")
                        if await next_btn.count() == 0:
                            break
                        await next_btn.first.click()
                        await asyncio.sleep(2)
                        html = await page.content()
                        results.extend(self._parse_rera_html(html))
                except Exception as nav_e:
                    logger.warning("HRERA navigation failed: %s", nav_e)
                    html = await page.content()
                    results.extend(self._parse_rera_html(html))
                await page.close()
        except Exception as e:
            logger.warning("RERA projects Playwright scrape failed: %s", e)
        return results

    def _parse_rera_html(self, html: str) -> list[dict]:
        import re
        soup = BeautifulSoup(html, "lxml")
        records = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                rec: dict[str, Any] = {"district": "Gurugram", "raw_data": {"headers": headers, "cells": cells}}
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i].strip()
                    if not val:
                        continue
                    if "rera" in h and "number" in h or "registration" in h and "no" in h:
                        rec["rera_number"] = val
                    elif "project" in h and "name" in h:
                        rec["project_name"] = val
                    elif "developer" in h or "promoter" in h:
                        rec["developer_name"] = val
                    elif "location" in h or "address" in h:
                        rec["location"] = val
                    elif "unit" in h and "total" in h:
                        try:
                            rec["total_units"] = int(val.replace(",", ""))
                        except ValueError:
                            pass
                    elif "status" in h:
                        rec["status"] = val.lower()
                    elif "possession" in h:
                        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", val)
                        if m:
                            try:
                                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                                if y < 100:
                                    y += 2000
                                rec["possession_date"] = date(y, mo, d)
                            except ValueError:
                                pass
                if rec.get("rera_number") and rec.get("project_name"):
                    rec["developer_slug"] = generate_slug(rec.get("developer_name", "unknown"))
                    rec["source_url"] = _HRERA_URL
                    records.append(rec)
        return records

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                values = {k: v for k, v in rec.items()
                          if hasattr(ReraProject, k) and k not in ("id", "created_at", "updated_at")}
                stmt = pg_insert(ReraProject).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["rera_number"],
                    set_={
                        "status": stmt.excluded.status,
                        "units_booked": stmt.excluded.units_booked,
                        "raw_data": stmt.excluded.raw_data,
                        "source_url": stmt.excluded.source_url,
                    }
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert RERA project %s: %s", rec.get("rera_number"), e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
