"""Aggregator e-auction scraper — BankEAuctions.com and eAuctionsIndia.com."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import address_hash, upsert_bank_auction

logger = logging.getLogger(__name__)

_SOURCES = [
    {
        "url": "https://bankeauctions.com",
        "source": AuctionSource.bank_eauctions,
        "bank": "BankEAuctions",
    },
    {
        "url": "https://eauctionsindia.com",
        "source": AuctionSource.eauctions_india,
        "bank": "eAuctionsIndia",
    },
]

# City detection keywords → canonical city name
_CITY_KEYWORDS = [
    (r"\bgurgaon\b", "Gurugram"),
    (r"\bgurugram\b", "Gurugram"),
    (r"\bdelhi\b", "Delhi"),
    (r"\bmeerut\b", "Meerut"),
    (r"\bnoida\b", "Noida"),
    (r"\bgreater noida\b", "Greater Noida"),
    (r"\bfaridabad\b", "Faridabad"),
    (r"\bghaziabad\b", "Ghaziabad"),
]


def _detect_city(text: str) -> str:
    """Try to detect city from listing content; default to Gurugram."""
    text_lower = text.lower()
    # Check longer phrases first to avoid partial matches
    for pattern, city in sorted(_CITY_KEYWORDS, key=lambda x: -len(x[0])):
        if re.search(pattern, text_lower):
            return city
    return "Gurugram"


def _parse_price(val: str) -> float | None:
    """Extract a numeric price from a string like '₹12,50,000' or '1250000'."""
    if not val:
        return None
    cleaned = val.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    # Handle Lakh / Crore notation
    cleaned_lower = cleaned.lower()
    try:
        if "lakh" in cleaned_lower or "lac" in cleaned_lower:
            num = float(re.sub(r"[^\d.]", "", cleaned.split()[0]))
            return num * 100000
        if "crore" in cleaned_lower or "cr" in cleaned_lower:
            num = float(re.sub(r"[^\d.]", "", cleaned.split()[0]))
            return num * 10000000
    except (ValueError, IndexError):
        pass
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(val: str) -> date | None:
    """Try common Indian date formats."""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


class AggregatorEauctionsScraper(BaseScraper):
    name = "aggregator_eauctions"

    async def _scrape(self) -> list[dict]:
        results = []
        for source_cfg in _SOURCES:
            try:
                html = await self._fetch_url(source_cfg["url"])
                parsed = self._parse_auction_html(html, source_cfg)
                results.extend(parsed)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("Failed to scrape aggregator %s: %s", source_cfg["url"], e)
        return results

    def _parse_auction_html(self, html: str, source_cfg: dict) -> list[dict]:
        """Best-effort parse of aggregator site auction listings."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # Strategy 1: Standard HTML tables
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:  # skip header
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                record = self._build_record(cells, headers, source_cfg)
                if record:
                    records.append(record)

        # Strategy 2: Card/listing divs (common on aggregator sites)
        for card in soup.find_all(["div", "article"], class_=re.compile(r"auction|listing|property|card", re.I)):
            text = card.get_text(separator=" ", strip=True)
            if not text or len(text) < 10:
                continue
            # Try to extract structured data from card text
            record = {
                "source": source_cfg["source"],
                "bank_name": source_cfg["bank"],
                "property_description": text[:500],
                "source_url": source_cfg["url"],
                "raw_data": {"card_text": text[:1000]},
            }
            # Try price extraction from card text
            price_match = re.search(r"(?:Reserve\s*Price|Base\s*Price|EMD)[:\s]*[₹Rs.]?\s*([\d,]+(?:\.\d+)?)", text, re.I)
            if price_match:
                price = _parse_price(price_match.group(1))
                if price is not None:
                    record["reserve_price"] = price
            # Try date extraction
            date_match = re.search(r"(?:Auction\s*Date|Bid\s*Date|Sale\s*Date)[:\s]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})", text, re.I)
            if date_match:
                parsed = _parse_date(date_match.group(1))
                if parsed:
                    record["auction_date"] = parsed
            # Detect city from full card text
            record["city"] = _detect_city(text)
            if record.get("property_description"):
                records.append(record)

        return records

    def _build_record(self, cells: list[str], headers: list[str], source_cfg: dict) -> dict | None:
        """Build a record from table row cells and headers."""
        record = {
            "source": source_cfg["source"],
            "bank_name": source_cfg["bank"],
            "property_description": cells[0] if cells else "",
            "source_url": source_cfg["url"],
            "raw_data": {"headers": headers, "cells": cells},
        }

        for i, h in enumerate(headers):
            if i >= len(cells):
                break
            val = cells[i]

            if "reserve" in h or "base" in h or "price" in h or "amount" in h:
                price = _parse_price(val)
                if price is not None:
                    record["reserve_price"] = price
            elif "emd" in h or "earnest" in h:
                price = _parse_price(val)
                if price is not None:
                    record["emd_amount"] = price
            elif "date" in h and ("auction" in h or "bid" in h or "sale" in h):
                parsed = _parse_date(val)
                if parsed:
                    record["auction_date"] = parsed
            elif "address" in h or "location" in h or "property" in h or "description" in h:
                record["full_address"] = val
            elif "bank" in h or "institution" in h:
                record["bank_name"] = val
            elif "city" in h or "district" in h:
                record["city"] = val
            elif "type" in h or "category" in h:
                record["property_type"] = val.lower().strip()
            elif "area" in h or "size" in h or "sqft" in h or "sqm" in h or "sqyd" in h:
                area_val = re.sub(r"[^\d.]", "", val.replace(",", ""))
                try:
                    record["area_sqft"] = float(area_val)
                except ValueError:
                    pass

        # Detect city from combined text if not explicitly set
        if not record.get("city"):
            combined = " ".join(cells)
            record["city"] = _detect_city(combined)

        if record.get("property_description"):
            return record
        return None

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
                logger.warning("Failed to upsert aggregator e-auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
