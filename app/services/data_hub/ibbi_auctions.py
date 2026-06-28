"""IBBI auction scraper — Insolvency and Bankruptcy Board of India liquidation auction notices."""
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

_IBBI_LIQUIDATION_URL = "https://ibbi.gov.in/liquidation-auction-notices"
_IBBI_SEARCH_URL = "https://ibbi.gov.in/en/notices"


class IBBIAuctionScraper(BaseScraper):
    name = "ibbi_auctions"
    source = AuctionSource.ibbi

    async def _scrape(self) -> list[dict]:
        results = []
        urls = [_IBBI_LIQUIDATION_URL, _IBBI_SEARCH_URL]

        for url in urls:
            try:
                html = await self._fetch_url(url)
                parsed = self._parse_notices(html, url)
                results.extend(parsed)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", url, e)
            await asyncio.sleep(2)

        return results

    def _parse_notices(self, html: str, source_url: str) -> list[dict]:
        """Parse IBBI notice listings. These are mainly metadata/links —
        the actual auction details live on BaankNet, so we capture what we can."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # IBBI pages typically use tables or card-based layouts for notices
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue

                # Try to extract a link from the row
                link_tag = row.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else ""
                if link_url and not link_url.startswith("http"):
                    link_url = f"https://ibbi.gov.in{link_url}"

                record: dict[str, Any] = {
                    "source": AuctionSource.ibbi,
                    "bank_name": "IBBI",
                    "property_description": cells[0] if cells else "",
                    "city": "Delhi NCR",
                    "source_url": link_url or source_url,
                    "raw_data": {"headers": headers, "cells": cells, "detail_url": link_url},
                }

                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if not val:
                        continue

                    if "company" in h or "corporate" in h or "debtor" in h:
                        record["bank_name"] = f"IBBI - {val}"
                        record["property_description"] = val
                    elif "liquidator" in h:
                        record.setdefault("contact_person", val)
                    elif "asset" in h or "description" in h or "property" in h:
                        record["property_description"] = val
                        record["full_address"] = val
                    elif "date" in h or "notice" in h:
                        record["auction_date"] = self._parse_date(val)
                    elif "reserve" in h or "price" in h:
                        try:
                            record["reserve_price"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "emd" in h or "earnest" in h:
                        try:
                            record["emd_amount"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass

                # Fallback description from full row text
                if not record.get("full_address"):
                    row_text = " ".join(cells)
                    record["full_address"] = row_text

                if record.get("property_description"):
                    records.append(record)

        # Also try card-based layout (IBBI sometimes uses divs instead of tables)
        if not records:
            for card in soup.find_all("div", class_=re.compile(r"notice|card|auction", re.I)):
                text = card.get_text(separator=" ", strip=True)
                if not text or len(text) < 10:
                    continue
                link_tag = card.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else source_url

                record = {
                    "source": AuctionSource.ibbi,
                    "bank_name": "IBBI",
                    "property_description": text[:500],
                    "full_address": text[:500],
                    "city": "Delhi NCR",
                    "source_url": link_url,
                    "raw_data": {"text": text[:1000]},
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
