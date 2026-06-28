"""YEIDA (Yamuna Expressway Industrial Development Authority) auction scraper."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import (
    _extract_city_from_text,
    _infer_property_type,
    _parse_area_sqft,
    _parse_auction_with_fallback,
    _parse_currency,
    _parse_date,
    _parse_notice_list_items,
    address_hash,
    upsert_bank_auction,
)

logger = logging.getLogger(__name__)

_SOURCES = [
    {
        "url": "https://yamunaexpresswayauthority.com",
        "source": AuctionSource.yeida,
    },
    {
        "url": "https://yamunaexpresswayauthority.com/auction.php",
        "source": AuctionSource.yeida,
    },
]

# YEIDA category mapping
_YEIDA_CATEGORY_MAP = {
    "commercial plot": "commercial",
    "industrial plot": "industrial",
    "institutional": "institutional",
    "institutional land": "institutional",
    "residential plot": "plot",
    "plot": "plot",
    "shop": "commercial",
    "flat": "apartment",
    "apartment": "apartment",
    "group housing": "apartment",
    "built up": "house",
    "factory": "industrial",
}

# Cities/areas in YEIDA jurisdiction
_YEIDA_CITIES = [
    "Greater Noida", "Noida", "Yamuna Expressway", "Jewar", "Dankaur",
    "Rabupura", "Tappal", "Khurja", "Bulandshahr", "Gautam Buddh Nagar",
    "Ghaziabad", "Hapur", "Aligarh", "Mathura", "Agra",
]


class YeidaAuctionScraper(BaseScraper):
    name = "yeida_auctions"

    async def _scrape(self) -> list[dict]:
        results = []
        for source_cfg in _SOURCES:
            try:
                html = await self._fetch_url(source_cfg["url"])
                parsed = self._parse_auction_html(html, source_cfg)
                results.extend(parsed)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("Failed to scrape YEIDA %s: %s", source_cfg["url"], e)
        return results

    def _parse_auction_html(self, html: str, source_cfg: dict) -> list[dict]:
        """Parse YEIDA auction HTML using multi-strategy approach with fallback."""
        base_url = source_cfg["url"]

        def strategy_table(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 1: Parse auction tables with header validation."""
            records = []
            expected_headers = ["plot", "sector", "category", "area", "size", "reserve", "price", "emd", "date", "scheme", "location"]
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
            """Strategy 2: Parse notice list items with city extraction from text."""
            return _parse_notice_list_items(
                soup,
                cfg,
                ["auction", "e-auction", "property", "plot", "flat", "shop", "commercial", "industrial", "scheme", "sector"],
                base_url,
                city=None,  # Will be extracted from text
                known_cities=_YEIDA_CITIES,
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
            "bank_name": "YEIDA",
            "property_description": cells[0] if cells else "",
            "source_url": source_cfg["url"],
            "raw_data": {"headers": headers, "cells": cells},
        }

        for i, h in enumerate(headers):
            if i >= len(cells):
                break
            val = cells[i]
            h_lower = h.lower()

            if "reserve" in h_lower or "base" in h_lower or "price" in h_lower or "amount" in h_lower:
                price = _parse_currency(val)
                if price is not None:
                    record["reserve_price"] = price
            elif "emd" in h_lower or "earnest" in h_lower:
                price = _parse_currency(val)
                if price is not None:
                    record["emd_amount"] = price
            elif "date" in h_lower and ("auction" in h_lower or "bid" in h_lower or "sale" in h_lower):
                parsed = _parse_date(val)
                if parsed:
                    record["auction_date"] = parsed
            elif "address" in h_lower or "location" in h_lower or "property" in h_lower or "description" in h_lower:
                record["full_address"] = val
            elif "sector" in h_lower or "locality" in h_lower or "scheme" in h_lower:
                record["locality"] = val
            elif ("area" in h_lower and ("sq" in h_lower or "size" in h_lower)) or "sqft" in h_lower or "sqm" in h_lower or "sqyd" in h_lower or "size" in h_lower:
                area = _parse_area_sqft(val)
                if area is not None:
                    record["area_sqft"] = area
            elif "type" in h_lower or "category" in h_lower:
                ptype = _infer_property_type(val, _YEIDA_CATEGORY_MAP)
                if ptype:
                    record["property_type"] = ptype

        # Fallback: infer property_type from description if not set
        if not record.get("property_type") and record.get("property_description"):
            ptype = _infer_property_type(record["property_description"], _YEIDA_CATEGORY_MAP)
            if ptype:
                record["property_type"] = ptype

        if "auction_date" not in record:
            record["auction_date"] = date(1970, 1, 1).isoformat()

        # Extract city from text (not hardcoded)
        if "city" not in record:
            full_text = " ".join([
                record.get("property_description", ""),
                record.get("locality", ""),
                record.get("full_address", ""),
            ])
            city = _extract_city_from_text(full_text, _YEIDA_CITIES)
            if city:
                record["city"] = city
            else:
                record["city"] = "Greater Noida"  # fallback

        # Set full_address from locality + city if not already set
        if not record.get("full_address"):
            locality = record.get("locality", "")
            city = record.get("city", "Greater Noida")
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
                # Ensure auction_date is a date object
                if isinstance(rec.get("auction_date"), str):
                    from datetime import datetime
                    try:
                        rec["auction_date"] = datetime.fromisoformat(rec["auction_date"]).date()
                    except ValueError:
                        rec["auction_date"] = date(1970, 1, 1)
                await upsert_bank_auction(db, rec)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert YEIDA auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
