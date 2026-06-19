"""Daily automated blog publisher scheduler.

Registers a single cron job on the shared APScheduler instance
from ``app.infrastructure.scheduler``.
"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.config import settings
from app.core.database import AsyncSessionLocalBG
from app.core.logging import get_logger
from app.infrastructure.scheduler import get_scheduler
from app.services.blog import publish_scheduled_posts
from app.services.blog_auto_publish import DailyPerplexityBlogPublisher

logger = get_logger(__name__)


def start_auto_blog_publish_scheduler(app: FastAPI) -> None:
    """Start the daily automated blog publisher if enabled."""
    del app

    if not settings.AUTO_BLOG_ENABLED:
        logger.info("Auto blog publish scheduler disabled via settings")
        return

    scheduler = get_scheduler()
    publisher = DailyPerplexityBlogPublisher()
    trigger = CronTrigger.from_crontab(
        settings.AUTO_BLOG_CRON,
        timezone=settings.AUTO_BLOG_TIMEZONE or "Asia/Kolkata",
    )

    async def _job_wrapper() -> None:
        try:
            # Publish any scheduled posts whose scheduled_at has passed.
            try:
                async with AsyncSessionLocalBG() as session:
                    async with session.begin():
                        published_count = await publish_scheduled_posts(session)
                        if published_count:
                            logger.info(
                                "Auto-published scheduled blog posts",
                                extra={"count": published_count},
                            )
            except Exception as sched_exc:  # noqa: BLE001
                logger.error("Scheduled blog publish step failed: %s", sched_exc, exc_info=True)

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
    logger.info(
        "Auto blog publish job registered",
        extra={"cron": settings.AUTO_BLOG_CRON, "timezone": settings.AUTO_BLOG_TIMEZONE},
    )


def start_auto_blog_scheduler(app: FastAPI) -> None:
    """Backward-compatible alias for the auto blog scheduler starter."""
    start_auto_blog_publish_scheduler(app)
