"""DDA e-Services scraper — eservices.dda.org.in (DDA Bhoomi Portal)."""
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


def _normalize_category(raw: str) -> str | None:
    """Map DDA category text to a normalized property_type value."""
    if not raw:
        return None
    key = raw.strip().lower()
    # Direct match
    if key in _DDA_CATEGORY_MAP:
        return _DDA_CATEGORY_MAP[key]
    # Partial match
    for cat_key, cat_val in _DDA_CATEGORY_MAP.items():
        if cat_key in key:
            return cat_val
    return None


def _parse_price(val: str) -> float | None:
    """Extract a numeric price from a string like '₹ 1,25,00,000' or '12500000'."""
    if not val:
        return None
    cleaned = val.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    # Remove any remaining non-numeric chars except dot
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(val: str) -> date | None:
    """Try common Indian date formats."""
    if not val:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


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
        """Best-effort parse of DDA auction table rows."""
        soup = BeautifulSoup(html, "lxml")
        records: list[dict] = []

        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:  # skip header row
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue

                record: dict = {
                    "source": source_cfg["source"],
                    "bank_name": source_cfg["bank_name"],
                    "city": "Delhi",
                    "property_description": cells[0] if cells else "",
                    "source_url": source_cfg["url"],
                    "raw_data": {"headers": headers, "cells": cells},
                }

                # Map common column names to record fields
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]

                    if "reserve" in h or "price" in h or "base" in h or "tender" in h:
                        price = _parse_price(val)
                        if price is not None:
                            record["reserve_price"] = price
                    elif "emd" in h or "earnest" in h:
                        price = _parse_price(val)
                        if price is not None:
                            record["emd_amount"] = price
                    elif "date" in h and ("auction" in h or "bid" in h or "closing" in h or "opening" in h):
                        parsed_date = _parse_date(val)
                        if parsed_date:
                            record["auction_date"] = parsed_date
                    elif "address" in h or "location" in h or "sector" in h or "locality" in h or "area" in h and "sq" not in h:
                        # Avoid matching "area in sqft" type headers as locality
                        if "sq" not in h and "sqft" not in h and "sqm" not in h and "sqyd" not in h:
                            record["locality"] = val
                            if not record.get("full_address"):
                                record["full_address"] = val
                    elif "property" in h or "type" in h or "category" in h or "scheme" in h:
                        normalized = _normalize_category(val)
                        if normalized:
                            record["property_type"] = normalized
                        # Also use as description if first cell is empty
                        if val and not record["property_description"]:
                            record["property_description"] = val
                    elif ("area" in h or "size" in h or "sq" in h or "yard" in h or "sqm" in h) and ("sq" in h or "yard" in h or "sqm" in h or "size" in h or "area" in h):
                        # Try to parse area in sqft
                        area_match = re.search(r"[\d,]+\.?\d*", val.replace(",", ""))
                        if area_match:
                            try:
                                area_val = float(area_match.group().replace(",", ""))
                                # If the unit is sqyd or yard, convert to sqft (1 sqyd = 9 sqft)
                                if "sqyd" in val.lower() or "yard" in val.lower() or "sq. yard" in val.lower():
                                    area_val *= 9
                                elif "sqm" in val.lower() or "sq. m" in val.lower():
                                    area_val *= 10.7639
                                record["area_sqft"] = area_val
                            except ValueError:
                                pass

                # Fallback: if no auction_date found, use sentinel
                if "auction_date" not in record:
                    record["auction_date"] = date(1970, 1, 1)

                # Build a usable property description if missing
                if not record.get("property_description"):
                    parts = [record.get("locality", ""), record.get("property_type", "")]
                    record["property_description"] = " - ".join(p for p in parts if p) or "DDA Auction Property"

                # Try to infer property_type from description if still missing
                if "property_type" not in record:
                    desc_lower = record["property_description"].lower()
                    if "residential" in desc_lower or "plot" in desc_lower or "flat" in desc_lower:
                        record["property_type"] = "plot"
                    elif "commercial" in desc_lower or "shop" in desc_lower or "booth" in desc_lower or "office" in desc_lower:
                        record["property_type"] = "commercial"
                    elif "industrial" in desc_lower:
                        record["property_type"] = "industrial"

                # Set full_address from locality + city if not already set
                if not record.get("full_address"):
                    locality = record.get("locality", "")
                    record["full_address"] = f"{locality}, Delhi".strip(", ").strip()

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
                rec.setdefault("city", "Delhi")
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
                        "property_type": stmt.excluded.property_type,
                        "area_sqft": stmt.excluded.area_sqft,
                        "locality": stmt.excluded.locality,
                    },
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert DDA auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
