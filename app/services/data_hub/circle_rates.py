"""Circle rates scraper — IGRS Haryana (Playwright, JS-rendered form)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import CircleRate
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_IGRS_URL = "https://jamabandi.nic.in/land records/NakalRecord"  # best effort
_CIRCLE_RATE_URL = "https://registration.rajasthan.gov.in"  # fallback reference

# Known Gurugram sectors for seed data (in case scraping fails)
_KNOWN_SECTORS = [f"Sector {i}" for i in range(1, 116)]


class CircleRateScraper(BaseScraper):
    name = "circle_rates"
    requires_playwright = True

    async def _scrape(self) -> list[dict]:
        results = []
        try:
            async with self._playwright_browser() as browser:
                page = await browser.new_page()
                page.set_default_timeout(60000)
                # IGRS Haryana circle rates
                await page.goto("https://igrs.haryana.gov.in/", timeout=60000)
                await asyncio.sleep(3)
                # Look for circle rate navigation
                try:
                    await page.click("text=Circle Rate", timeout=5000)
                    await asyncio.sleep(2)
                    html = await page.content()
                    records = self._parse_circle_rates_html(html)
                    results.extend(records)
                except Exception as nav_e:
                    logger.warning("IGRS navigation failed: %s", nav_e)
                    # Fall back: try district rate PDF page
                    try:
                        await page.goto("https://igrs.haryana.gov.in/circlerates", timeout=60000)
                        await asyncio.sleep(2)
                        html = await page.content()
                        results.extend(self._parse_circle_rates_html(html))
                    except Exception as e2:
                        logger.warning("IGRS fallback also failed: %s", e2)
                await page.close()
        except Exception as e:
            logger.warning("Circle rates Playwright scrape failed: %s", e)
        return results

    def _parse_circle_rates_html(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        records = []
        revision_year = date.today().year
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                rec: dict[str, Any] = {
                    "district": "Gurugram",
                    "revision_year": revision_year,
                    "property_type": "residential",
                    "raw_data": {"headers": headers, "cells": cells},
                }
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if "sector" in h or "locality" in h or "colony" in h:
                        if not rec.get("sector"):
                            rec["sector"] = val
                        else:
                            rec["colony"] = val
                    elif "type" in h:
                        rec["property_type"] = val.lower() or "residential"
                    elif "rate" in h and "sqyd" in h:
                        try:
                            rec["rate_per_sqyd"] = float(val.replace(",", "").replace("₹", "").strip())
                        except ValueError:
                            pass
                    elif "rate" in h and "sqft" in h:
                        try:
                            rec["rate_per_sqft"] = float(val.replace(",", "").replace("₹", "").strip())
                        except ValueError:
                            pass
                if rec.get("sector"):
                    rec["slug"] = generate_slug(rec["sector"], rec.get("colony", ""), rec["property_type"], str(revision_year))
                    rec["source_url"] = "https://igrs.haryana.gov.in/"
                    records.append(rec)
        return records

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                rec.setdefault("colony", None)
                values = {k: v for k, v in rec.items()
                          if hasattr(CircleRate, k) and k not in ("id", "created_at", "updated_at")}
                stmt = pg_insert(CircleRate).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["sector", "colony", "property_type", "revision_year"],
                    set_={
                        "rate_per_sqyd": stmt.excluded.rate_per_sqyd,
                        "rate_per_sqft": stmt.excluded.rate_per_sqft,
                        "raw_data": stmt.excluded.raw_data,
                        "slug": stmt.excluded.slug,
                        "source_url": stmt.excluded.source_url,
                    }
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert circle rate: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
