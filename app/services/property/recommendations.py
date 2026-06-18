"""Property recommendation logic."""

from __future__ import annotations

import json

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import get_cache_manager
from app.core.db_resilience import execute_with_transient_retry
from app.core.logging import get_logger
from app.models.enums import PG_FLATMATE_TYPES
from app.models.properties import Property, PropertyAmenity
from app.schemas.pagination import offset_payload, read_offset
from app.schemas.property import Property as PropertySchema

logger = get_logger(__name__)

_ANON_CACHE_TTL = 86400  # 1 day for anonymous recommendations


def _anon_cache_key(limit: int) -> str:
    return f"recs:anon:v1:l{limit}"


async def get_property_recommendations(
    db: AsyncSession,
    user_id: int | None,
    cursor_payload: dict,
    limit: int = 10,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """Get property recommendations for a user"""
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
        # Simple recommendation: get available properties
        # TODO: Implement proper recommendation algorithm based on user preferences
        query = (
            select(Property)
            .options(
                selectinload(Property.images),
                selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
            )
            .where(
                Property.is_available,
                or_(
                    Property.property_type.notin_(PG_FLATMATE_TYPES),
                    func.coalesce(
                        Property.listing_preferences["moderation_status"].as_string(),
                        "live",
                    )
                    == "live",
                ),
            )
            .offset(skip)
            .limit(limit + 1)
        )

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_recommendations_query",
        )
        properties = list(result.scalars().all())

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
