"""Property recommendation logic."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import DateTime, Integer, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.config import settings
from app.core.cache import get_cache_manager
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.core.logging import get_logger
from app.models.enums import PG_FLATMATE_TYPES
from app.models.properties import Property, PropertyAmenity
from app.models.users import User, UserSwipe
from app.schemas.pagination import keyset_payload
from app.schemas.property import Property as PropertySchema
from app.services.flatmates.compatibility import (
    score_viewer_owner_compatibility,
    snapshot_user_for_compat,
    user_has_lifestyle_profile,
)
from app.services.property.crud import attach_owner_agents
from app.services.property.keyset import cursor_kinds, json_key, keyset_after, read_cursor_key

_OWNER_COMPAT_LOAD_ONLY = (
    User.id,
    User.flatmates_sleep_schedule,
    User.flatmates_cleanliness,
    User.flatmates_food_habits,
    User.flatmates_smoking,
    User.flatmates_drinking,
    User.flatmates_guests_policy,
    User.flatmates_work_style,
)

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

    first_page = not cursor_payload
    if user_id is None and first_page:
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
                    cached_next = None
                else:
                    raw_items = cached_data.get("items", [])
                    has_more = bool(cached_data.get("has_more", False))
                    cached_next = cached_data.get("next")
                # Entries written before the keyset cursor have no "next". Skip them when
                # another page exists, so the cursor is never lost.
                if not has_more or cached_next is not None:
                    items = [PropertySchema.model_validate(p) for p in raw_items]
                    if has_more:
                        items = items[:limit]
                    return items, (cached_next if has_more else None), None
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
                pref_city, pref_locality, pref_type = await _user_preference_signals(db, user_id)
            except Exception as exc:
                # A failure here must not break the endpoint — log and fall
                # through to the popularity ordering.
                logger.debug("Preference-signal lookup failed for user %s: %s", user_id, exc)

        base_filters = [Property.is_available, availability_filter]
        # Snapshot before execute_with_transient_retry — a retry detaches ORM
        # instances and would break later current_user.id / lifestyle access.
        current_user = await db.get(User, user_id) if user_id else None
        score_compatibility = user_has_lifestyle_profile(current_user)
        viewer_for_compat = snapshot_user_for_compat(current_user) if score_compatibility else None
        viewer_id = viewer_for_compat.id if viewer_for_compat is not None else None
        query_options = [
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        ]
        if score_compatibility:
            query_options.append(selectinload(Property.owner).load_only(*_OWNER_COMPAT_LOAD_ONLY))
        query = select(Property).options(*query_options).where(*base_filters).limit(limit + 1)

        # Sort keys, then id. The preference score is always the first key, so the cursor
        # has the same shape for every viewer and every like (it is 0 without a signal).
        # A CASE scores a city match 4, a locality match 2 and a type match 1.
        pref_score: ColumnElement[int] = cast(literal(0), Integer)
        if pref_city:
            pref_score = pref_score + case((Property.city == pref_city, 4), else_=0)
        if pref_locality:
            pref_score = pref_score + case((Property.locality == pref_locality, 2), else_=0)
        if pref_type:
            pref_score = pref_score + case((Property.property_type == pref_type, 1), else_=0)
        rank_keys: list[tuple[Any, Any, bool]] = [(pref_score, Integer(), True)]
        rank_keys.extend(
            [
                (Property.like_count, Integer(), True),
                (Property.view_count, Integer(), True),
                (Property.created_at, DateTime(timezone=True), True),
            ]
        )
        for index, (rank_expr, _sql_type, _desc) in enumerate(rank_keys):
            query = query.add_columns(rank_expr.label(f"sk{index}"))
        cursor_key = read_cursor_key(cursor_payload, cursor_kinds(rank_keys))
        if cursor_key is not None:
            cursor_values, cursor_id = cursor_key
            query = query.where(keyset_after(rank_keys, True, cursor_values, cursor_id))
        query = query.order_by(*[expr.desc() for expr, _t, _d in rank_keys], Property.id.desc())

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_recommendations_query",
        )
        rows = result.all()
        properties = [row[0] for row in rows]
        key_values = [
            [json_key(row._mapping[f"sk{i}"]) for i in range(len(rank_keys))] for row in rows
        ]

        logger.info("Found %s recommended properties for user %s", len(properties), user_id)

        has_more = len(properties) > limit
        if has_more:
            properties = properties[:limit]
            key_values = key_values[:limit]
        next_payload: dict | None = (
            keyset_payload(key_values[-1], properties[-1].id) if has_more and properties else None
        )

        schemas = []
        for prop in properties:
            schema = PropertySchema.model_validate(prop)
            if score_compatibility and viewer_for_compat is not None:
                try:
                    owner = prop.owner
                except Exception:
                    owner = None
                schema.compatibility_score = score_viewer_owner_compatibility(
                    viewer_for_compat,
                    owner_id=prop.owner_id,
                    owner=owner,
                    viewer_id=viewer_id,
                )
            schemas.append(schema)

        # The owner-contact fallback needs the agent on every row, cache entries included.
        await attach_owner_agents(db, schemas)

        # Cache anonymous first-page results
        if user_id is None and first_page:
            try:
                cache = get_cache_manager()
                cache_obj = {
                    "items": [s.cache_payload() for s in schemas],
                    "has_more": next_payload is not None,
                    "next": next_payload,
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
