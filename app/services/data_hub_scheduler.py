"""Consolidated APScheduler for all data hub scrapers."""
from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None

_TZ = "Asia/Kolkata"

# Cron expressions (all at 2:00 AM IST)
_DAILY_CRON = "0 2 * * *"
_WEEKLY_CRON = "0 2 * * 1"        # Monday
_QUARTERLY_CRON = "0 2 1 4,10 *"  # Apr 1 + Oct 1

# Limit concurrent scrapers to avoid saturating PgBouncer connections.
_SCRAPER_SEMAPHORE = asyncio.Semaphore(3)


async def _run_scraper_limited(scraper):
    """Run a single scraper under the concurrency semaphore."""
    async with _SCRAPER_SEMAPHORE:
        return await scraper.run()


async def _run_daily_scrapers() -> None:
    """Bank auctions, HSVP, DDA, MDA, YEIDA, aggregator, gazette, court auctions, neighbourhood scores, alert matching."""
    from app.services.data_hub.aggregator_eauctions import AggregatorEauctionsScraper
    from app.services.data_hub.alerts import AlertMatcherService
    from app.services.data_hub.bank_auctions import BankAuctionScraper
    from app.services.data_hub.court_auctions import CourtAuctionScraper
    from app.services.data_hub.dda_auctions import DdaAuctionScraper
    from app.services.data_hub.gazette import GazetteScraper
    from app.services.data_hub.hsvp_auctions import HsvpAuctionScraper
    from app.services.data_hub.mda_auctions import MdaAuctionScraper
    from app.services.data_hub.neighbourhood import NeighbourhoodScraper
    from app.services.data_hub.yeida_auctions import YeidaAuctionScraper

    scrapers = [
        BankAuctionScraper(),
        HsvpAuctionScraper(),
        DdaAuctionScraper(),
        MdaAuctionScraper(),
        YeidaAuctionScraper(),
        AggregatorEauctionsScraper(),
        GazetteScraper(),
        CourtAuctionScraper(),
        NeighbourhoodScraper(),
        AlertMatcherService(),
    ]
    results = await asyncio.gather(*[_run_scraper_limited(s) for s in scrapers], return_exceptions=True)
    for scraper, result in zip(scrapers, results, strict=False):
        if isinstance(result, Exception):
            logger.error("Daily scraper %s failed: %s", scraper.name, result, exc_info=result)
        else:
            logger.info("Daily scraper %s done: %s", scraper.name, result)


async def _run_weekly_scrapers() -> None:
    """RERA projects, bank rates, RERA complaints, Tier 2 auction scrapers, bank-specific scrapers."""
    from app.services.data_hub.aggregator_misc import AggregatorMiscAuctionScraper
    from app.services.data_hub.baanknet_auctions import BaankNetAuctionScraper
    from app.services.data_hub.bank_rates import BankRateScraper
    from app.services.data_hub.bank_specific_auctions import BankSpecificAuctionScraper
    from app.services.data_hub.dfc_delhi_auctions import DFCDelhiAuctionScraper
    from app.services.data_hub.drt_auctions import DRTAuctionScraper
    from app.services.data_hub.hsvp_procure247_auctions import HSVPProcure247AuctionScraper
    from app.services.data_hub.ibbi_auctions import IBBIAuctionScraper
    from app.services.data_hub.rera_complaints import ReraComplaintScraper
    from app.services.data_hub.rera_projects import ReraProjectScraper

    scrapers = [
        ReraProjectScraper(),
        BankRateScraper(),
        ReraComplaintScraper(),
        BaankNetAuctionScraper(),
        IBBIAuctionScraper(),
        DFCDelhiAuctionScraper(),
        DRTAuctionScraper(),
        HSVPProcure247AuctionScraper(),
        AggregatorMiscAuctionScraper(),
        BankSpecificAuctionScraper(),
    ]
    results = await asyncio.gather(*[_run_scraper_limited(s) for s in scrapers], return_exceptions=True)
    for scraper, result in zip(scrapers, results, strict=False):
        if isinstance(result, Exception):
            logger.error("Weekly scraper %s failed: %s", scraper.name, result, exc_info=result)
        else:
            logger.info("Weekly scraper %s done: %s", scraper.name, result)


async def _run_quarterly_scrapers() -> None:
    """Circle rates, zoning data."""
    from app.services.data_hub.circle_rates import CircleRateScraper
    from app.services.data_hub.zoning import ZoningScraper

    scrapers = [
        CircleRateScraper(),
        ZoningScraper(),
    ]
    results = await asyncio.gather(*[_run_scraper_limited(s) for s in scrapers], return_exceptions=True)
    for scraper, result in zip(scrapers, results, strict=False):
        if isinstance(result, Exception):
            logger.error("Quarterly scraper %s failed: %s", scraper.name, result, exc_info=result)
        else:
            logger.info("Quarterly scraper %s done: %s", scraper.name, result)


def start_data_hub_scheduler(app: FastAPI) -> None:
    """Start the consolidated data hub scheduler if DATA_HUB_ENABLED."""
    del app

    global _scheduler

    if not getattr(settings, "DATA_HUB_ENABLED", True):
        logger.info("Data hub scheduler disabled via DATA_HUB_ENABLED=False")
        return

    if _scheduler and _scheduler.running:
        logger.info("Data hub scheduler already running")
        return

    scheduler = AsyncIOScheduler(timezone=_TZ)

    def _make_wrapper(coro_func, name: str):
        async def _wrapper():
            try:
                await coro_func()
            except Exception as exc:  # noqa: BLE001
                logger.error("Data hub %s job failed: %s", name, exc, exc_info=True)
        return _wrapper

    scheduler.add_job(
        _make_wrapper(_run_daily_scrapers, "daily"),
        CronTrigger.from_crontab(_DAILY_CRON, timezone=_TZ),
        id="data_hub_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _make_wrapper(_run_weekly_scrapers, "weekly"),
        CronTrigger.from_crontab(_WEEKLY_CRON, timezone=_TZ),
        id="data_hub_weekly",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _make_wrapper(_run_quarterly_scrapers, "quarterly"),
        CronTrigger.from_crontab(_QUARTERLY_CRON, timezone=_TZ),
        id="data_hub_quarterly",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Data hub scheduler started",
        extra={
            "daily_cron": _DAILY_CRON,
            "weekly_cron": _WEEKLY_CRON,
            "quarterly_cron": _QUARTERLY_CRON,
            "timezone": _TZ,
        },
    )


def shutdown_scheduler() -> None:
    """Shut down the data hub scheduler. Called during app lifespan teardown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
