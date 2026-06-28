"""DDA e-Services scraper — eservices.dda.org.in (DDA Bhoomi Portal)."""
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
    _infer_property_type,
    _parse_area_sqft,
    _parse_auction_with_fallback,
    _parse_currency,
    _parse_date,
    address_hash,
    upsert_bank_auction,
)

logger = logging.getLogger(__name__)

# DDA category to normalized property type mapping
_DDA_CATEGORY_MAP: dict[str, str] = {
    "residential": "plot",
    "commercial": "commercial",
    "industrial": "industrial",
    "institutional": "commercial",
    "flats": "apartment",
    "plots": "plot",
    "shops": "commercial",
    "office": "commercial",
    "group housing": "apartment",
    "mixed use": "commercial",
}

# Known DDA e-auction pages (best-effort, gracefully returns [] on failure)
_SOURCES = [
    {
        "url": "https://eservices.dda.org.in/",
        "source": AuctionSource.dda,
        "bank_name": "DDA",
    },
    {
        "url": "https://eservices.dda.org.in/eAuction/",
        "source": AuctionSource.dda,
        "bank_name": "DDA",
    },
    {
        "url": "https://dda.gov.in/e-auction",
        "source": AuctionSource.dda,
        "bank_name": "DDA",
    },
    {
        "url": "https://dda.gov.in/bhoomi-e-auction",
        "source": AuctionSource.dda,
        "bank_name": "DDA",
    },
]

_DDA_KEYWORDS = ["auction", "e-auction", "property", "plot", "flat", "shop", "commercial", "residential", "scheme", "sector"]
_DDA_CITIES = ["Delhi", "New Delhi", "North Delhi", "South Delhi", "East Delhi", "West Delhi", "Central Delhi"]


class DdaAuctionScraper(BaseScraper):
    name = "dda_auctions"

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
        """Parse DDA auction HTML using multi-strategy approach with fallback."""
        base_url = source_cfg["url"]

        def strategy_table(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 1: Parse auction tables with header validation."""
            records = []
            expected_headers = ["property", "type", "category", "sector", "locality", "reserve", "price", "emd", "date", "area", "address", "location"]
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

        def strategy_notice_list(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 2: Parse notice list items (links with auction details in text)."""
            from app.services.data_hub.utils import _parse_notice_list_items
            return _parse_notice_list_items(
                soup,
                cfg,
                _DDA_KEYWORDS,
                base_url,
                city=None,  # Will be extracted from text
                known_cities=_DDA_CITIES,
            )

        return _parse_auction_with_fallback(
            html,
            source_cfg,
            [strategy_table, strategy_notice_list],
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

        for i, h in enumerate(headers):
            if i >= len(cells):
                break
            val = cells[i]
            h_lower = h.lower()

            if "reserve" in h_lower or "price" in h_lower or "base" in h_lower or "tender" in h_lower:
                price = _parse_currency(val)
                if price is not None:
                    record["reserve_price"] = price
            elif "emd" in h_lower or "earnest" in h_lower:
                price = _parse_currency(val)
                if price is not None:
                    record["emd_amount"] = price
            elif "date" in h_lower and ("auction" in h_lower or "bid" in h_lower or "closing" in h_lower or "opening" in h_lower):
                parsed = _parse_date(val)
                if parsed:
                    record["auction_date"] = parsed
            elif "address" in h_lower or "location" in h_lower or "sector" in h_lower or "locality" in h_lower:
                if "sq" not in h_lower and "sqft" not in h_lower and "sqm" not in h_lower and "sqyd" not in h_lower:
                    record["locality"] = val
                    if not record.get("full_address"):
                        record["full_address"] = val
            elif "property" in h_lower or "type" in h_lower or "category" in h_lower or "scheme" in h_lower:
                normalized = _infer_property_type(val, _DDA_CATEGORY_MAP)
                if normalized:
                    record["property_type"] = normalized
                if val and not record["property_description"]:
                    record["property_description"] = val
            elif ("area" in h_lower or "size" in h_lower) and ("sq" in h_lower or "yard" in h_lower or "sqm" in h_lower or "sqyd" in h_lower or "ft" in h_lower or "meter" in h_lower):
                area = _parse_area_sqft(val)
                if area is not None:
                    record["area_sqft"] = area

        # Fallback: if no auction_date found, use sentinel
        if "auction_date" not in record:
            record["auction_date"] = date(1970, 1, 1).isoformat()

        # Build property description if missing
        if not record.get("property_description"):
            parts = [record.get("locality", ""), record.get("property_type", "")]
            record["property_description"] = " - ".join(p for p in parts if p) or "DDA Auction Property"

        # Infer property_type from description if still missing
        if "property_type" not in record:
            desc_lower = record["property_description"].lower()
            if "residential" in desc_lower or "plot" in desc_lower or "flat" in desc_lower:
                record["property_type"] = "plot"
            elif "commercial" in desc_lower or "shop" in desc_lower or "booth" in desc_lower or "office" in desc_lower:
                record["property_type"] = "commercial"
            elif "industrial" in desc_lower:
                record["property_type"] = "industrial"

        # Extract city from text if not hardcoded
        if "city" not in record:
            full_text = " ".join([record.get("property_description", ""), record.get("locality", ""), record.get("full_address", "")])
            for city in _DDA_CITIES:
                if city.lower() in full_text.lower():
                    record["city"] = city
                    break
            if "city" not in record:
                record["city"] = "Delhi"  # fallback

        # Set full_address from locality + city if not already set
        if not record.get("full_address"):
            locality = record.get("locality", "")
            city = record.get("city", "Delhi")
            record["full_address"] = f"{locality}, {city}".strip(", ").strip()

        return record if record.get("property_description") else None

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                addr = rec.get("full_address") or rec.get("property_description", "")
                rec["normalized_address_hash"] = address_hash(addr)
                rec.setdefault("city", "Delhi")
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
                logger.warning("Failed to upsert DDA auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
