"""Haryana Gazette scraper — official gazette site + PDF extraction."""
import asyncio
import logging
import re
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import GazetteNotification
from app.models.enums import GazetteType
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import classify_gazette_relevance, extract_pdf_text

logger = logging.getLogger(__name__)

_GAZETTE_URL = "https://egazette.haryana.gov.in/"


class GazetteScraper(BaseScraper):
    name = "gazette"

    async def _scrape(self) -> list[dict]:
        results = []
        try:
            html = await self._fetch_url(_GAZETTE_URL)
            listings = self._parse_gazette_listing(html)
            for item in listings[:20]:  # process up to 20 recent items
                # Try to fetch PDF text if URL available
                if item.get("pdf_url"):
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            resp = await client.get(item["pdf_url"])
                            resp.raise_for_status()
                            item["pdf_text"] = extract_pdf_text(resp.content)
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.warning(
                            "Failed to fetch PDF %s: %s", item.get("pdf_url"), e
                        )
                # Classify relevance using title + pdf_text
                text_for_classify = f"{item.get('title', '')} {item.get('pdf_text', '')}"
                tags, score = classify_gazette_relevance(text_for_classify)
                item["relevance_tags"] = tags
                item["relevance_score"] = score
                if tags:  # only store relevant items
                    results.append(item)
                await asyncio.sleep(1)
        except Exception as e:
            logger.warning("Failed to scrape gazette: %s", e)
        return results

    def _parse_gazette_listing(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for row in soup.select("table tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            pdf_link = row.find("a", href=True)
            item: dict[str, Any] = {
                "title": cells[0] if cells else "Untitled",
                "department": cells[1] if len(cells) > 1 else None,
                "source_url": _GAZETTE_URL,
                "raw_data": {"cells": cells},
            }
            # Try to parse date from cells
            for c in cells:
                m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", c)
                if m:
                    try:
                        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        if y < 100:
                            y += 2000
                        item["notification_date"] = date(y, mo, d)
                    except ValueError:
                        pass
                    break
            if pdf_link:
                href = str(pdf_link["href"])
                if not href.startswith("http"):
                    href = _GAZETTE_URL.rstrip("/") + "/" + href.lstrip("/")
                item["pdf_url"] = href
                # Use PDF filename as notification_number
                item["notification_number"] = href.split("/")[-1].replace(".pdf", "")
            items.append(item)
        return items

    def _map_gazette_type(self, tags: list[str]) -> GazetteType | None:
        if not tags:
            return None
        mapping = {
            "land_acquisition": GazetteType.land_acquisition,
            "rate_revision": GazetteType.rate_revision,
            "policy": GazetteType.policy,
            "clu_change": GazetteType.clu_change,
        }
        return mapping.get(tags[0])

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        """
        Select-then-insert/update pattern to avoid partial unique index issues.

        GazetteNotification has no named unique constraint — the DB uses partial
        indexes (notification_number WHERE NOT NULL). We therefore:
        1. Try to find an existing row by (notification_number, notification_date)
           when both values are present.
        2. If found → update mutable fields in-place.
        3. If not found → insert a new row.
        """
        found = len(records)
        upserted = 0
        failed = 0

        for rec in records:
            try:
                tags = rec.get("relevance_tags", [])
                rec["notification_type"] = self._map_gazette_type(tags)

                notification_number = rec.get("notification_number")
                notification_date = rec.get("notification_date")

                existing = None

                # Attempt to locate an existing row
                if notification_number and notification_date:
                    result = await db.execute(
                        select(GazetteNotification).where(
                            GazetteNotification.notification_number == notification_number,
                            GazetteNotification.notification_date == notification_date,
                        )
                    )
                    existing = result.scalar_one_or_none()
                elif notification_number:
                    result = await db.execute(
                        select(GazetteNotification).where(
                            GazetteNotification.notification_number == notification_number,
                        )
                    )
                    existing = result.scalar_one_or_none()

                if existing is not None:
                    # Update mutable fields
                    existing.summary = rec.get("summary", existing.summary)
                    existing.pdf_text = rec.get("pdf_text", existing.pdf_text)
                    existing.relevance_tags = rec.get("relevance_tags", existing.relevance_tags)
                    existing.relevance_score = rec.get("relevance_score", existing.relevance_score)
                    existing.notification_type = rec.get(
                        "notification_type", existing.notification_type
                    )
                    existing.raw_data = rec.get("raw_data", existing.raw_data)
                else:
                    # Build a clean values dict from model columns only
                    allowed = {
                        k: v
                        for k, v in rec.items()
                        if hasattr(GazetteNotification, k)
                        and k not in ("id", "created_at", "updated_at")
                    }
                    db.add(GazetteNotification(**allowed))

                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert gazette item: %s", e)
                await db.rollback()
                failed += 1

        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
