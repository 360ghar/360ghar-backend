import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.database import get_bg_session_factory

logger = logging.getLogger(__name__)


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
            records = await self._scrape()
        except Exception as e:
            logger.error("Scraper %s scrape failed: %s", self.name, e, exc_info=True)
            async with session_factory() as db:
                await self._finish_run(db, run_id, "failed", {}, error=str(e))
            return {"status": "failed", "run_id": run_id, "error": str(e)}

        # Phase 3: open a session for upsert + finish
        try:
            async with session_factory() as db:
                stats = await self._upsert(db, records)
                await self._finish_run(db, run_id, "success", stats)
            return {"status": "success", "run_id": run_id, **stats}
        except Exception as e:
            logger.error("Scraper %s upsert failed: %s", self.name, e, exc_info=True)
            async with session_factory() as db:
                await self._finish_run(db, run_id, "failed", {}, error=str(e))
            return {"status": "failed", "run_id": run_id, "error": str(e)}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_url(self, url: str, **kwargs) -> str:
        """Fetch URL with tenacity retry (3 attempts, exponential 2s→4s→8s)."""
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
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
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.flush()
        await db.commit()
        return run.id

    async def _finish_run(
        self, db: AsyncSession, run_id: int,
        status: str, stats: dict, error: str | None = None
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
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()

    @abstractmethod
    async def _scrape(self) -> list[dict]:
        """Fetch raw data. Return list of dicts."""
        ...

    @abstractmethod
    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        """Insert/update records into DB. Return stats dict with 'found', 'upserted', 'failed'."""
        ...
