"""Bank-specific auction scraper — top 3 PSU banks:
1. SBI (sbi.co.in) — State Bank of India
2. PNB (pnbindia.in) — Punjab National Bank
3. BOB (bankofbaroda.in) — Bank of Baroda

Each bank has a different URL structure for their auction page.
Graceful failure if a bank site restructures."""
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

_BANK_SOURCES = [
    {
        "name": "SBI",
        "source": AuctionSource.sbi,
        "bank_name": "State Bank of India",
        "urls": [
            "https://www.sbi.co.in/web/personal-banking/loans/home-loans/property-auction",
            "https://www.sbi.co.in/web/personal-banking/loans/mortgage-loans/property-auction",
        ],
    },
    {
        "name": "PNB",
        "source": AuctionSource.pnb,
        "bank_name": "Punjab National Bank",
        "urls": [
            "https://www.pnbindia.in/auction-of-immovable-properties.html",
            "https://www.pnbindia.in/e-auction.html",
        ],
    },
    {
        "name": "BOB",
        "source": AuctionSource.bob,
        "bank_name": "Bank of Baroda",
        "urls": [
            "https://www.bankofbaroda.in/personal-banking/loans/property-auction",
            "https://www.bankofbaroda.in/e-auction",
        ],
    },
]


class BankSpecificAuctionScraper(BaseScraper):
    name = "bank_specific_auctions"

    async def _scrape(self) -> list[dict]:
        results = []

        for bank_cfg in _BANK_SOURCES:
            for url in bank_cfg["urls"]:
                try:
                    html = await self._fetch_url(url)
                    parsed = self._parse_bank_page(html, bank_cfg, url)
                    results.extend(parsed)
                except Exception as e:
                    logger.warning(
                        "Failed to scrape %s (%s): %s",
                        bank_cfg["name"], url, e,
                    )
                await asyncio.sleep(2)

        return results

    def _parse_bank_page(self, html: str, bank_cfg: dict, source_url: str) -> list[dict]:
        """Best-effort parse of bank-specific auction pages.
        Each bank structures their page differently, so we try multiple patterns."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # --- Strategy 1: Table-based (most common for bank auction pages) ---
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
                link_url = link_tag["href"] if link_tag else source_url

                record: dict[str, Any] = {
                    "source": bank_cfg["source"],
                    "bank_name": bank_cfg["bank_name"],
                    "property_description": cells[0] if cells else "",
                    "source_url": link_url,
                    "raw_data": {"headers": headers, "cells": cells, "bank": bank_cfg["name"]},
                }

                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if not val:
                        continue

                    if "property" in h and "type" in h:
                        record["property_type"] = val
                    elif ("address" in h or "location" in h or "area" in h) and "type" not in h:
                        record["full_address"] = val
                        record["city"] = self._detect_city(val) or "Gurugram"
                    elif "description" in h or "detail" in h or "particular" in h:
                        record["property_description"] = val
                        record["full_address"] = val
                    elif "reserve" in h or "base" in h or "price" in h:
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
                    elif "area" in h or "size" in h or "sq" in h:
                        area_sqft = self._parse_area(val)
                        if area_sqft:
                            record["area_sqft"] = area_sqft
                    elif "contact" in h or "person" in h:
                        record["contact_person"] = val
                    elif "branch" in h:
                        record["locality"] = val

                # Fill defaults
                if not record.get("full_address"):
                    record["full_address"] = " ".join(cells)
                record.setdefault("city", self._detect_city(record.get("full_address", "")) or "Gurugram")

                if record.get("property_description"):
                    records.append(record)

        # --- Strategy 2: List/card-based (some banks use divs instead of tables) ---
        if not records:
            for item in soup.find_all(["div", "li", "article"], class_=re.compile(r"auction|property|listing|card|notice", re.I)):
                text = item.get_text(separator=" ", strip=True)
                if not text or len(text) < 20:
                    continue
                link_tag = item.find("a", href=True)
                link_url = link_tag["href"] if link_tag else source_url

                record = {
                    "source": bank_cfg["source"],
                    "bank_name": bank_cfg["bank_name"],
                    "property_description": text[:500],
                    "full_address": text[:500],
                    "city": self._detect_city(text) or "Gurugram",
                    "source_url": link_url,
                    "raw_data": {"text": text[:1000], "bank": bank_cfg["name"]},
                }
                records.append(record)

        # --- Strategy 3: PDF links (some banks link to PDF notices) ---
        for link in soup.find_all("a", href=re.compile(r"\.pdf", re.I)):
            pdf_url = str(link["href"])
            if not pdf_url.startswith("http"):
                # Resolve relative URL
                base = source_url.rsplit("/", 1)[0]
                pdf_url = f"{base}/{pdf_url.lstrip('/')}"

            link_text = link.get_text(strip=True) or "Auction Notice PDF"
            record = {
                    "source": bank_cfg["source"],
                    "bank_name": bank_cfg["bank_name"],
                    "property_description": link_text,
                    "full_address": link_text,
                    "city": "Gurugram",
                    "source_url": pdf_url,
                    "raw_data": {"pdf_url": pdf_url, "bank": bank_cfg["name"]},
                }
            records.append(record)

        return records

    @staticmethod
    def _detect_city(text: str) -> str:
        """Detect city from listing content."""
        text_lower = text.lower()
        city_keywords = {
            "Delhi": ["delhi", "new delhi", "narela", "jhilmil", "nangloi", "dwarka", "rohini", "saket", "karol bagh", "lajpat nagar"],
            "Gurugram": ["gurugram", "gurgaon", "sector"],
            "Noida": ["noida", "greater noida"],
            "Faridabad": ["faridabad"],
            "Ghaziabad": ["ghaziabad", "indirapuram", "vaishali"],
            "Mumbai": ["mumbai", "bombay", "thane", "navi mumbai"],
            "Bangalore": ["bangalore", "bengaluru"],
            "Pune": ["pune"],
            "Hyderabad": ["hyderabad"],
            "Chennai": ["chennai"],
            "Kolkata": ["kolkata", "calcutta"],
            "Ahmedabad": ["ahmedabad"],
            "Jaipur": ["jaipur"],
            "Lucknow": ["lucknow"],
            "Chandigarh": ["chandigarh", "mohali"],
        }
        for city, keywords in city_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return city
        return ""

    @staticmethod
    def _parse_area(val: str) -> float | None:
        """Extract area in sqft from text."""
        m = re.search(r"([\d,.]+)\s*(?:sq\s*ft|sft|sqft)", val, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
        m = re.search(r"([\d,.]+)\s*(?:sq\s*m|sqm)", val, re.I)
        if m:
            try:
                return round(float(m.group(1).replace(",", "")) * 10.764, 2)
            except ValueError:
                pass
        m = re.search(r"([\d,.]+)\s*(?:sq\s*yd|sqyd|sq\.?\s*yards?)", val, re.I)
        if m:
            try:
                return round(float(m.group(1).replace(",", "")) * 9, 2)
            except ValueError:
                pass
        return None

    @staticmethod
    def _parse_date(val: str) -> date:
        """Attempt multiple date formats."""
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y", "%b %d, %Y"):
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
