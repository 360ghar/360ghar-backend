"""DRT auction scraper — Debt Recovery Tribunal Delhi benches (DRT-I and DRT-II)
for court-ordered property sales under RDDBFI/SARFAESI Acts."""
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

_DRT_BASE_URL = "https://drt.gov.in"
_DRT_DELHI_I_URL = "https://drt.gov.in/drt1delhi/auction-notices"
_DRT_DELHI_II_URL = "https://drt.gov.in/drt2delhi/auction-notices"
_DRT_SEARCH_URL = "https://drt.gov.in/case-status-search"

_DRT_BENCHES = [
    {"url": _DRT_DELHI_I_URL, "bench": "DRT-I Delhi"},
    {"url": _DRT_DELHI_II_URL, "bench": "DRT-II Delhi"},
]


class DRTAuctionScraper(BaseScraper):
    name = "drt_auctions"
    source = AuctionSource.drt

    async def _scrape(self) -> list[dict]:
        results = []

        # Scrape each Delhi bench
        for bench_cfg in _DRT_BENCHES:
            try:
                html = await self._fetch_url(bench_cfg["url"])
                parsed = self._parse_auction_notices(html, bench_cfg)
                results.extend(parsed)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", bench_cfg["url"], e)
            await asyncio.sleep(2)

        # Also try the main search/listing page
        try:
            html = await self._fetch_url(_DRT_SEARCH_URL)
            parsed = self._parse_search_page(html)
            results.extend(parsed)
        except Exception as e:
            logger.warning("Failed to scrape %s: %s", _DRT_SEARCH_URL, e)

        return results

    def _parse_auction_notices(self, html: str, bench_cfg: dict) -> list[dict]:
        """Parse DRT auction notice listings (table-based)."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not headers:
                first_row = table.find("tr")
                if first_row:
                    headers = [td.get_text(strip=True).lower() for td in first_row.find_all("td")]

            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue

                # Extract detail link if available
                link_tag = row.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else ""
                if link_url and not link_url.startswith("http"):
                    link_url = f"{_DRT_BASE_URL}/{link_url.lstrip('/')}"

                record: dict[str, Any] = {
                    "source": AuctionSource.drt,
                    "bank_name": bench_cfg["bench"],
                    "property_description": cells[0] if cells else "",
                    "city": "Delhi",
                    "source_url": link_url or bench_cfg["url"],
                    "raw_data": {"headers": headers, "cells": cells, "bench": bench_cfg["bench"], "detail_url": link_url},
                }

                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if not val:
                        continue

                    if "case" in h and "number" in h or "case" in h and "no" in h:
                        record["bank_name"] = f"{bench_cfg['bench']} — {val}"
                    elif "borrower" in h or "debtor" in h or "defendant" in h:
                        record["property_description"] = val
                    elif "property" in h and ("description" in h or "detail" in h):
                        record["property_description"] = val
                        record["full_address"] = val
                    elif "address" in h or "location" in h:
                        record["full_address"] = val
                    elif "reserve" in h or "price" in h or "value" in h:
                        try:
                            record["reserve_price"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "emd" in h or "earnest" in h:
                        try:
                            record["emd_amount"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "auction" in h and "date" in h or "sale" in h and "date" in h:
                        record["auction_date"] = self._parse_date(val)
                    elif "type" in h and "property" in h:
                        record["property_type"] = val

                # Fallback: use full row text as address
                if not record.get("full_address"):
                    record["full_address"] = " ".join(cells)

                # Detect city from content
                detected_city = self._detect_city(record.get("full_address", ""))
                if detected_city:
                    record["city"] = detected_city

                if record.get("property_description"):
                    records.append(record)

        # Try notice/list cards as fallback
        if not records:
            for item in soup.find_all(["div", "li"], class_=re.compile(r"notice|auction|listing", re.I)):
                text = item.get_text(separator=" ", strip=True)
                if not text or len(text) < 15:
                    continue
                link_tag = item.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else bench_cfg["url"]

                record = {
                    "source": AuctionSource.drt,
                    "bank_name": bench_cfg["bench"],
                    "property_description": text[:500],
                    "full_address": text[:500],
                    "city": "Delhi",
                    "source_url": link_url,
                    "raw_data": {"text": text[:1000], "bench": bench_cfg["bench"]},
                }
                records.append(record)

        return records

    def _parse_search_page(self, html: str) -> list[dict]:
        """Parse the main DRT search/listing page for any Delhi auction references."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                row_text = " ".join(cells).lower()
                # Only include rows that reference auctions or Delhi benches
                if "auction" not in row_text and "delhi" not in row_text:
                    continue

                link_tag = row.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else _DRT_SEARCH_URL

                record = {
                    "source": AuctionSource.drt,
                    "bank_name": "DRT Delhi",
                    "property_description": cells[0] if cells else "",
                    "full_address": " ".join(cells),
                    "city": "Delhi",
                    "source_url": link_url,
                    "raw_data": {"headers": headers, "cells": cells},
                }
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
            "Delhi": ["delhi", "new delhi", "narela", "jhilmil", "nangloi", "dwarka", "rohini", "saket"],
            "Gurugram": ["gurugram", "gurgaon"],
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
