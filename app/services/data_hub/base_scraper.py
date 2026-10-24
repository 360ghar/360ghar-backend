from __future__ import annotations

import copy
import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.database import get_bg_session_factory

logger = logging.getLogger(__name__)

#: The only keys a re-parse may clear, by model. A parse that cannot read a label
#: is not evidence the figure went away, so every other key keeps its stored value
#: when the new read is ``None`` — a transient portal relabelling would otherwise
#: erase a good figure a previous parse had read. ``stage`` is the exception
#: because ``derive_stage`` returns ``None`` on purpose: the filed completion date
#: has passed while the register still lists the project as live, so its stage is
#: unknown rather than assumed, and a stale stage would be a claim the filing no
#: longer supports.
_CLEARABLE_ON_REPARSE = frozenset({"stage"})


@dataclass
class ScrapeResult:
    """Structured result for scrapers that need source-level coverage reporting."""

    records: list[dict[str, Any]] = field(default_factory=list)
    source_documents: list[dict[str, Any]] = field(default_factory=list)
    source_coverage: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    successful_sources: int = 0

    @property
    def status(self) -> str:
        if self.successful_sources == 0:
            return "failed"
        if self.errors:
            return "partial"
        return "success"

    @property
    def run_metadata(self) -> dict[str, Any]:
        return {"source_coverage": self.source_coverage, "errors": self.errors}


def final_run_status(scrape_result: ScrapeResult | None, stats: dict[str, Any]) -> str:
    """Combine source coverage and record-write outcomes without hiding partial failures."""
    status = scrape_result.status if scrape_result is not None else "success"
    if not stats.get("failed", 0):
        return status
    if stats.get("found", 0) and not stats.get("upserted", 0):
        return "failed"
    return "failed" if status == "failed" else "partial"


def attach_source_checked_at(
    records: list[dict[str, Any]],
    source_documents: list[dict[str, Any]],
) -> None:
    """Attach each source document's check time to the records it produced."""
    checked_at_by_key = {
        str(source["source_key"]): source["checked_at"]
        for source in source_documents
        if source.get("source_key") is not None
        and isinstance(source.get("checked_at"), datetime)
    }
    for record in records:
        checked_at = checked_at_by_key.get(str(record.get("_source_key", "")))
        if checked_at is not None:
            record["_source_checked_at"] = checked_at


def successful_provenance_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in copy.deepcopy(record).items()
            if key not in {"_upsert_succeeded", "_source_checked_at"}
        }
        for record in records
        if record.get("_upsert_succeeded") is not False
    ]


class BaseScraper(ABC):
    """Abstract base for all data hub scrapers."""

    name: str = ""                      # e.g. "circle_rates"
    requires_playwright: bool = False

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        """Orchestrate: start_run → _scrape (no DB session) → open session → _upsert → finish_run.

        The network-heavy ``_scrape()`` call runs **without** holding a DB
        session so the background pool is not exhausted while waiting for
        external HTTP responses.
        """
        session_factory = get_bg_session_factory()

        # Phase 1: open a short-lived session just to record the run start
        async with session_factory() as db:
            run_id = await self._start_run(db, run_type, triggered_by)

        # Phase 2: scrape external sources (no DB session held)
        try:
            scrape_output = await self._scrape()
        except Exception as e:
            logger.error("Scraper %s scrape failed: %s", self.name, e, exc_info=True)
            async with session_factory() as db:
                await self._finish_run(
                    db,
                    run_id,
                    "failed",
                    {},
                    error="Scrape failed",
                    metadata={
                        "source_coverage": [],
                        "errors": [
                            {
                                "stage": "scrape",
                                "error_type": type(e).__name__,
                                "message": "Scrape failed",
                            }
                        ],
                    },
                )
            return {"status": "failed", "run_id": run_id, "error": "Scrape failed"}

        # Phase 3: open a session for upsert + finish
        if isinstance(scrape_output, ScrapeResult):
            scrape_result: ScrapeResult | None = scrape_output
            records = scrape_output.records
        else:
            scrape_result = None
            records = scrape_output
        if scrape_result is not None:
            attach_source_checked_at(records, scrape_result.source_documents)
        run_metadata: dict[str, Any] = (
            scrape_result.run_metadata
            if scrape_result is not None
            else {"source_coverage": [], "errors": []}
        )
        try:
            async with session_factory() as db:
                stats = await self._upsert(db, records)
                if scrape_result is not None:
                    try:
                        from app.services.data_hub.provenance import persist_scrape_provenance

                        provenance_errors = await persist_scrape_provenance(
                            db,
                            scraper_name=self.name,
                            run_id=run_id,
                            records=successful_provenance_records(records),
                            source_documents=scrape_result.source_documents,
                            run_succeeded=(
                                scrape_result.status == "success"
                                and not stats.get("failed", 0)
                            ),
                        )
                        if provenance_errors:
                            run_metadata["errors"].extend(provenance_errors)
                            stats["failed"] = stats.get("failed", 0) + len(provenance_errors)
                    except Exception as e:
                        logger.error(
                            "Scraper %s provenance persistence failed: %s",
                            self.name,
                            e,
                            exc_info=True,
                        )
                        run_metadata["errors"].append(
                            {
                                "stage": "provenance",
                                "error_type": type(e).__name__,
                                "message": "Provenance persistence failed",
                            }
                        )
                        stats["failed"] = stats.get("failed", 0) + 1
                run_status = final_run_status(scrape_result, stats)
                await self._finish_run(
                    db,
                    run_id,
                    run_status,
                    stats,
                    metadata=run_metadata if scrape_result is not None else None,
                )
            return {"status": run_status, "run_id": run_id, **stats}
        except Exception as e:
            logger.error("Scraper %s upsert failed: %s", self.name, e, exc_info=True)
            async with session_factory() as db:
                if scrape_result is not None:
                    run_metadata["errors"].append(
                        {
                            "stage": "upsert",
                            "error_type": type(e).__name__,
                            "message": "Entity upsert failed",
                        }
                    )
                await self._finish_run(
                    db,
                    run_id,
                    "failed",
                    {},
                    error="Entity upsert failed",
                    metadata=run_metadata if scrape_result is not None else None,
                )
            return {"status": "failed", "run_id": run_id, "error": "Entity upsert failed"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_url(self, url: str, **kwargs) -> str:
        """Fetch URL with tenacity retry (3 attempts, exponential 2s→4s→8s)."""
        from app.core.http import get_scraper_client

        client = get_scraper_client()
        response = await client.get(url, **kwargs)
        response.raise_for_status()
        return response.text

    @asynccontextmanager
    async def _playwright_browser(self):
        """Context manager yielding a headless Chromium browser with guaranteed cleanup."""
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            await browser.close()
            await pw.stop()

    async def _start_run(self, db: AsyncSession, run_type: str, triggered_by: int | None) -> int:
        """Insert a ScraperRun row and return its id."""
        from app.models.data_hub import ScraperRun
        from app.models.enums import ScraperStatus
        run = ScraperRun(
            scraper_name=self.name,
            run_type=run_type,
            status=ScraperStatus.running,
            triggered_by=triggered_by,
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        await db.commit()
        return run.id

    async def _finish_run(
        self, db: AsyncSession, run_id: int,
        status: str,
        stats: dict,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update ScraperRun row with final status and stats."""
        from sqlalchemy import select

        from app.models.data_hub import ScraperRun
        from app.models.enums import ScraperStatus
        result = await db.execute(select(ScraperRun).where(ScraperRun.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            logger.warning("_finish_run: ScraperRun id=%s not found — status not updated", run_id)
            return
        run.status = ScraperStatus(status)
        run.records_found = stats.get("found", 0)
        run.records_upserted = stats.get("upserted", 0)
        run.records_failed = stats.get("failed", 0)
        run.error_message = error
        if metadata is not None:
            run.run_metadata = metadata
        run.finished_at = datetime.now(UTC)
        await db.commit()

    @abstractmethod
    async def _scrape(self) -> list[dict] | ScrapeResult:
        """Fetch raw data. Return list of dicts."""
        ...

    @abstractmethod
    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        """Insert/update records into DB. Return stats dict with 'found', 'upserted', 'failed'."""
        ...

    async def _upsert_one(
        self,
        db: AsyncSession,
        model: Any,
        key_column: str,
        project_id: int,
        values: dict[str, Any],
        document_id: int | None,
        checked_at: datetime,
        *,
        touch: bool = False,
    ) -> None:
        """Upsert a 1:1 section row, keeping the previous values when absent.

        "Absent" means the new parse could not read the label, which is not the
        same as the value having gone away. On an update, a key whose new value
        is None is left out of the update set, so the stored value stands; only
        ``_CLEARABLE_ON_REPARSE`` may be cleared. The insert path still writes
        every key, because a new row has nothing to keep.

        A payload with no readable value at all is skipped rather than inserted,
        so a filing that states nothing about a section does not create an empty
        row that later reads as a section the authority filed and left blank. The
        key, the citing document and the touch timestamp are bookkeeping rather
        than filed values, so a payload carrying only those is empty for this
        purpose: Delhi files a cost for 120 of its 133 projects, and the other 13
        must not produce a cost row with a NULL total.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        payload = {key: value for key, value in values.items() if hasattr(model, key)}
        payload[key_column] = project_id
        payload["source_document_id"] = document_id
        if touch:
            payload["updated_at"] = checked_at
        bookkeeping = {key_column, "source_document_id", "updated_at"}
        if not any(
            value is not None for key, value in payload.items() if key not in bookkeeping
        ):
            return
        stmt = pg_insert(model).values(**payload)
        update_fields = {
            key: getattr(stmt.excluded, key)
            for key in payload
            if key != key_column
            and (payload[key] is not None or key in _CLEARABLE_ON_REPARSE)
        }
        await db.execute(
            stmt.on_conflict_do_update(index_elements=[key_column], set_=update_fields)
        )
