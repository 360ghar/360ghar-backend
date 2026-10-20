"""Notification scheduler.

The daily marketing push used the FCM topic channel, which is removed. No client
subscribes to topics, and a topic message skips the per-user consent gate. A
scheduled campaign must dispatch per user through the notification dispatcher.
ponytail: no scheduled job. Add a per-user gated job when a campaign needs one.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def start_notification_scheduler(app: FastAPI) -> None:
    """Log that no scheduled push job exists when the scheduler flag is set."""
    del app
    if settings.ENABLE_NOTIF_SCHEDULER:
        logger.warning("ENABLE_NOTIF_SCHEDULER has no effect: the topic push job was removed")
