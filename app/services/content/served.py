"""The (entity_type, slug, locale) keys of served content blocks, cached in process.

The public read answers most lookups with 404 (most entities have no block). Checking this set
first keeps those 404s off the DB: a crawler burst over thousands of slugs then costs one query
per refresh, not one pool connection per request. Every content write runs in this process
(production has one instance) and calls ``invalidate_served_keys``.
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceUnavailableException
from app.models.content import SERVED_STATUSES, ContentBlock

SERVED_TTL_S = 300.0
# After a failed refresh (for example a full pool), waiters fail fast for this long instead of
# each waiting through another pool timeout.
FAILED_REFRESH_HOLD_S = 5.0

_cache: tuple[float, frozenset[tuple[str, str, str]]] | None = None
_generation = 0
_failed_at: float | None = None
_lock = asyncio.Lock()


def invalidate_served_keys() -> None:
    global _cache, _generation
    _cache = None
    _generation += 1


def _fresh() -> frozenset[tuple[str, str, str]] | None:
    if _cache is not None and time.monotonic() - _cache[0] < SERVED_TTL_S:
        return _cache[1]
    return None


async def _load(db: AsyncSession) -> frozenset[tuple[str, str, str]]:
    rows = (
        await db.execute(
            select(ContentBlock.entity_type, ContentBlock.slug, ContentBlock.locale).where(
                ContentBlock.review_status.in_(SERVED_STATUSES)
            )
        )
    ).all()
    return frozenset((r[0], r[1], r[2]) for r in rows)


async def served_keys(db: AsyncSession) -> frozenset[tuple[str, str, str]]:
    """Every served key. One query per TTL; concurrent callers at expiry share it."""
    global _cache, _failed_at
    if (keys := _fresh()) is not None:
        return keys
    async with _lock:
        if (keys := _fresh()) is not None:
            return keys
        if _failed_at is not None and time.monotonic() - _failed_at < FAILED_REFRESH_HOLD_S:
            raise ServiceUnavailableException(
                detail="Content is temporarily unavailable. Please retry shortly.",
                headers={"Retry-After": "5"},
            )
        # A write that commits during the query invalidates its snapshot: query once more,
        # and never cache a snapshot older than the latest invalidation.
        for _ in range(2):
            generation = _generation
            try:
                keys = await _load(db)
            except Exception:
                _failed_at = time.monotonic()
                raise
            _failed_at = None
            if generation == _generation:
                _cache = (time.monotonic(), keys)
                break
        return keys
