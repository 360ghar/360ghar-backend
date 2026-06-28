"""Zoning data scraper — TCP Haryana tables + supports CSV admin import."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import ColonyApproval, ZoningData
from app.services.data_hub.base_scraper import BaseScraper
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_TCP_URL = "https://dtcp.haryana.gov.in/colonies.htm"
_GMDA_URL = "https://www.gmda.gov.in/gurgaon-master-plan"


class ZoningScraper(BaseScraper):
    name = "zoning"

    async def _scrape(self) -> list[dict]:
        results = []
        # Try TCP Haryana colony approvals page
        try:
            html = await self._fetch_url(_TCP_URL)
            records = self._parse_tcp_html(html)
            results.extend(records)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning("Failed to scrape TCP colonies: %s", e)
        # Try GMDA master plan page for zoning data
        try:
            html = await self._fetch_url(_GMDA_URL)
            records = self._parse_zoning_html(html)
            results.extend(records)
        except Exception as e:
            logger.warning("Failed to scrape GMDA zoning: %s", e)
        return results

    def _parse_tcp_html(self, html: str) -> list[dict]:
        """Parse TCP colony approval table."""
        soup = BeautifulSoup(html, "html.parser")
        records = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                rec: dict[str, Any] = {
                    "district": "Gurugram",
                    "source_url": _TCP_URL,
                    "raw_data": {"headers": headers, "cells": cells},
                    "_table": "colony_approvals",  # marker
                }
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i].strip()
                    if "colony" in h or "name" in h:
                        rec["colony_name"] = val
                    elif "licence" in h or "number" in h:
                        rec["licence_number"] = val
                    elif "status" in h:
                        rec["approval_status"] = val.lower()
                    elif "sector" in h:
                        rec["sector"] = val
                    elif "area" in h:
                        try:
                            rec["area_acres"] = float(val.replace(",", "").replace("acres", "").strip())
                        except ValueError:
                            pass
                if rec.get("colony_name"):
                    records.append(rec)
        return records

    def _parse_zoning_html(self, html: str) -> list[dict]:
        """Parse master plan zoning data from GMDA."""
        soup = BeautifulSoup(html, "html.parser")
        records = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 2:
                    continue
                rec: dict[str, Any] = {
                    "source_url": _GMDA_URL,
                    "raw_data": {"headers": headers, "cells": cells},
                    "_table": "zoning_data",  # marker
                }
                for i, h in enumerate(headers):
                    if i >= len(cells):
                        break
                    val = cells[i].strip()
                    if "sector" in h:
                        rec["sector"] = val
                    elif "land use" in h or "zone" in h:
                        rec["land_use"] = val.lower()
                    elif "far" in h:
                        try:
                            rec["far_limit"] = float(val)
                        except ValueError:
                            pass
                    elif "height" in h:
                        try:
                            rec["max_height_m"] = float(val.replace("m", "").strip())
                        except ValueError:
                            pass
                if rec.get("sector") and rec.get("land_use"):
                    rec["slug"] = generate_slug(rec["sector"], rec["land_use"])
                    records.append(rec)
        return records

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            try:
                table_marker = rec.pop("_table", "zoning_data")
                if table_marker == "colony_approvals":
                    from sqlalchemy import select as sa_select
                    values = {k: v for k, v in rec.items()
                              if hasattr(ColonyApproval, k) and k not in ("id", "created_at", "updated_at")}
                    colony_name = values.get("colony_name")
                    licence_number = values.get("licence_number")
                    existing = await db.execute(
                        sa_select(ColonyApproval.id).where(
                            ColonyApproval.colony_name == colony_name,
                            ColonyApproval.licence_number == licence_number,
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none() is None:
                        db.add(ColonyApproval(**values))
                        await db.flush()
                else:
                    values = {k: v for k, v in rec.items()
                              if hasattr(ZoningData, k) and k not in ("id", "created_at", "updated_at")}
                    stmt = pg_insert(ZoningData).values(**values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["sector", "land_use"],
                        set_={
                            "far_limit": stmt.excluded.far_limit,
                            "max_height_m": stmt.excluded.max_height_m,
                            "raw_data": stmt.excluded.raw_data,
                        }
                    )
                    await db.execute(stmt)
                upserted += 1
            except Exception as e:
                logger.warning("Failed to upsert zoning/colony record: %s", e)
                await db.rollback()
                failed += 1
        await db.commit()
        return {"found": found, "upserted": upserted, "failed": failed}
