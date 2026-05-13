from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from app.config import settings
from app.core.logging import get_logger
from app.vector.sync import run_property_vector_sync

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_vector_sync_scheduler(app: FastAPI):
    """Start APScheduler job for property vector sync if enabled.

    Uses CRON if VECTOR_SYNC_CRON provided; else interval seconds.
    """
    global _scheduler
    if not settings.VECTOR_SYNC_ENABLED:
        logger.info("Vector sync scheduler disabled via settings")
        return

    if _scheduler and _scheduler.running:
        logger.info("Vector sync scheduler already running")
        return

    sched = AsyncIOScheduler()

    if settings.VECTOR_SYNC_CRON:
        trig = CronTrigger.from_crontab(settings.VECTOR_SYNC_CRON)
        logger.info("Scheduling vector sync with CRON", extra={"cron": settings.VECTOR_SYNC_CRON})
    else:
        seconds = int(settings.VECTOR_SYNC_INTERVAL_SECONDS)
        trig = IntervalTrigger(seconds=seconds)
        logger.info("Scheduling vector sync with interval", extra={"seconds": seconds})

    async def job_wrapper():
        try:
            stats = await run_property_vector_sync()
            logger.info("Vector sync pass completed", extra=stats)
        except Exception as e:  # noqa: BLE001
            logger.error("Vector sync job failed: %s", e)

    sched.add_job(job_wrapper, trig, id="property_vector_sync", replace_existing=True, max_instances=1)
    sched.start()
    _scheduler = sched
    logger.info("Vector sync scheduler started")


def shutdown_scheduler() -> None:
    """Shut down the vector sync scheduler. Called during app lifespan teardown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

