"""BaankNet auction scraper — NPA and insolvency liquidation assets from baanknet.com."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import address_hash, upsert_bank_auction

logger = logging.getLogger(__name__)

_BAANKNET_URL = "https://www.baanknet.com/searchresult.aspx"
# Alternate search endpoints for broader coverage
_BAANKNET_NPA_URL = "https://www.baanknet.com/npa-search.aspx"
_BAANKNET_LIQUIDATION_URL = "https://www.baanknet.com/liquidation-search.aspx"


class BaankNetAuctionScraper(BaseScraper):
    name = "baanknet_auctions"
    source = AuctionSource.baanknet
    requires_playwright = True

    async def _scrape(self) -> list[dict]:
        results = []
        urls = [_BAANKNET_URL, _BAANKNET_NPA_URL, _BAANKNET_LIQUIDATION_URL]

        async with self._playwright_browser() as browser:
            for url in urls:
                try:
                    page = await browser.new_page()
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=60000)
                        # Wait for the results table to render
                        await page.wait_for_selector("table, .grid, .auction-list", timeout=10000)
                        content = await page.content()
                        parsed = self._parse_listing(content, url)
                        results.extend(parsed)
                    except Exception as e:
                        logger.warning("Playwright failed for %s: %s", url, e)
                    finally:
                        await page.close()
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning("Error processing %s: %s", url, e)

        return results

    def _parse_listing(self, html: str, source_url: str) -> list[dict]:
        """Best-effort parse of BaankNet auction listing tables."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not headers:
                # Try first row as header
                first_row = table.find("tr")
                if first_row:
                    headers = [td.get_text(strip=True).lower() for td in first_row.find_all("td")]

            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 3:
                    continue

                record: dict[str, Any] = {
                    "source": AuctionSource.baanknet,
                    "bank_name": "BaankNet",
                    "property_description": cells[0] if cells else "",
                    "city": "Delhi NCR",
                    "source_url": source_url,
                    "raw_data": {"headers": headers, "cells": cells},
                }

                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if not val:
                        continue

                    if "property" in h and "type" in h:
                        record["property_type"] = val
                    elif "address" in h or "location" in h or "city" in h:
                        record["full_address"] = val
                        # Detect city from content
                        record["city"] = self._detect_city(val) or "Delhi NCR"
                    elif "reserve" in h or "base" in h or "price" in h:
                        try:
                            record["reserve_price"] = float(
                                re.sub(r"[,₹\s]", "", val)
                            )
                        except ValueError:
                            pass
                    elif "emd" in h or "earnest" in h:
                        try:
                            record["emd_amount"] = float(
                                re.sub(r"[,₹\s]", "", val)
                            )
                        except ValueError:
                            pass
                    elif "auction" in h and "date" in h:
                        record["auction_date"] = self._parse_date(val)
                    elif "description" in h or "detail" in h:
                        record["property_description"] = val
                    elif "bank" in h or "branch" in h:
                        record["bank_name"] = val

                # Fallback: try to extract address from the full row text
                if not record.get("full_address"):
                    row_text = " ".join(cells)
                    record["full_address"] = row_text

                if record.get("property_description"):
                    records.append(record)

        return records

    @staticmethod
    def _parse_date(val: str) -> date:
        """Attempt multiple date formats."""
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                continue
        return date(1970, 1, 1)

    @staticmethod
    def _detect_city(text: str) -> str:
        """Detect city from address text."""
        text_lower = text.lower()
        city_keywords = {
            "Delhi": ["delhi", "new delhi", "narela", "jhilmil", "nangloi", "dwarka", "rohini"],
            "Gurugram": ["gurugram", "gurgaon", "sector"],
            "Noida": ["noida", "greater noida"],
            "Faridabad": ["faridabad"],
            "Ghaziabad": ["ghaziabad", "indirapuram"],
        }
        for city, keywords in city_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return city
        return ""

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                addr = rec.get("full_address") or rec.get("property_description", "")
                rec["normalized_address_hash"] = address_hash(addr)
                await upsert_bank_auction(db, rec)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
