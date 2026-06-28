"""DFC Delhi auction scraper — Delhi Development Authority (DSIDC/DFC) public auctions
for industrial plots, sheds, and commercial land in Narela, Jhilmil, Nangloi etc."""
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

_DFC_AUCTION_URL = "https://dfc.delhi.gov.in/dfc/public-auction"
_DFC_TENDER_URL = "https://dfc.delhi.gov.in/dfc/tenders"
_DFC_NEWS_URL = "https://dfc.delhi.gov.in/dfc/news-updates"


class DFCDelhiAuctionScraper(BaseScraper):
    name = "dfc_delhi_auctions"
    source = AuctionSource.dfc_delhi

    async def _scrape(self) -> list[dict]:
        results = []
        urls = [_DFC_AUCTION_URL, _DFC_TENDER_URL, _DFC_NEWS_URL]

        for url in urls:
            try:
                html = await self._fetch_url(url)
                parsed = self._parse_auction_page(html, url)
                results.extend(parsed)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", url, e)
            await asyncio.sleep(2)

        return results

    def _parse_auction_page(self, html: str, source_url: str) -> list[dict]:
        """Parse DFC Delhi public auction notices and tender listings."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # Parse auction/tender tables
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

                # Try to extract a detail link
                link_tag = row.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else ""
                if link_url and not link_url.startswith("http"):
                    link_url = f"https://dfc.delhi.gov.in{link_url}"

                record: dict[str, Any] = {
                    "source": AuctionSource.dfc_delhi,
                    "bank_name": "DSIDC/DFC Delhi",
                    "property_description": cells[0] if cells else "",
                    "city": "Delhi",
                    "source_url": link_url or source_url,
                    "raw_data": {"headers": headers, "cells": cells, "detail_url": link_url},
                }

                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if not val:
                        continue

                    if "property" in h or "plot" in h or "shed" in h or "unit" in h:
                        record["property_description"] = val
                        record["full_address"] = self._enrich_address(val)
                    elif "type" in h:
                        record["property_type"] = self._classify_type(val)
                    elif "area" in h or "size" in h or "sq" in h:
                        area_sqft = self._parse_area(val)
                        if area_sqft:
                            record["area_sqft"] = area_sqft
                    elif "reserve" in h or "price" in h or "base" in h or "bid" in h:
                        try:
                            record["reserve_price"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "emd" in h or "earnest" in h or "deposit" in h:
                        try:
                            record["emd_amount"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "date" in h and ("auction" in h or "bid" in h or "tender" in h):
                        record["auction_date"] = self._parse_date(val)
                    elif "location" in h or "address" in h or "area" in h or "place" in h:
                        record["full_address"] = self._enrich_address(val)

                # Ensure full_address is set; fall back to property description
                if not record.get("full_address"):
                    record["full_address"] = record.get("property_description", "")

                # Classify property type from description if not already set
                if not record.get("property_type"):
                    desc = (record.get("property_description", "") + " " + record.get("full_address", "")).lower()
                    record["property_type"] = self._classify_type(desc)

                if record.get("property_description"):
                    records.append(record)

        # Also try notice/article cards (DFC sometimes lists auctions as news items)
        if not records:
            for item in soup.find_all(["div", "li"], class_=re.compile(r"auction|notice|tender|news", re.I)):
                text = item.get_text(separator=" ", strip=True)
                if not text or len(text) < 15:
                    continue
                link_tag = item.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else source_url
                if link_url and not link_url.startswith("http"):
                    link_url = f"https://dfc.delhi.gov.in{link_url}"

                record = {
                    "source": AuctionSource.dfc_delhi,
                    "bank_name": "DSIDC/DFC Delhi",
                    "property_description": text[:500],
                    "full_address": text[:500],
                    "city": "Delhi",
                    "source_url": link_url,
                    "raw_data": {"text": text[:1000]},
                }
                records.append(record)

        return records

    @staticmethod
    def _enrich_address(text: str) -> str:
        """Prepend 'Delhi — ' to addresses that mention known DFC industrial areas."""
        known_areas = ["narela", "jhilmil", "nangloi", "okhla", "wazirpur", "mohan cooperative", "badli"]
        text_lower = text.lower()
        if any(area in text_lower for area in known_areas):
            if "delhi" not in text_lower:
                return f"Delhi — {text}"
        return text

    @staticmethod
    def _classify_type(text: str) -> str:
        """Classify property type from text."""
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["industrial", "factory", "shed"]):
            return "industrial"
        elif any(kw in text_lower for kw in ["commercial", "shop", "office", "showroom"]):
            return "commercial"
        elif any(kw in text_lower for kw in ["plot", "land"]):
            return "plot"
        elif any(kw in text_lower for kw in ["flat", "apartment", "residential"]):
            return "residential"
        return "industrial"  # DFC default

    @staticmethod
    def _parse_area(val: str) -> float | None:
        """Extract area in sqft from text like '500 sqft', '50 sqm', '200 sqyd'."""
        # sqft
        m = re.search(r"([\d,.]+)\s*(?:sq\s*ft|sft|sqft)", val, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
        # sqm → sqft (1 sqm = 10.764 sqft)
        m = re.search(r"([\d,.]+)\s*(?:sq\s*m|sqm)", val, re.I)
        if m:
            try:
                return round(float(m.group(1).replace(",", "")) * 10.764, 2)
            except ValueError:
                pass
        # sqyd → sqft (1 sqyd = 9 sqft)
        m = re.search(r"([\d,.]+)\s*(?:sq\s*yd|sqyd|sq\.?\s*yards?)", val, re.I)
        if m:
            try:
                return round(float(m.group(1).replace(",", "")) * 9, 2)
            except ValueError:
                pass
        return None

    @staticmethod
    def _parse_date(val: str) -> date:
        """Attempt multiple date formats."""
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                continue
        return date(1970, 1, 1)

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
