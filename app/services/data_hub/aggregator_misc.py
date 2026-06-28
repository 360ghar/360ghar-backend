"""Aggregator miscellaneous auction scraper — 4 sub-sources:
1. eAuctionDekho.com (eauctiondekho.com)
2. FindAuction.in (findauction.in)
3. FindAuctionProperty.com (findauctionproperty.com)
4. AuctionBazaar.com (auctionbazaar.com)

Each sub-source is scraped independently with graceful failure."""
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

_SUB_SOURCES = [
    {
        "name": "eAuctionDekho",
        "url": "https://eauctiondekho.com/auctions",
        "source": AuctionSource.eauction_dekho,
        "bank_name": "eAuctionDekho",
    },
    {
        "name": "FindAuction",
        "url": "https://findauction.in/auctions",
        "source": AuctionSource.findauction,
        "bank_name": "FindAuction",
    },
    {
        "name": "FindAuctionProperty",
        "url": "https://findauctionproperty.com/auctions",
        "source": AuctionSource.findauction_prop,
        "bank_name": "FindAuctionProperty",
    },
    {
        "name": "AuctionBazaar",
        "url": "https://auctionbazaar.com/auctions",
        "source": AuctionSource.auction_bazaar,
        "bank_name": "AuctionBazaar",
    },
]


class AggregatorMiscAuctionScraper(BaseScraper):
    name = "aggregator_misc_auctions"

    async def _scrape(self) -> list[dict]:
        results = []

        for source_cfg in _SUB_SOURCES:
            try:
                html = await self._fetch_url(source_cfg["url"])
                parsed = self._parse_aggregator_html(html, source_cfg)
                results.extend(parsed)
            except Exception as e:
                logger.warning(
                    "Failed to scrape %s (%s): %s",
                    source_cfg["name"], source_cfg["url"], e,
                )
            await asyncio.sleep(2)

        return results

    def _parse_aggregator_html(self, html: str, source_cfg: dict) -> list[dict]:
        """Best-effort parse of aggregator auction listing pages.
        These sites vary in layout; we try table, card, and list patterns."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # --- Strategy 1: Table-based listings ---
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not headers:
                first_row = table.find("tr")
                if first_row:
                    headers = [td.get_text(strip=True).lower() for td in first_row.find_all("td")]

            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue

                link_tag = row.find("a", href=True)
                link_url = link_tag["href"] if link_tag else source_cfg["url"]

                record = {
                    "source": source_cfg["source"],
                    "bank_name": source_cfg["bank_name"],
                    "property_description": cells[0] if cells else "",
                    "source_url": link_url,
                    "raw_data": {"headers": headers, "cells": cells, "aggregator": source_cfg["name"]},
                }

                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if not val:
                        continue

                    if "bank" in h or "institution" in h:
                        record["bank_name"] = val
                    elif "property" in h and ("type" in h or "category" in h):
                        record["property_type"] = val
                    elif "address" in h or "location" in h or "city" in h or "area" in h:
                        record["full_address"] = val
                        record["city"] = self._detect_city(val) or "Gurugram"
                    elif "description" in h or "detail" in h:
                        record["property_description"] = val
                    elif "reserve" in h or "price" in h or "base" in h or "value" in h:
                        try:
                            record["reserve_price"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "emd" in h or "earnest" in h:
                        try:
                            record["emd_amount"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "date" in h and ("auction" in h or "bid" in h or "sale" in h):
                        record["auction_date"] = self._parse_date(val)

                # Fill defaults
                if not record.get("full_address"):
                    record["full_address"] = " ".join(cells)
                record.setdefault("city", self._detect_city(record.get("full_address", "")) or "Gurugram")

                if record.get("property_description"):
                    records.append(record)

        # --- Strategy 2: Card-based listings ---
        if not records:
            for card in soup.find_all(["div", "article", "li"], class_=re.compile(r"auction|listing|card|property|item", re.I)):
                text = card.get_text(separator=" ", strip=True)
                if not text or len(text) < 20:
                    continue
                link_tag = card.find("a", href=True)
                link_url = link_tag["href"] if link_tag else source_cfg["url"]

                record = {
                    "source": source_cfg["source"],
                    "bank_name": source_cfg["bank_name"],
                    "property_description": text[:500],
                    "full_address": text[:500],
                    "city": self._detect_city(text) or "Gurugram",
                    "source_url": link_url,
                    "raw_data": {"text": text[:1000], "aggregator": source_cfg["name"]},
                }
                # Try to extract price from card text
                price_match = re.search(r"[₹Rs\.]?\s*([\d,]+(?:\.\d+)?)\s*(?:Lakh|Crore|Cr|L)?", text, re.I)
                if price_match:
                    try:
                        amount_str = price_match.group(1).replace(",", "")
                        amount = float(amount_str)
                        # Handle Lakh/Crore multipliers
                        multiplier_match = re.search(r"(Lakh|Crore|Cr|L)\b", text[price_match.start():], re.I)
                        if multiplier_match:
                            mult = multiplier_match.group(1).lower()
                            if mult in ("crore", "cr"):
                                amount *= 10000000
                            elif mult in ("lakh", "l"):
                                amount *= 100000
                        record["reserve_price"] = amount
                    except ValueError:
                        pass

                records.append(record)

        return records

    @staticmethod
    def _detect_city(text: str) -> str:
        """Detect city from listing content."""
        text_lower = text.lower()
        city_keywords = {
            "Delhi": ["delhi", "new delhi", "narela", "jhilmil", "nangloi", "dwarka", "rohini", "saket"],
            "Gurugram": ["gurugram", "gurgaon", "sector"],
            "Noida": ["noida", "greater noida"],
            "Faridabad": ["faridabad"],
            "Ghaziabad": ["ghaziabad", "indirapuram", "vaishali"],
            "Chandigarh": ["chandigarh"],
            "Mumbai": ["mumbai", "bombay", "thane", "navi mumbai"],
            "Bangalore": ["bangalore", "bengaluru"],
            "Pune": ["pune"],
            "Hyderabad": ["hyderabad"],
            "Chennai": ["chennai"],
            "Kolkata": ["kolkata", "calcutta"],
        }
        for city, keywords in city_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return city
        return ""

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
