"""Bank auction scraper — 3 sources: SARFAESI (SBI), IBAPI, MSTC."""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuctionSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import (
    _parse_auction_with_fallback,
    _parse_currency,
    _parse_date,
    address_hash,
    upsert_bank_auction,
)

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
        """Parse auction HTML using multi-strategy approach with fallback."""
        base_url = source_cfg["url"]

        def strategy_table(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 1: Parse auction tables with header mapping."""
            records = []
            for table in soup.find_all("table"):
                headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
                for row in table.find_all("tr")[1:]:
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cells) < 2:
                        continue
                    record = {
                        "source": cfg["source"],
                        "bank_name": cfg["bank"],
                        "property_description": cells[0] if cells else "",
                        "source_url": cfg["url"],
                        "raw_data": {"headers": headers, "cells": cells},
                    }
                    for i, h in enumerate(headers):
                        if i >= len(cells):
                            break
                        val = cells[i]
                        h_lower = h.lower()
                        if "reserve" in h_lower or "price" in h_lower:
                            price = _parse_currency(val)
                            if price is not None:
                                record["reserve_price"] = price
                        elif "emd" in h_lower:
                            price = _parse_currency(val)
                            if price is not None:
                                record["emd_amount"] = price
                        elif "date" in h_lower and "auction" in h_lower:
                            parsed = _parse_date(val)
                            if parsed:
                                record["auction_date"] = parsed
                        elif "address" in h_lower or "property" in h_lower:
                            record["full_address"] = val
                    if record.get("property_description"):
                        records.append(record)
            return records

        def strategy_sbi_notice_links(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 2: SBI-specific - parse notice page/PDF links for detailed data."""
            records: list[dict] = []
            if "sbi.co.in" not in cfg["url"]:
                return records

            # SBI auction page often has links to individual property notices/PDFs
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                if not text or len(text) < 15:
                    continue
                href = link["href"]
                full_url = urljoin(base_url, href)

                # Look for property-like links
                text_lower = text.lower()
                if not any(kw in text_lower for kw in ["property", "auction", "e-auction", "sale", "lot", "flat", "plot", "shop", "office"]):
                    continue

                record = {
                    "source": cfg["source"],
                    "bank_name": cfg["bank"],
                    "property_description": text,
                    "source_url": full_url,
                    "raw_data": {"link_text": text, "link_href": href},
                }

                # Try to extract city from text
                cities = ["mumbai", "delhi", "gurugram", "bangalore", "chennai", "hyderabad", "pune", "kolkata", "ahmedabad"]
                for city in cities:
                    if city in text_lower:
                        record["city"] = city.title()
                        break

                # Parse dates, prices, area from link text
                date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text)
                if date_match:
                    parsed = _parse_date(date_match.group(1))
                    if parsed:
                        record["auction_date"] = parsed

                price_match = re.search(r"(?:reserve|price|base)[\s:]*[₹Rs]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
                if price_match:
                    record["reserve_price"] = _parse_currency(price_match.group(1))

                emd_match = re.search(r"emd[\s:]*[₹Rs]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
                if emd_match:
                    record["emd_amount"] = _parse_currency(emd_match.group(1))

                if record.get("property_description"):
                    records.append(record)
            return records

        def strategy_generic_links(soup: BeautifulSoup, cfg: dict) -> list[dict]:
            """Strategy 3: Generic link-based parsing for IBAPI/MSTC."""
            records = []
            keywords = ["auction", "property", "e-auction", "sale", "bid", "lot"]
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                if not text or len(text) < 10:
                    continue
                text_lower = text.lower()
                if not any(kw in text_lower for kw in keywords):
                    continue
                href = link["href"]
                full_url = urljoin(base_url, href)
                record = {
                    "source": cfg["source"],
                    "bank_name": cfg["bank"],
                    "property_description": text,
                    "source_url": full_url,
                    "raw_data": {"link_text": text, "link_href": href},
                }
                if record.get("property_description"):
                    records.append(record)
            return records

        return _parse_auction_with_fallback(
            html,
            source_cfg,
            [strategy_table, strategy_sbi_notice_links, strategy_generic_links],
        )

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                addr = rec.get("full_address") or rec.get("property_description", "")
                rec["normalized_address_hash"] = address_hash(addr)
                rec.setdefault("city", "Delhi NCR")
                await upsert_bank_auction(db, rec)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert bank auction: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
