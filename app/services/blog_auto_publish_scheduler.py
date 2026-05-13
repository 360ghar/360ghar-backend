from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.config import settings
from app.core.logging import get_logger
from app.services.blog_auto_publish import DailyPerplexityBlogPublisher

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_auto_blog_publish_scheduler(app: FastAPI) -> None:
    """Start the daily automated blog publisher if enabled."""
    del app

    global _scheduler
    if not settings.AUTO_BLOG_ENABLED:
        logger.info("Auto blog publish scheduler disabled via settings")
        return

    if _scheduler and _scheduler.running:
        logger.info("Auto blog publish scheduler already running")
        return

    timezone = settings.AUTO_BLOG_TIMEZONE or "Asia/Kolkata"
    scheduler = AsyncIOScheduler(timezone=timezone)
    publisher = DailyPerplexityBlogPublisher()
    trigger = CronTrigger.from_crontab(settings.AUTO_BLOG_CRON, timezone=timezone)

    async def _job_wrapper() -> None:
        try:
            stats = await publisher.publish_daily_posts()
            logger.info("Auto blog publish job completed", extra=stats)
        except Exception as exc:  # noqa: BLE001
            logger.error("Auto blog publish job failed: %s", exc, exc_info=True)

    scheduler.add_job(
        _job_wrapper,
        trigger,
        id="auto_blog_publish",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Auto blog publish scheduler started",
        extra={"cron": settings.AUTO_BLOG_CRON, "timezone": timezone},
    )


def start_auto_blog_scheduler(app: FastAPI) -> None:
    """Backward-compatible alias for the auto blog scheduler starter."""
    start_auto_blog_publish_scheduler(app)


def shutdown_scheduler() -> None:
    """Shut down the blog scheduler. Called during app lifespan teardown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
