"""HSVP e-Auction Portal scraper — eauction.hsvphry.org.in."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import (
    BANK_AUCTION_EXTENDED_SET,
    _extract_city_from_text,
    _infer_property_type,
    _parse_area_sqft,
    _parse_auction_with_fallback,
    _parse_currency,
    _parse_date,
    address_hash,
    upsert_bank_auction,
)

logger = logging.getLogger(__name__)

# HSVP category to normalized property type mapping
_HSVP_CATEGORY_MAP: dict[str, str] = {
    "residential plot": "plot",
    "commercial site": "commercial",
    "industrial plot": "industrial",
    "institutional": "commercial",
}

# HSVP districts/cities in Haryana
_HSVP_CITIES = [
    "Gurugram", "Faridabad", "Panchkula", "Ambala", "Yamunanagar",
    "Kurukshetra", "Kaithal", "Karnal", "Panipat", "Sonipat",
    "Rohtak", "Jhajjar", "Rewari", "Mahendragarh", "Bhiwani",
    "Hisar", "Fatehabad", "Sirsa", "Jind", "Palwal", "Nuh",
    "Charkhi Dadri",
]

# Known HSVP e-auction pages (best-effort, gracefully returns [] on failure)
_SOURCES = [
    {
        "url": "https://eauction.hsvphry.org.in/",
        "source": AuctionSource.hsvp,
        "bank_name": "HSVP",
    },
    {
        "url": "https://eauction.hsvphry.org.in/eauction/",
        "source": AuctionSource.hsvp,
        "bank_name": "HSVP",
    },
    {
        "url": "https://hsvphry.org.in/e-auction-scheme-list",
        "source": AuctionSource.hsvp,
        "bank_name": "HSVP",
    },
    {
        "url": "https://hsvphry.org.in/scheme-list",
        "source": AuctionSource.hsvp,
        "bank_name": "HSVP",
    },
]


class HsvpAuctionScraper(BaseScraper):
    name = "hsvp_auctions"

    async def _scrape(self) -> list[dict]:
        results: list[dict] = []
        for source_cfg in _SOURCES:
            try:
                html = await self._fetch_url(source_cfg["url"])
                parsed = self._parse_auction_html(html, source_cfg)
                results.extend(parsed)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", source_cfg["url"], e)
            await asyncio.sleep(2)
        return results

    def _parse_auction_html(self, html: str, source_cfg: dict) -> list[dict]:
        """Parse HSVP auction HTML using multi-strategy approach with fallback."""

        def strategy_table(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 1: Parse auction tables with header validation."""
            records = []
            expected_headers = ["estate", "sector", "plot", "category", "area", "reserve", "price", "emd", "date", "location", "address"]
            for table in soup.find_all("table"):
                headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
                # Validate headers match expected pattern
                matched = sum(1 for eh in expected_headers if any(eh in h for h in headers))
                if matched < 2:
                    continue
                for row in table.find_all("tr")[1:]:
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cells) < 2:
                        continue
                    record = self._parse_table_row(cfg, headers, cells)
                    if record:
                        records.append(record)
            return records

        def strategy_estate_location(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 2: Parse estate/location based listings (e.g., 'Sector 12, Faridabad')."""
            records = []
            # Look for estate location patterns in text content
            for elem in soup.find_all(["div", "span", "td", "li", "p"]):
                text = elem.get_text(strip=True)
                if not text or len(text) < 10:
                    continue
                # Check for HSVP estate pattern: "Sector XX, City" or "Estate Name, City"
                import re
                estate_match = re.search(r"(?:sector|estate|scheme)\s+[\w\s]+,\s*(\w+)", text, re.IGNORECASE)
                if estate_match:
                    city = estate_match.group(1)
                    if city in _HSVP_CITIES:
                        # Find nearby auction details
                        record = self._extract_from_location_context(elem, cfg, city)
                        if record:
                            records.append(record)
            return records

        return _parse_auction_with_fallback(
            html,
            source_cfg,
            [strategy_table, strategy_estate_location],
        )

    def _parse_table_row(self, source_cfg: dict, headers: list[str], cells: list[str]) -> dict | None:
        """Parse a single table row into a record."""
        record: dict = {
            "source": source_cfg["source"],
            "bank_name": source_cfg["bank_name"],
            "property_description": cells[0] if cells else "",
            "source_url": source_cfg["url"],
            "raw_data": {"headers": headers, "cells": cells},
        }

        estate_location = None

        for i, h in enumerate(headers):
            if i >= len(cells):
                break
            val = cells[i]
            h_lower = h.lower()

            if "reserve" in h_lower or "price" in h_lower or "base" in h_lower:
                price = _parse_currency(val)
                if price is not None:
                    record["reserve_price"] = price
            elif "emd" in h_lower:
                price = _parse_currency(val)
                if price is not None:
                    record["emd_amount"] = price
            elif "date" in h_lower and ("auction" in h_lower or "bid" in h_lower or "eauction" in h_lower):
                parsed = _parse_date(val)
                if parsed:
                    record["auction_date"] = parsed
            elif "address" in h_lower or "location" in h_lower or "sector" in h_lower or "locality" in h_lower:
                record["locality"] = val
                if not record.get("full_address"):
                    record["full_address"] = val
                # Capture estate_location for city extraction
                if "estate" in h_lower or "location" in h_lower:
                    estate_location = val
            elif "property" in h_lower or "type" in h_lower or "category" in h_lower or "scheme" in h_lower:
                normalized = _infer_property_type(val, _HSVP_CATEGORY_MAP)
                if normalized:
                    record["property_type"] = normalized
                if val and not record["property_description"]:
                    record["property_description"] = val
            elif "area" in h_lower or "size" in h_lower or "sq" in h_lower or "yard" in h_lower or "sqm" in h_lower:
                area = _parse_area_sqft(val)
                if area is not None:
                    record["area_sqft"] = area

        # Fallback: if no auction_date found, use sentinel
        if "auction_date" not in record:
            record["auction_date"] = date(1970, 1, 1).isoformat()

        # Build property description if missing
        if not record.get("property_description"):
            parts = [record.get("locality", ""), record.get("property_type", "")]
            record["property_description"] = " - ".join(p for p in parts if p) or "HSVP Auction Property"

        # Infer property_type from description if still missing
        if "property_type" not in record:
            desc_lower = record["property_description"].lower()
            if "residential" in desc_lower or "plot" in desc_lower:
                record["property_type"] = "plot"
            elif "commercial" in desc_lower or "shop" in desc_lower or "booth" in desc_lower:
                record["property_type"] = "commercial"
            elif "industrial" in desc_lower:
                record["property_type"] = "industrial"

        # Extract city from estate_location column or other text
        if "city" not in record:
            # First try estate_location column
            if estate_location:
                city = _extract_city_from_text(estate_location, _HSVP_CITIES)
                if city:
                    record["city"] = city
            # Then try other fields
            if "city" not in record:
                full_text = " ".join([
                    record.get("property_description", ""),
                    record.get("locality", ""),
                    record.get("full_address", ""),
                ])
                city = _extract_city_from_text(full_text, _HSVP_CITIES)
                if city:
                    record["city"] = city
            # Fallback
            if "city" not in record:
                record["city"] = "Gurugram"

        # Set full_address from locality + city if not already set
        if not record.get("full_address"):
            locality = record.get("locality", "")
            city = record.get("city", "Gurugram")
            record["full_address"] = f"{locality}, {city}".strip(", ").strip()

        return record if record.get("property_description") else None

    def _extract_from_location_context(self, elem, source_cfg: dict, city: str) -> dict | None:
        """Extract auction details from elements near a location match."""
        # Look for sibling/parent elements that might contain auction data
        parent = elem.parent if elem.parent else elem
        text = parent.get_text(strip=True) if parent else ""
        if not text:
            return None

        record: dict = {
            "source": source_cfg["source"],
            "bank_name": source_cfg["bank_name"],
            "city": city,
            "property_description": text[:500],
            "source_url": source_cfg["url"],
            "raw_data": {"extracted_from": text[:200]},
        }

        # Parse common fields from the context text
        import re
        date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text)
        if date_match:
            parsed = _parse_date(date_match.group(1))
            if parsed:
                record["auction_date"] = parsed

        price_match = re.search(r"(?:reserve|base|price)[\s:]*[₹Rs]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
        if price_match:
            record["reserve_price"] = _parse_currency(price_match.group(1))

        emd_match = re.search(r"emd[\s:]*[₹Rs]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
        if emd_match:
            record["emd_amount"] = _parse_currency(emd_match.group(1))

        area_match = re.search(r"(?:area|size)[\s:]*([\d,]+\.?\d*\s*(?:sq\.?\s*(?:ft|yd|m|yard|meter|acre)))", text, re.IGNORECASE)
        if area_match:
            record["area_sqft"] = _parse_area_sqft(area_match.group(1))

        # Extract locality/sector
        sector_match = re.search(r"(?:sector|scheme|estate)[\s:]*([A-Za-z0-9\s\-]+)", text, re.IGNORECASE)
        if sector_match:
            record["locality"] = sector_match.group(1).strip()

        if not record.get("auction_date"):
            record["auction_date"] = date(1970, 1, 1).isoformat()

        record["full_address"] = f"{record.get('locality', '')}, {city}".strip(", ").strip()
        return record

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                addr = rec.get("full_address") or rec.get("property_description", "")
                rec["normalized_address_hash"] = address_hash(addr)
                rec.setdefault("city", "Gurugram")
                # Ensure auction_date is a date object
                if isinstance(rec.get("auction_date"), str):
                    from datetime import datetime
                    try:
                        rec["auction_date"] = datetime.fromisoformat(rec["auction_date"]).date()
                    except ValueError:
                        rec["auction_date"] = date(1970, 1, 1)
                await upsert_bank_auction(db, rec, set_fields=BANK_AUCTION_EXTENDED_SET)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert HSVP auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
