"""Zoning data scraper — TCP Haryana tables + supports CSV admin import."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import ColonyApproval, ZoningData
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_TCP_URL = "https://dtcp.haryana.gov.in/colonies.htm"
_GMDA_URL = "https://www.gmda.gov.in/gurgaon-master-plan"


class ZoningScraper(BaseScraper):
    name = "zoning"

    async def _scrape(self) -> ScrapeResult:
        result = ScrapeResult()
        sources = (
            (
                _TCP_URL,
                self._parse_tcp_html,
                "Town and Country Planning Department, Haryana",
                "Haryana licensed colony approvals",
                "registry_table",
            ),
            (
                _GMDA_URL,
                self._parse_zoning_html,
                "Gurugram Metropolitan Development Authority",
                "Gurugram master plan zoning table",
                "planning_table",
            ),
        )
        for source_url, parser, authority, title, document_type in sources:
            coverage = {
                "source_url": source_url,
                "pages_attempted": 1,
                "pages_checked": 0,
                "records_parsed": 0,
                "status": "failed",
            }
            try:
                html = await self._fetch_url(source_url)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", source_url, exc)
                result.errors.append(
                    {
                        "source_url": source_url,
                        "stage": "fetch",
                        "error_type": type(exc).__name__,
                        "message": "Source page fetch failed",
                    }
                )
                result.source_coverage.append(coverage)
                continue

            coverage["pages_checked"] = 1
            checked_at = datetime.now(UTC)
            content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
            source_key = f"{source_url}#{content_hash}"
            result.source_documents.append(
                {
                    "source_key": source_key,
                    "authority": authority,
                    "title": title,
                    "canonical_url": source_url,
                    "source_record_id": None,
                    "jurisdiction": "Gurugram, Haryana, India",
                    "document_type": document_type,
                    "language": "en",
                    "license_name": None,
                    "reuse_terms": None,
                    "terms_url": None,
                    "published_at": None,
                    "effective_from": None,
                    "effective_to": None,
                    "fetched_at": checked_at,
                    "checked_at": checked_at,
                    "content_sha256": content_hash,
                    "artifact_reference": None,
                }
            )
            try:
                if not BeautifulSoup(html, "html.parser").find("table"):
                    raise ValueError("Expected source table was not found")
                records = parser(html)
                if not records:
                    raise ValueError("Source table produced no zoning or colony records")
                for record in records:
                    record["_source_key"] = source_key
                    record["_locator_page"] = 1
                result.records.extend(records)
                coverage["records_parsed"] = len(records)
                coverage["status"] = "success"
                result.successful_sources += 1
                if source_url == _TCP_URL:
                    await asyncio.sleep(2)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", source_url, exc)
                result.errors.append(
                    {
                        "source_url": source_url,
                        "stage": "parse",
                        "error_type": type(exc).__name__,
                        "message": "Source page parsing failed",
                    }
                )
            result.source_coverage.append(coverage)
        return result

    def _parse_tcp_html(self, html: str) -> list[dict]:
        """Parse TCP colony approval table."""
        soup = BeautifulSoup(html, "html.parser")
        records = []
        for table_index, table in enumerate(soup.find_all("table"), start=1):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row_index, row in enumerate(table.find_all("tr")[1:], start=2):
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
                    rec["_locator_table"] = table_index
                    rec["_locator_row"] = row_index
                    records.append(rec)
        return records

    def _parse_zoning_html(self, html: str) -> list[dict]:
        """Parse master plan zoning data from GMDA."""
        soup = BeautifulSoup(html, "html.parser")
        records = []
        for table_index, table in enumerate(soup.find_all("table"), start=1):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            for row_index, row in enumerate(table.find_all("tr")[1:], start=2):
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
                    rec["_locator_table"] = table_index
                    rec["_locator_row"] = row_index
                    records.append(rec)
        return records

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            rec["_upsert_succeeded"] = False
            try:
                source_checked_at = rec.get("_source_checked_at")
                if not isinstance(source_checked_at, datetime):
                    failed += 1
                    continue
                table_marker = rec.get("_table", "zoning_data")
                if table_marker == "colony_approvals":
                    values = {
                        key: value
                        for key, value in rec.items()
                        if hasattr(ColonyApproval, key)
                        and key
                        not in (
                            "id",
                            "created_at",
                            "updated_at",
                            "last_checked_at",
                            "last_successful_run_id",
                        )
                    }
                    colony_name = values.get("colony_name")
                    licence_number = values.get("licence_number")
                    conditions = [ColonyApproval.colony_name == colony_name]
                    conditions.append(
                        ColonyApproval.licence_number == licence_number
                        if licence_number is not None
                        else ColonyApproval.licence_number.is_(None)
                    )
                    async with db.begin_nested():
                        existing = await db.execute(
                            select(ColonyApproval)
                            .where(*conditions)
                            .limit(1)
                            .with_for_update()
                        )
                        colony = existing.scalar_one_or_none()
                        if colony is None:
                            db.add(ColonyApproval(**values))
                        else:
                            if (
                                colony.last_checked_at is not None
                                and colony.last_checked_at > source_checked_at
                            ):
                                continue
                            for key, value in values.items():
                                setattr(colony, key, value)
                        await db.flush()
                else:
                    values = {
                        key: value
                        for key, value in rec.items()
                        if hasattr(ZoningData, key)
                        and key
                        not in (
                            "id",
                            "created_at",
                            "updated_at",
                            "last_checked_at",
                            "last_successful_run_id",
                        )
                    }
                    async with db.begin_nested():
                        stmt = pg_insert(ZoningData).values(**values)
                        update_fields = {
                            key: getattr(stmt.excluded, key)
                            for key in values
                            if key
                            not in (
                                "sector",
                                "land_use",
                                "last_checked_at",
                                "last_successful_run_id",
                            )
                        }
                        result = await db.execute(
                            stmt.on_conflict_do_update(
                                index_elements=["sector", "land_use"],
                                set_=update_fields,
                                where=or_(
                                    ZoningData.last_checked_at.is_(None),
                                    ZoningData.last_checked_at <= source_checked_at,
                                ),
                            )
                            .returning(ZoningData.id)
                        )
                        if result.scalar_one_or_none() is None:
                            continue
                upserted += 1
                rec["_upsert_succeeded"] = True
            except Exception as e:
                logger.warning("Failed to upsert zoning/colony record: %s", e)
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}
