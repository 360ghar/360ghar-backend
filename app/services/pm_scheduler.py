"""Daily property management job: overdue charges, late fees and lease expiry.

Registers on the shared APScheduler (``app.infrastructure.scheduler``). A
transaction-scoped advisory lock keeps one run at a time when several API
instances run the scheduler.
"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from sqlalchemy import text

from app.core.database import get_bg_session_factory
from app.core.logging import get_logger
from app.infrastructure.scheduler import get_scheduler
from app.services.pm.lifecycle import run_lifecycle
from app.services.pm.rent_rules import business_today

logger = get_logger(__name__)

JOB_ID = "pm_daily_lifecycle"
LOCK_KEY = "pm_daily_lifecycle"
# 00:30 in the scheduler timezone, after the day has started.
TRIGGER_HOUR = 0
TRIGGER_MINUTE = 30


async def run_pm_daily_lifecycle() -> dict:
    """Run the daily steps once. Returns counts, or ``{"skipped": True}`` if another run holds the lock."""
    factory = get_bg_session_factory()
    async with factory() as db:
        got_lock = (
            await db.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": LOCK_KEY}
            )
        ).scalar()
        if not got_lock:
            logger.info("PM daily lifecycle skipped: another run holds the lock")
            return {"skipped": True}
        stats = await run_lifecycle(db, today=business_today())
        await db.commit()
    logger.info("PM daily lifecycle completed", extra=stats)
    return stats


def start_pm_scheduler(app: FastAPI) -> None:
    """Register the daily PM job on the shared scheduler."""
    del app
    scheduler = get_scheduler()

    async def job_wrapper() -> None:
        try:
            await run_pm_daily_lifecycle()
        except Exception as exc:  # noqa: BLE001 - a failed run must not stop the scheduler
            logger.error("PM daily lifecycle failed: %s", exc, exc_info=True)

    scheduler.add_job(
        job_wrapper,
        CronTrigger(hour=TRIGGER_HOUR, minute=TRIGGER_MINUTE),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
    )
    logger.info("PM daily lifecycle job registered")
