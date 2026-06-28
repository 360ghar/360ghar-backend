"""HSVP Procure247 auction scraper — Haryana Shehri Vikas Pradhikaran e-auction
via hsvp.procure247.com (JS-rendered site)."""
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

_HSVP_PROCURE247_URL = "https://hsvp.procure247.com"
_HSVP_AUCTION_PATH = "/auction/list"
_HSVP_TENDER_PATH = "/tender/list"


class HSVPProcure247AuctionScraper(BaseScraper):
    name = "hsvp_procure247_auctions"
    source = AuctionSource.hsvp_procure247
    requires_playwright = True

    async def _scrape(self) -> list[dict]:
        results = []
        paths = [_HSVP_AUCTION_PATH, _HSVP_TENDER_PATH]

        async with self._playwright_browser() as browser:
            for path in paths:
                url = f"{_HSVP_PROCURE247_URL}{path}"
                try:
                    page = await browser.new_page()
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=60000)
                        # Wait for the auction/tender data to load
                        await page.wait_for_selector("table, .auction-card, .tender-card, .list-item", timeout=10000)
                        content = await page.content()
                        parsed = self._parse_listing(content, url)
                        results.extend(parsed)
                    except Exception as e:
                        logger.warning("Playwright failed for %s: %s", url, e)
                    finally:
                        await page.close()
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning("Error processing %s: %s", url, e)

            # Also try the homepage for featured/latest auctions
            try:
                page = await browser.new_page()
                try:
                    await page.goto(_HSVP_PROCURE247_URL, wait_until="networkidle", timeout=60000)
                    content = await page.content()
                    parsed = self._parse_homepage(content)
                    results.extend(parsed)
                except Exception as e:
                    logger.warning("Playwright failed for homepage %s: %s", _HSVP_PROCURE247_URL, e)
                finally:
                    await page.close()
            except Exception as e:
                logger.warning("Error processing homepage: %s", e)

        return results

    def _parse_listing(self, html: str, source_url: str) -> list[dict]:
        """Parse HSVP auction/tender listing page (table or card layout)."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # Parse tables
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
                link_url = str(link_tag["href"]) if link_tag else ""
                if link_url and not link_url.startswith("http"):
                    link_url = f"{_HSVP_PROCURE247_URL}{link_url.lstrip('/')}"

                record: dict[str, Any] = {
                    "source": AuctionSource.hsvp_procure247,
                    "bank_name": "HSVP",
                    "property_description": cells[0] if cells else "",
                    "city": "Gurugram",
                    "source_url": link_url or source_url,
                    "raw_data": {"headers": headers, "cells": cells, "detail_url": link_url},
                }

                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i]
                    if not val:
                        continue

                    if "sector" in h or "plot" in h or "property" in h or "site" in h:
                        record["property_description"] = val
                        record["full_address"] = f"Gurugram — {val}" if "gurugram" not in val.lower() and "gurgaon" not in val.lower() else val
                    elif "type" in h:
                        record["property_type"] = self._classify_type(val)
                    elif "area" in h or "size" in h or "sq" in h:
                        area_sqft = self._parse_area(val)
                        if area_sqft:
                            record["area_sqft"] = area_sqft
                    elif "reserve" in h or "price" in h or "base" in h or "bid" in h:
                        try:
                            record["reserve_price"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "emd" in h or "earnest" in h:
                        try:
                            record["emd_amount"] = float(re.sub(r"[,₹\s]", "", val))
                        except ValueError:
                            pass
                    elif "date" in h and ("auction" in h or "bid" in h or "start" in h or "end" in h):
                        record["auction_date"] = self._parse_date(val)
                    elif "address" in h or "location" in h:
                        record["full_address"] = val

                # Default full_address
                if not record.get("full_address"):
                    record["full_address"] = record.get("property_description", "")

                if record.get("property_description"):
                    records.append(record)

        # Fallback: try card-based layout
        if not records:
            for card in soup.find_all(["div", "li"], class_=re.compile(r"auction|tender|card|listing", re.I)):
                text = card.get_text(separator=" ", strip=True)
                if not text or len(text) < 15:
                    continue
                link_tag = card.find("a", href=True)
                link_url = str(link_tag["href"]) if link_tag else source_url

                record = {
                    "source": AuctionSource.hsvp_procure247,
                    "bank_name": "HSVP",
                    "property_description": text[:500],
                    "full_address": text[:500],
                    "city": "Gurugram",
                    "source_url": link_url,
                    "raw_data": {"text": text[:1000]},
                }
                records.append(record)

        return records

    def _parse_homepage(self, html: str) -> list[dict]:
        """Parse HSVP homepage for featured or latest auction listings."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # Look for any links/sections mentioning auctions or tenders
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            if not re.search(r"auction|tender|e-auction", text, re.I):
                continue
            href = str(link["href"])
            if href and not href.startswith("http"):
                href = f"{_HSVP_PROCURE247_URL}/{href.lstrip('/')}"

            record = {
                "source": AuctionSource.hsvp_procure247,
                "bank_name": "HSVP",
                "property_description": text,
                "full_address": text,
                "city": "Gurugram",
                "source_url": href,
                "raw_data": {"text": text, "homepage_link": True},
            }
            records.append(record)

        return records

    @staticmethod
    def _classify_type(text: str) -> str:
        """Classify property type from text."""
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["residential", "flat", "apartment", "house"]):
            return "residential"
        elif any(kw in text_lower for kw in ["commercial", "shop", "office", "booth", "sco"]):
            return "commercial"
        elif any(kw in text_lower for kw in ["industrial", "factory"]):
            return "industrial"
        elif any(kw in text_lower for kw in ["plot", "site"]):
            return "plot"
        return "plot"  # HSVP default

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
        # Marla/Kanal (Haryana common) → 1 kanal = 5445 sqft, 1 marla = 272.25 sqft
        m = re.search(r"([\d,.]+)\s*kanal", val, re.I)
        if m:
            try:
                return round(float(m.group(1).replace(",", "")) * 5445, 2)
            except ValueError:
                pass
        m = re.search(r"([\d,.]+)\s*marla", val, re.I)
        if m:
            try:
                return round(float(m.group(1).replace(",", "")) * 272.25, 2)
            except ValueError:
                pass
        return None

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
