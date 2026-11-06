"""The (entity_type, slug, locale) keys of served content blocks, cached in process.

The public read answers most lookups with 404 (most entities have no block). Checking this set
first keeps those 404s off the DB: a crawler burst over thousands of slugs then costs one query
per refresh, not one pool connection per request. Writes call ``invalidate_served_keys``; other
processes see a change within ``SERVED_TTL_S``.
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import SERVED_STATUSES, ContentBlock

SERVED_TTL_S = 300.0

_cache: tuple[float, frozenset[tuple[str, str, str]]] | None = None
_lock = asyncio.Lock()


def invalidate_served_keys() -> None:
    global _cache
    _cache = None


def _fresh() -> frozenset[tuple[str, str, str]] | None:
    if _cache is not None and time.monotonic() - _cache[0] < SERVED_TTL_S:
        return _cache[1]
    return None


async def served_keys(db: AsyncSession) -> frozenset[tuple[str, str, str]]:
    """Every served key. One query per TTL; concurrent callers at expiry share it."""
    global _cache
    if (keys := _fresh()) is not None:
        return keys
    async with _lock:
        if (keys := _fresh()) is not None:
            return keys
        rows = (
            await db.execute(
                select(ContentBlock.entity_type, ContentBlock.slug, ContentBlock.locale).where(
                    ContentBlock.review_status.in_(SERVED_STATUSES)
                )
            )
        ).all()
        keys = frozenset((r[0], r[1], r[2]) for r in rows)
        _cache = (time.monotonic(), keys)
        return keys
