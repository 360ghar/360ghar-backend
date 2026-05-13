"""Bank auction scraper — 3 sources: SARFAESI (SBI), IBAPI, MSTC."""
import asyncio
import logging
from datetime import date, datetime

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import BankAuction
from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import address_hash

logger = logging.getLogger(__name__)

# Known public auction pages (best-effort, gracefully returns [] on failure)
_SOURCES = [
    {
        "url": "https://www.sbi.co.in/web/personal-banking/loans/home-loans/property-auction",
        "source": AuctionSource.sarfaesi,
        "bank": "State Bank of India",
    },
    {
        "url": "https://ibapi.in/auction-list",
        "source": AuctionSource.ibapi,
        "bank": "IBAPI",
    },
    {
        "url": "https://mstcecommerce.com/auctionhome/ibapi/index.jsp",
        "source": AuctionSource.mstc,
        "bank": "MSTC",
    },
]


class BankAuctionScraper(BaseScraper):
    name = "bank_auctions"

    async def _scrape(self) -> list[dict]:
        results = []
        for source_cfg in _SOURCES:
            try:
                html = await self._fetch_url(source_cfg["url"])
                parsed = self._parse_auction_html(html, source_cfg)
                results.extend(parsed)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", source_cfg["url"], e)
        return results

    def _parse_auction_html(self, html: str, source_cfg: dict) -> list[dict]:
        """Best-effort parse of auction table rows."""
        soup = BeautifulSoup(html, "lxml")
        records = []
        # Look for common table patterns on auction sites
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:  # skip header
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                record = {
                    "source": source_cfg["source"],
                    "bank_name": source_cfg["bank"],
                    "property_description": cells[0] if cells else "",
                    "source_url": source_cfg["url"],
                    "raw_data": {"headers": headers, "cells": cells},
                }
                # Try to map common column names
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if "reserve" in h or "price" in h:
                        try:
                            record["reserve_price"] = float(
                                val.replace(",", "").replace("\u20b9", "").strip()
                            )
                        except ValueError:
                            pass
                    elif "emd" in h:
                        try:
                            record["emd_amount"] = float(
                                val.replace(",", "").replace("\u20b9", "").strip()
                            )
                        except ValueError:
                            pass
                    elif "date" in h and "auction" in h:
                        try:
                            record["auction_date"] = datetime.strptime(val, "%d/%m/%Y").date()
                        except ValueError:
                            pass
                    elif "address" in h or "property" in h:
                        record["full_address"] = val
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
                rec.setdefault("city", "Gurugram")
                rec.setdefault("is_active", True)
                rec.setdefault("auction_date", date(1970, 1, 1))  # sentinel for unknown date
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
                logger.warning("Failed to upsert bank auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
