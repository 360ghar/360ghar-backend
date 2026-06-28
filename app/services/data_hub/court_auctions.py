"""Court auction scraper — DRT Chandigarh and eCourts notices."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import CourtAuction
from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_DRT_CHANDIGARH_URL = "https://drtchandigarh.gov.in/auction-notices"
_ECOURTS_URL = "https://ecourts.gov.in/ecourts_home/static/auction-notices.php"

_SOURCES = [
    {"url": _DRT_CHANDIGARH_URL, "source": AuctionSource.drt, "court": "DRT Chandigarh"},
    {"url": _ECOURTS_URL, "source": AuctionSource.ecourts, "court": "eCourts"},
]


class CourtAuctionScraper(BaseScraper):
    name = "court_auctions"

    async def _scrape(self) -> list[dict]:
        results = []
        for source_cfg in _SOURCES:
            try:
                html = await self._fetch_url(source_cfg["url"])
                records = self._parse_court_html(html, source_cfg)
                results.extend(records)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", source_cfg["url"], e)
        return results

    def _parse_court_html(self, html: str, source_cfg: dict) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        records = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                rec = {
                    "source": source_cfg["source"],
                    "court_name": source_cfg["court"],
                    "case_number": cells[0] if cells else "UNKNOWN",
                    "source_url": source_cfg["url"],
                    "city": "Gurugram",
                    "is_active": True,
                    "raw_data": {"headers": headers, "cells": cells},
                }
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if "borrower" in h or "debtor" in h:
                        rec["borrower_name"] = val
                    elif "property" in h and "description" in h:
                        rec["property_description"] = val
                    elif "reserve" in h:
                        try:
                            rec["reserve_price"] = float(
                                val.replace(",", "").replace("\u20b9", "").strip()
                            )
                        except ValueError:
                            pass
                    elif "auction" in h and "date" in h:
                        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", val)
                        if m:
                            try:
                                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                                if y < 100:
                                    y += 2000
                                rec["auction_date"] = date(y, mo, d)
                            except ValueError:
                                pass
                records.append(rec)
        return records

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                rec.setdefault("auction_date", date(1970, 1, 1))  # sentinel for unknown date
                values = {
                    k: v
                    for k, v in rec.items()
                    if hasattr(CourtAuction, k) and k not in ("id", "created_at", "updated_at")
                }
                stmt = pg_insert(CourtAuction).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["case_number", "auction_date"],
                    set_={
                        "reserve_price": stmt.excluded.reserve_price,
                        "raw_data": stmt.excluded.raw_data,
                        "is_active": True,
                    },
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert court auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
