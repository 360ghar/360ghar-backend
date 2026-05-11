"""Shared helpers for the notifications package."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from app.core.auth import get_supabase_service_client
from app.core.logging import get_logger
from app.services.notification_config import (
    NOTIFICATION_TYPES,
    NotificationChannel,
    NotificationPriority,
)

logger = get_logger(__name__)

# Bounded thread pool for notification sync operations to avoid
# exhausting the default asyncio executor under burst load.
_NOTIFICATION_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="notif-",
)


def _supa():
    """Return the Supabase service client."""
    return get_supabase_service_client()


async def _run_sync(fn):
    """Run a sync function in the dedicated notification thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_NOTIFICATION_EXECUTOR, fn)


def _get_type_config(type_key: str | None) -> tuple[str | None, int | None, bool]:
    """Resolve priority label, TTL, and priority_high flag for a type key.

    Falls back to a safe default if the type is unknown.
    """
    if not type_key:
        return None, None, True
    cfg = NOTIFICATION_TYPES.get(type_key)
    if not cfg:
        return None, None, True
    ttl = cfg.default_ttl_seconds
    priority_high = cfg.priority in {NotificationPriority.HIGH, NotificationPriority.CRITICAL}
    return cfg.priority.value, ttl, priority_high


def _augment_data_with_meta(
    data: dict[str, Any] | None,
    *,
    type_key: str | None,
    channel: NotificationChannel,
    priority: str | None = None,
) -> dict[str, Any]:
    """Attach metadata about the notification into the data payload.

    Metadata is nested under a reserved ``_meta`` key to avoid clashing with
    domain-specific data fields.
    """
    base: dict[str, Any] = dict(data or {})
    meta = base.get("_meta") or {}
    meta.update(
        {
            "type_key": type_key,
            "channel": channel.value,
        }
    )
    if priority:
        meta["priority"] = priority
    base["_meta"] = meta
    return base


def shutdown_executor() -> None:
    """Shut down the notification thread pool. Called during app lifespan teardown."""
    _NOTIFICATION_EXECUTOR.shutdown(wait=False)
