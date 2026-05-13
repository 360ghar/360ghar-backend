"""YEIDA (Yamuna Expressway Industrial Development Authority) auction scraper."""
import asyncio
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import BankAuction
from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import address_hash

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


def _infer_property_type(text: str) -> str | None:
    """Guess property_type from description text using YEIDA categories."""
    text_lower = text.lower()
    # Check multi-word phrases first (longer match wins)
    for keyword in sorted(_YEIDA_CATEGORY_MAP.keys(), key=len, reverse=True):
        if keyword in text_lower:
            return _YEIDA_CATEGORY_MAP[keyword]
    return None


def _parse_price(val: str) -> float | None:
    """Extract a numeric price from a string like '₹12,50,000' or '1250000'."""
    if not val:
        return None
    cleaned = val.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(val: str) -> date | None:
    """Try common Indian date formats."""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


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
        """Best-effort parse of YEIDA auction table rows."""
        soup = BeautifulSoup(html, "lxml")
        records = []

        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:  # skip header
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue

                record = {
                    "source": source_cfg["source"],
                    "bank_name": "YEIDA",
                    "property_description": cells[0] if cells else "",
                    "source_url": source_cfg["url"],
                    "city": "Greater Noida",
                    "raw_data": {"headers": headers, "cells": cells},
                }

                # Try to map common column names
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
                    elif "sector" in h or "locality" in h or "scheme" in h:
                        record["locality"] = val
                    elif ("area" in h and ("sq" in h or "size" in h)) or "sqft" in h or "sqm" in h or "sqyd" in h or "size" in h:
                        area_val = re.sub(r"[^\d.]", "", val.replace(",", ""))
                        try:
                            record["area_sqft"] = float(area_val)
                        except ValueError:
                            pass
                    elif "type" in h or "category" in h:
                        ptype = _infer_property_type(val)
                        if ptype:
                            record["property_type"] = ptype

                # Fallback: infer property_type from description if not set
                if not record.get("property_type") and record.get("property_description"):
                    ptype = _infer_property_type(record["property_description"])
                    if ptype:
                        record["property_type"] = ptype

                if record.get("property_description"):
                    records.append(record)

        return records

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                addr = rec.get("full_address") or rec.get("property_description", "")
                rec["normalized_address_hash"] = address_hash(addr)
                rec.setdefault("is_active", True)
                rec.setdefault("auction_date", date(1970, 1, 1))
                stmt = pg_insert(BankAuction).values(
                    **{
                        k: v
                        for k, v in rec.items()
                        if hasattr(BankAuction, k) and k not in ("id", "created_at", "updated_at")
                    }
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_bank_auctions_key",
                    set_={
                        "reserve_price": stmt.excluded.reserve_price,
                        "emd_amount": stmt.excluded.emd_amount,
                        "raw_data": stmt.excluded.raw_data,
                        "is_active": True,
                        "source_url": stmt.excluded.source_url,
                    },
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert YEIDA auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
