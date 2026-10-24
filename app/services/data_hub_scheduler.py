"""Consolidated APScheduler for all data hub scrapers.

Registers daily, weekly, and quarterly cron jobs on the shared
APScheduler instance from ``app.infrastructure.scheduler``.
"""

from __future__ import annotations

import asyncio

from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.config import settings
from app.core.logging import get_logger
from app.infrastructure.scheduler import get_scheduler

logger = get_logger(__name__)

_TZ = "Asia/Kolkata"

_DAILY_CRON = "0 2 * * *"
_WEEKLY_CRON = "0 2 * * 1"
_QUARTERLY_CRON = "0 2 1 4,10 *"

_SCRAPER_SEMAPHORE = asyncio.Semaphore(3)


async def _run_scraper_limited(scraper):
    """Run a single scraper under the concurrency semaphore."""
    async with _SCRAPER_SEMAPHORE:
        return await scraper.run()


async def _run_daily_scrapers() -> None:
    """Bank auctions, HSVP, DDA, MDA, YEIDA, aggregator, gazette, court auctions, neighbourhood scores, alert matching, market pulse."""
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
    if settings.HRERA_DATA_ENABLED:
        from app.services.data_hub.market_pulse import MarketPulseScraper

        # A snapshot is keyed (city, captured_on), so it has to run daily or the
        # history has gaps. Its 7-day windows also slide daily even though the
        # filing data behind them only refreshes weekly.
        scrapers.append(MarketPulseScraper())
    results = await asyncio.gather(*[_run_scraper_limited(s) for s in scrapers], return_exceptions=True)
    for scraper, result in zip(scrapers, results, strict=False):
        if isinstance(result, Exception):
            logger.error("Daily scraper %s failed: %s", scraper.name, result, exc_info=result)
        else:
            logger.info("Daily scraper %s done: %s", scraper.name, result)


async def _run_weekly_scrapers() -> None:
    """Bank rates, Tier 2 auction scrapers, and the HRERA/UP RERA filing jobs."""
    from app.services.data_hub.aggregator_misc import AggregatorMiscAuctionScraper
    from app.services.data_hub.baanknet_auctions import BaankNetAuctionScraper
    from app.services.data_hub.bank_rates import BankRateScraper
    from app.services.data_hub.bank_specific_auctions import BankSpecificAuctionScraper
    from app.services.data_hub.dfc_delhi_auctions import DFCDelhiAuctionScraper
    from app.services.data_hub.drt_auctions import DRTAuctionScraper
    from app.services.data_hub.hsvp_procure247_auctions import HSVPProcure247AuctionScraper
    from app.services.data_hub.ibbi_auctions import IBBIAuctionScraper
    scrapers = []
    if settings.HRERA_DATA_ENABLED:
        from app.services.data_hub.delhi_rera_projects import DelhiReraProjectScraper
        from app.services.data_hub.developer_dossier import DeveloperDossierScraper
        from app.services.data_hub.micro_market import MicroMarketScraper
        from app.services.data_hub.rera_complaints import ReraComplaintScraper
        from app.services.data_hub.rera_price_history import ReraPriceHistoryScraper
        from app.services.data_hub.rera_project_detail import ReraProjectDetailScraper
        from app.services.data_hub.uprera_projects import UpreraProjectScraper

        # ReraProjectScraper is deliberately absent: HRERA's project search is
        # CAPTCHA-gated, so it can never succeed and a weekly failing run would
        # only teach operators to ignore failures. Discovery runs through
        # rera_portal_scan, which an operator triggers with an explicit id range.
        # This job refreshes filings for projects whose portal id is already
        # stored, which is every project the scanner has found.
        #
        # Price history and the developer dossier read what the filing refresh
        # writes, so they belong in the same batch. They run in parallel with it,
        # so a value derived from this run's own filing lands next run; both are
        # weekly readings, so the one-run lag does not change their meaning.
        scrapers.extend(
            [
                ReraProjectDetailScraper(),
                ReraComplaintScraper(),
                ReraPriceHistoryScraper(),
                DeveloperDossierScraper(),
                # Micro-markets are derived from the sector and locality text the
                # filings name, so they are a reading of the register rather than
                # a source of their own. Same one-run lag as the two above.
                MicroMarketScraper(),
                # UP RERA is a different portal with a different contract: its
                # register is one server-rendered grid behind an ASP.NET postback,
                # with no CAPTCHA and no pagination, so unlike HRERA it can be
                # scraped headlessly.
                UpreraProjectScraper(),
                # Delhi RERA is the same shape of surface as UP RERA: one open,
                # server-rendered register plus one open filing page per project,
                # no CAPTCHA and no pagination, so httpx reads it without a
                # browser. It shares this flag with the other RERA sources rather
                # than getting its own: the flag is the off-switch for RERA
                # register data as a whole, and Delhi rows feed the same tables and
                # the same read endpoints as the Haryana and UP rows, so a switch
                # that left Delhi flowing would not be an off-switch.
                DelhiReraProjectScraper(),
            ]
        )
    from app.services.data_hub.watchlist_alerts import WatchlistAlertScraper

    scrapers.extend([
        BankRateScraper(),
        BaankNetAuctionScraper(),
        IBBIAuctionScraper(),
        DFCDelhiAuctionScraper(),
        DRTAuctionScraper(),
        HSVPProcure247AuctionScraper(),
        AggregatorMiscAuctionScraper(),
        BankSpecificAuctionScraper(),
        # Watchlist alerts read RERA filing data, so they belong in this batch.
        # They run in parallel with the filing refresh, which means a change made
        # by this run's own scrape is reported on the next one — the same one-run
        # lag AlertMatcherService already has. The scraper gates itself on
        # HRERA_DATA_ENABLED, so it is listed outside that flag's block.
        WatchlistAlertScraper(),
    ])
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
    """Register data hub cron jobs if DATA_HUB_ENABLED."""
    del app

    if not getattr(settings, "DATA_HUB_ENABLED", True):
        logger.info("Data hub scheduler disabled via DATA_HUB_ENABLED=False")
        return

    scheduler = get_scheduler()

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
    logger.info(
        "Data hub jobs registered",
        extra={
            "daily_cron": _DAILY_CRON,
            "weekly_cron": _WEEKLY_CRON,
            "quarterly_cron": _QUARTERLY_CRON,
            "timezone": _TZ,
        },
    )
