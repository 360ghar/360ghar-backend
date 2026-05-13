from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.config import settings
from app.core.logging import get_logger
from app.services.notifications import send_to_topic

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_notification_scheduler(app: FastAPI):
    """Start APScheduler for push notifications if enabled in settings."""
    global _scheduler
    if not settings.ENABLE_NOTIF_SCHEDULER:
        logger.info("Notification scheduler disabled via settings")
        return
    if _scheduler and _scheduler.running:
        return

    tz = settings.NOTIF_SCHED_TZ or "Asia/Kolkata"
    sched = AsyncIOScheduler(timezone=tz)

    # Example: 9:00 AM daily marketing push (safe default message)
    async def _daily_marketing_job():
        try:
            await send_to_topic(
                topic="marketing",
                title="Good morning!",
                body="Check out new updates today.",
                data=None,
                deep_link=None,
                type_key="promotion_generic",
            )
            logger.info("Daily marketing push job executed")
        except Exception as e:
            logger.error("Daily marketing push job failed: %s", e, exc_info=True)

    sched.add_job(_daily_marketing_job, CronTrigger(hour=9, minute=0))
    sched.start()
    _scheduler = sched
    logger.info("Notification scheduler started", extra={"timezone": tz})


def shutdown_scheduler() -> None:
    """Shut down the notification scheduler. Called during app lifespan teardown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
