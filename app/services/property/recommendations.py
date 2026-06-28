"""Property recommendation logic."""

from __future__ import annotations

import json

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.cache import get_cache_manager
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.core.logging import get_logger
from app.models.enums import PG_FLATMATE_TYPES
from app.models.properties import Property, PropertyAmenity
from app.models.users import UserSwipe
from app.schemas.pagination import offset_payload, read_offset
from app.schemas.property import Property as PropertySchema

logger = get_logger(__name__)

_ANON_CACHE_TTL = 86400  # 1 day for anonymous recommendations


def _anon_cache_key(limit: int) -> str:
    return f"recs:anon:v1:l{limit}"


async def _user_preference_signals(
    db: AsyncSession, user_id: int
) -> tuple[str | None, str | None, str | None]:
    """Return the most-recent liked property's ``(city, locality, property_type)``
    to use as a cheap personalization signal. ``None`` if the user has no
    likes yet, in which case we fall back to global popularity.
    """
    stmt = (
        select(Property.city, Property.locality, Property.property_type)
        .join(UserSwipe, UserSwipe.property_id == Property.id)
        .where(UserSwipe.user_id == user_id, UserSwipe.is_liked.is_(True))
        .order_by(UserSwipe.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        return None, None, None
    return row[0], row[1], row[2]


async def get_property_recommendations(
    db: AsyncSession,
    user_id: int | None,
    cursor_payload: dict,
    limit: int = 10,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """Get property recommendations for a user.

    For anonymous callers the result is a global popularity feed (cached
    for ``_ANON_CACHE_TTL``). For logged-in callers we add a cheap
    personalization signal: properties matching the user's most-recent
    liked property's city/locality/property_type bubble to the top via a
    CASE-based rank, with the global popularity order as a tiebreaker.
    This is NOT ML — it just stops the feed from being identical for every
    user. A real recommendation model is a larger project.
    """
    logger.info("Getting property recommendations for user %s, limit: %s", user_id, limit)

    skip = read_offset(cursor_payload)
    if user_id is None and skip == 0:
        try:
            cache = get_cache_manager()
            cached = await cache.get(_anon_cache_key(limit))
            if cached is not None:
                logger.info("Serving anonymous recommendations from cache (limit=%s)", limit)
                cached_data = json.loads(cached)
                if isinstance(cached_data, list):
                    # backward-compat: old cache format was a plain list
                    raw_items = cached_data
                    has_more = False
                else:
                    raw_items = cached_data.get("items", [])
                    has_more = bool(cached_data.get("has_more", False))
                items = [PropertySchema.model_validate(p) for p in raw_items]
                if has_more:
                    items = items[:limit]
                nxt = offset_payload(limit) if has_more else None
                return items, nxt, None
        except Exception:
            logger.debug("Cache read failed for anonymous recommendations; falling back to DB")

    try:
        # Bound the read so a stalled DB backend fails fast.
        await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)

        availability_filter = or_(
            Property.property_type.notin_(PG_FLATMATE_TYPES),
            func.coalesce(
                Property.listing_preferences["moderation_status"].as_string(),
                "live",
            )
            == "live",
        )

        # For logged-in users, look up their most-recent liked property's
        # (city, locality, property_type) to use as a cheap ranking signal.
        # If they have no likes yet, this returns Nones and we fall back to
        # pure global popularity — same as the anonymous path.
        pref_city: str | None = None
        pref_locality: str | None = None
        pref_type: str | None = None
        if user_id is not None:
            try:
                pref_city, pref_locality, pref_type = await _user_preference_signals(
                    db, user_id
                )
            except Exception as exc:
                # A failure here must not break the endpoint — log and fall
                # through to the popularity ordering.
                logger.debug("Preference-signal lookup failed for user %s: %s", user_id, exc)

        base_filters = [Property.is_available, availability_filter]
        query = (
            select(Property)
            .options(
                selectinload(Property.images),
                selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
            )
            .where(*base_filters)
            .offset(skip)
            .limit(limit + 1)
        )

        if pref_city or pref_locality or pref_type:
            # Build an ordered CASE: city match scores 4, locality 2, type 1,
            # no match 0. The score is the primary sort; popularity is the
            # tiebreaker; recency is the final tiebreaker. ``coalesce`` lets
            # us treat absent user signals as "0 contribution" without
            # per-condition null handling.
            pref_score = (
                func.coalesce(case((Property.city == pref_city, 4), else_=0), 0)
                + func.coalesce(case((Property.locality == pref_locality, 2), else_=0), 0)
                + func.coalesce(case((Property.property_type == pref_type, 1), else_=0), 0)
            ).label("pref_score")
            query = query.add_columns(pref_score).order_by(
                pref_score.desc(),
                Property.like_count.desc(),
                Property.view_count.desc(),
                Property.created_at.desc(),
            )
        else:
            query = query.order_by(
                Property.like_count.desc(),
                Property.view_count.desc(),
                Property.created_at.desc(),
            )

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_recommendations_query",
        )
        rows = result.all()
        properties = [row[0] for row in rows]

        logger.info("Found %s recommended properties for user %s", len(properties), user_id)

        has_more = len(properties) > limit
        if has_more:
            properties = properties[:limit]
        next_payload: dict | None = offset_payload(skip + limit) if has_more else None

        schemas = [PropertySchema.model_validate(prop) for prop in properties]

        # Cache anonymous first-page results
        if user_id is None and skip == 0:
            try:
                cache = get_cache_manager()
                cache_obj = {
                    "items": [s.model_dump(mode="json") for s in schemas],
                    "has_more": next_payload is not None,
                }
                serialized = json.dumps(cache_obj)
                await cache.set(_anon_cache_key(limit), serialized, ttl=_ANON_CACHE_TTL)
            except Exception:
                logger.debug("Cache write failed for anonymous recommendations")

        count_total: int | None = None
        return schemas, next_payload, count_total
    except Exception as e:
        logger.error("Failed to get recommendations for user %s: %s", user_id, e, exc_info=True)
        raise
