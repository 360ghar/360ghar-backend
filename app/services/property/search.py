"""Unified property search with comprehensive filtering and geospatial optimization."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    and_,
    bindparam,
    cast,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.cache import PropertyCacheManager
from app.core.db_resilience import execute_with_transient_retry
from app.core.logging import get_logger
from app.models.enums import PG_FLATMATE_TYPES, BookingStatus
from app.models.properties import Amenity, Property, PropertyAmenity, PropertyImage
from app.schemas.pagination import offset_payload, read_offset
from app.schemas.property import Property as PropertySchema
from app.schemas.property import SortBy, UnifiedPropertyFilter
from app.vector.embedding_client import embed_query

_vector_metadata = MetaData()
_property_embeddings_table: Table | None = None

# Default weights for hybrid relevance scoring
VECTOR_WEIGHT = 0.6
TEXT_WEIGHT = 0.4

logger = get_logger(__name__)


def _get_property_embeddings_table() -> Table:
    """Lazily build the property_embeddings Table on first use.

    Deferring the ``pgvector`` import (and the numpy it pulls in) out of module
    import time keeps both off the startup RAM footprint; they only load when a
    semantic search is actually performed.
    """
    global _property_embeddings_table
    if _property_embeddings_table is None:
        from pgvector.sqlalchemy import Vector

        _property_embeddings_table = Table(
            "property_embeddings",
            _vector_metadata,
            Column("property_id", Integer, primary_key=True),
            Column("embedding", Vector(768)),
            schema="public",
        )
    return _property_embeddings_table


def __getattr__(name: str):  # PEP 562 module-level lazy attribute
    if name == "property_embeddings_table":
        return _get_property_embeddings_table()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals().keys(), "property_embeddings_table"})


def _utc_day_start(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def _next_month_start(value: datetime) -> datetime:
    month = value.month + 1
    year = value.year
    if month == 13:
        month = 1
        year += 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _normalize_move_in_filter(move_in: str | None) -> str | None:
    if move_in is None:
        return None
    value = move_in.strip().lower().replace("-", "_")
    if value in {"", "all", "any", "anytime", "flexible", "just_exploring"}:
        return None
    if value in {"immediate", "immediately", "now"}:
        return "immediate"
    if value in {"this_month", "within_1_month", "within_a_month"}:
        return "this_month"
    if value == "next_month":
        return "next_month"
    if value in {"within_2_weeks", "two_weeks"}:
        return "within_2_weeks"
    return None


def _move_in_window(
    move_in: str | None,
    *,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime] | None:
    normalized = _normalize_move_in_filter(move_in)
    if normalized is None:
        return None

    today = _utc_day_start(now or datetime.now(timezone.utc))
    if normalized == "immediate":
        return None, today + timedelta(days=8)
    if normalized == "within_2_weeks":
        return None, today + timedelta(days=15)
    if normalized == "this_month":
        return None, _next_month_start(today)
    if normalized == "next_month":
        start = _next_month_start(today)
        return start, _next_month_start(start)
    return None


def _available_from_minimum(available_from: str | None) -> datetime | None:
    if available_from is None or not available_from.strip():
        return None
    try:
        return _utc_day_start(datetime.fromisoformat(available_from.strip()))
    except ValueError:
        return None


async def get_unified_properties_optimized(
    db: AsyncSession,
    filters: UnifiedPropertyFilter,
    user_id: int | None,
    cursor_payload: dict,
    limit: int,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """Unified property search with comprehensive filtering and geospatial optimization."""
    skip = read_offset(cursor_payload)
    logger.info(
        "Searching properties for user %s, offset %s, limit %s, filters: %s",
        user_id,
        skip,
        limit,
        filters,
        extra={
            "user_id": user_id,
            "offset": skip,
            "limit": limit,
            "property_type": [t.value if hasattr(t, "value") else t for t in filters.property_type]
            if filters.property_type
            else None,
            "purpose": filters.purpose.value if filters.purpose else None,
            "city": filters.city,
            "locality": filters.locality,
            "price_min": filters.price_min,
            "price_max": filters.price_max,
            "bedrooms_min": filters.bedrooms_min,
            "bedrooms_max": filters.bedrooms_max,
            "search_query": filters.search_query,
            "radius_km": filters.radius_km,
            "semantic_search": getattr(filters, "semantic_search", False),
            "sort_by": filters.sort_by.value if filters.sort_by else None,
        },
    )

    try:
        cache_filters = filters.model_dump(exclude_none=True, mode="json")
        cache_user_id = user_id or 0
        # Only cache unauthenticated first-page results (offset == 0)
        should_cache = user_id is None and skip == 0
        if should_cache:
            cached = await PropertyCacheManager.get_cached_properties(
                cache_filters, cache_user_id, 1, limit
            )
            if cached:
                try:
                    cached_items = [
                        PropertySchema.model_validate(item) for item in cached.get("items", [])
                    ]
                    # Return as 3-tuple: (items, next_payload, total)
                    cached_total = cached.get("total")
                    cached_has_more = bool(cached.get("has_more", False))
                    next_p = offset_payload(limit) if cached_has_more else None
                    return cached_items[:limit], next_p, cached_total
                except Exception as cache_exc:  # noqa: BLE001
                    logger.warning("Ignoring invalid property search cache: %s", cache_exc)

        # Base query with eager loading
        query = select(Property).options(
            selectinload(Property.images).load_only(
                PropertyImage.id,
                PropertyImage.property_id,
                PropertyImage.image_url,
                PropertyImage.caption,
                PropertyImage.image_category,
                PropertyImage.display_order,
                PropertyImage.is_main_image,
            ),
            selectinload(Property.property_amenities)
            .load_only(
                PropertyAmenity.id,
                PropertyAmenity.property_id,
                PropertyAmenity.amenity_id,
            )
            .selectinload(PropertyAmenity.amenity)
            .load_only(
                Amenity.id,
                Amenity.title,
                Amenity.icon,
                Amenity.category,
            ),
        )
        count_query = select(func.count(Property.id))

        # Build base conditions
        conditions: list[Any] = []
        text_filter_applied = False
        has_additional_columns = False
        semantic_enabled = bool(getattr(filters, "semantic_search", False) and filters.search_query)
        semantic_embedding = None
        vector_distance_expr = None
        combined_relevance_expr = None
        text_rank_expr = None

        # Always filter by availability unless explicitly requested
        if not filters.include_unavailable:
            conditions.append(Property.is_available)
            conditions.append(
                or_(
                    Property.property_type.notin_(PG_FLATMATE_TYPES),
                    func.coalesce(
                        Property.listing_preferences["moderation_status"].as_string(),
                        "live",
                    )
                    == "live",
                )
            )

        # Location-based search
        user_location = None
        distance = None
        if filters.latitude is not None and filters.longitude is not None and filters.radius_km:
            logger.debug(
                "Adding location filter: %s, %s, radius: %skm",
                filters.latitude,
                filters.longitude,
                filters.radius_km,
            )

            # Create a point from the user's location, ensuring SRID is set
            user_location = func.ST_SetSRID(
                func.ST_MakePoint(filters.longitude, filters.latitude), 4326
            )

            # Use ST_DWithin for efficient, index-based distance filtering.
            # ST_DWithin takes distance in meters.
            radius_m = filters.radius_km * 1000
            conditions.append(func.ST_DWithin(Property.location, user_location, radius_m))

            # Calculate distance for ordering and display, converting from meters to km.
            distance = func.ST_Distance(Property.location, user_location) / 1000
            query = query.add_columns(distance.label("distance_km"))
            has_additional_columns = True

        # Text search using PostgreSQL full-text search with GIN index.
        # Uses the pre-computed __ts_vector__ column (with weighted A/B/C ranking)
        # instead of dynamically building to_tsvector at query time, so the GIN
        # index is used and search_keywords are included.
        search_query_obj = None
        search_vector = None
        if filters.search_query:
            logger.debug("Adding full-text search filter: %s", filters.search_query)

            search_query_obj = func.plainto_tsquery("english", filters.search_query)
            search_vector = Property.__ts_vector__
            # Only hard-filter by text match when semantic search is not requested
            if not semantic_enabled:
                conditions.append(search_vector.op("@@")(search_query_obj))
                text_filter_applied = True
            text_rank_expr = func.ts_rank(search_vector, search_query_obj)

        # Property IDs filter
        if filters.property_ids:
            logger.debug("Adding property IDs filter: %s", filters.property_ids)
            conditions.append(Property.id.in_(filters.property_ids))

        # Property type filter - handle list of property types
        if filters.property_type:
            logger.debug("Adding property type filter: %s", filters.property_type)
            if isinstance(filters.property_type, list) and len(filters.property_type) > 0:
                conditions.append(Property.property_type.in_(filters.property_type))
            elif not isinstance(filters.property_type, list):
                conditions.append(Property.property_type == filters.property_type)

        # Purpose filter
        if filters.purpose:
            logger.debug("Adding purpose filter: %s", filters.purpose)
            conditions.append(Property.purpose == filters.purpose)

        # Price range filters
        if filters.price_min is not None:
            logger.debug("Adding min price filter: %s", filters.price_min)
            conditions.append(Property.base_price >= filters.price_min)
        if filters.price_max is not None:
            logger.debug("Adding max price filter: %s", filters.price_max)
            conditions.append(Property.base_price <= filters.price_max)

        # Bedroom filters
        if filters.bedrooms_min is not None:
            logger.debug("Adding min bedrooms filter: %s", filters.bedrooms_min)
            conditions.append(Property.bedrooms >= filters.bedrooms_min)
        if filters.bedrooms_max is not None:
            logger.debug("Adding max bedrooms filter: %s", filters.bedrooms_max)
            conditions.append(Property.bedrooms <= filters.bedrooms_max)

        # Bathroom filters
        if filters.bathrooms_min is not None:
            logger.debug("Adding min bathrooms filter: %s", filters.bathrooms_min)
            conditions.append(Property.bathrooms >= filters.bathrooms_min)
        if filters.bathrooms_max is not None:
            logger.debug("Adding max bathrooms filter: %s", filters.bathrooms_max)
            conditions.append(Property.bathrooms <= filters.bathrooms_max)

        # Area filters
        if filters.area_min is not None:
            logger.debug("Adding min area filter: %s", filters.area_min)
            conditions.append(Property.area_sqft >= filters.area_min)
        if filters.area_max is not None:
            logger.debug("Adding max area filter: %s", filters.area_max)
            conditions.append(Property.area_sqft <= filters.area_max)

        # Location filters — normalize via city alias map, then use filtered LIKE
        # so properties like "New Delhi" still match a search for "Delhi",
        # while "Gurugram" does NOT match a search for "Delhi".
        if filters.city:
            from app.utils.geo import normalize_city

            normalized_city = normalize_city(filters.city)
            logger.debug("Adding city filter: %s (normalized from: %s)", normalized_city, filters.city)
            conditions.append(func.lower(Property.city).like(f"%{normalized_city.lower()}%"))
        if filters.locality:
            logger.debug("Adding locality filter: %s", filters.locality)
            conditions.append(Property.locality.ilike(f"%{filters.locality}%"))
        if filters.pincode:
            logger.debug("Adding pincode filter: %s", filters.pincode)
            conditions.append(Property.pincode == filters.pincode)

        # Additional filters
        if filters.parking_spaces_min is not None:
            logger.debug("Adding min parking spaces filter: %s", filters.parking_spaces_min)
            conditions.append(Property.parking_spaces >= filters.parking_spaces_min)

        if filters.floor_number_min is not None:
            logger.debug("Adding min floor number filter: %s", filters.floor_number_min)
            conditions.append(Property.floor_number >= filters.floor_number_min)
        if filters.floor_number_max is not None:
            logger.debug("Adding max floor number filter: %s", filters.floor_number_max)
            conditions.append(Property.floor_number <= filters.floor_number_max)

        if filters.age_max is not None:
            logger.debug("Adding max age filter: %s", filters.age_max)
            conditions.append(Property.age_of_property <= filters.age_max)

        # Amenities filter
        if filters.amenities:
            logger.debug("Adding amenities filter: %s", filters.amenities)
            # Join with PropertyAmenity and Amenity tables

            # Convert amenity names to IDs if needed
            amenity_ids = []
            amenity_names = []

            for amenity in filters.amenities:
                if isinstance(amenity, int) or (isinstance(amenity, str) and amenity.isdigit()):
                    amenity_ids.append(int(amenity))
                else:
                    amenity_names.append(amenity)

            # Get amenity IDs from names if any — case-insensitive matching
            if amenity_names:
                amenity_result = await execute_with_transient_retry(
                    db,
                    lambda: db.execute(
                        select(Amenity.id).where(
                            func.lower(Amenity.title).in_([n.lower() for n in amenity_names])
                        )
                    ),
                    operation_name="property_search_amenity_lookup",
                )
                amenity_ids.extend([row[0] for row in amenity_result.fetchall()])

            if amenity_ids:
                # Subquery to find properties with all required amenities
                amenity_subquery = (
                    select(PropertyAmenity.property_id)
                    .where(PropertyAmenity.amenity_id.in_(amenity_ids))
                    .group_by(PropertyAmenity.property_id)
                    .having(func.count(PropertyAmenity.amenity_id) >= len(amenity_ids))
                )
                conditions.append(Property.id.in_(amenity_subquery))

        # Listing preference filters for PG / flatmate use cases
        listing_preferences_json = cast(Property.listing_preferences, JSONB)
        if filters.gender_preference is not None:
            logger.debug(
                "Adding gender preference filter: %s",
                filters.gender_preference,
            )
            conditions.append(
                listing_preferences_json["gender_preference"].astext
                == filters.gender_preference.value
            )

        if filters.sharing_type is not None:
            logger.debug("Adding sharing type filter: %s", filters.sharing_type)
            conditions.append(
                listing_preferences_json["sharing_type"].astext == filters.sharing_type.value
            )

        available_from_min = _available_from_minimum(filters.available_from)
        if available_from_min is not None:
            logger.debug("Adding available-from lower-bound filter: %s", available_from_min)
            conditions.append(Property.available_from.is_not(None))
            conditions.append(Property.available_from >= available_from_min)

        move_in_window = _move_in_window(filters.move_in)
        if move_in_window is not None:
            start, end = move_in_window
            logger.debug("Adding move-in timeline filter: %s to %s", start, end)
            conditions.append(Property.available_from.is_not(None))
            if start is not None:
                conditions.append(Property.available_from >= start)
            conditions.append(Property.available_from < end)

        # Features filter - support both object and string-array JSON shapes.
        if filters.features:
            logger.debug("Adding features filter: %s", filters.features)
            for feature in filters.features:
                conditions.append(
                    or_(
                        Property.features.op("@>")(cast(json.dumps({feature: True}), JSONB)),
                        Property.features.op("@>")(cast(json.dumps([feature]), JSONB)),
                    )
                )

        # Short stay filters
        if filters.guests is not None:
            logger.debug("Adding max occupancy filter for guests: %s", filters.guests)
            conditions.append(Property.max_occupancy >= filters.guests)

        # Booking availability filtering - exclude properties with conflicting bookings
        if getattr(filters, "check_in_date", None) and getattr(filters, "check_out_date", None):
            from datetime import datetime

            from app.models.bookings import Booking

            logger.debug(
                "Adding availability filter: %s to %s",
                filters.check_in_date,
                filters.check_out_date,
            )

            # Parse date strings if needed
            check_in = (
                datetime.fromisoformat(filters.check_in_date)
                if isinstance(filters.check_in_date, str)
                else filters.check_in_date
            )
            check_out = (
                datetime.fromisoformat(filters.check_out_date)
                if isinstance(filters.check_out_date, str)
                else filters.check_out_date
            )

            # Subquery to find properties with conflicting confirmed/checked-in bookings
            # Overlap logic: existing.check_in < requested.check_out AND existing.check_out > requested.check_in
            booked_properties_subquery = (
                select(Booking.property_id)
                .where(
                    and_(
                        Booking.booking_status.in_(
                            [BookingStatus.confirmed, BookingStatus.checked_in]
                        ),
                        Booking.check_in_date < check_out,
                        Booking.check_out_date > check_in,
                    )
                )
                .distinct()
            )

            # Exclude properties that have conflicting bookings
            conditions.append(~Property.id.in_(booked_properties_subquery))

        # Optionally exclude properties already swiped by the user if authenticated
        if user_id and getattr(filters, "exclude_swiped", False):
            from app.models.users import UserSwipe

            swiped_subquery = select(UserSwipe.property_id).where(
                UserSwipe.user_id == user_id,
                UserSwipe.target_type == "property",
                UserSwipe.property_id.is_not(None),
            )
            conditions.append(~Property.id.in_(swiped_subquery))

        # Prepare semantic embedding if requested; fall back to text search on failure
        if semantic_enabled and filters.search_query:
            try:
                vector_vals = await embed_query(filters.search_query)
                if vector_vals:
                    semantic_embedding = (
                        vector_vals[0] if isinstance(vector_vals[0], list) else vector_vals
                    )
                else:
                    semantic_enabled = False
                    logger.warning(
                        "Semantic search requested but embedding service returned no vector"
                    )
            except Exception as e:
                semantic_enabled = False
                logger.error(
                    "Semantic embedding generation failed, falling back to text search: %s", e
                )

        if (
            search_query_obj is not None
            and search_vector is not None
            and not text_filter_applied
            and not semantic_enabled
        ):
            conditions.append(search_vector.op("@@")(search_query_obj))
            text_filter_applied = True

        if semantic_enabled and semantic_embedding:
            # pgvector (and numpy) load lazily here on first semantic search.
            from pgvector.sqlalchemy import Vector

            property_embeddings_table = _get_property_embeddings_table()

            query = query.outerjoin(
                property_embeddings_table, property_embeddings_table.c.property_id == Property.id
            )
            count_query = count_query.outerjoin(
                property_embeddings_table, property_embeddings_table.c.property_id == Property.id
            )

            query_vector_param = bindparam(
                "query_vector", value=semantic_embedding, type_=Vector(768)
            )
            vector_distance_expr = func.coalesce(
                property_embeddings_table.c.embedding.cosine_distance(query_vector_param), 2.0
            )
            vector_score_expr = 1.0 / (1.0 + vector_distance_expr)
            text_component = (
                func.coalesce(text_rank_expr, 0.0) if text_rank_expr is not None else 0.0
            )
            combined_relevance_expr = (VECTOR_WEIGHT * vector_score_expr) + (
                TEXT_WEIGHT * text_component
            )
            query = query.add_columns(
                vector_distance_expr.label("vector_distance"),
                combined_relevance_expr.label("relevance_score"),
            )
            has_additional_columns = True

        # Apply all conditions
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        # Apply sorting - use distance only if location is provided
        sort_by = filters.sort_by
        if semantic_enabled and sort_by in (SortBy.distance, SortBy.newest):
            sort_by = SortBy.relevance
        if sort_by is None:
            sort_by = (
                SortBy.distance
                if (filters.latitude is not None and filters.longitude is not None)
                else SortBy.newest
            )

        if sort_by == SortBy.distance and distance is not None:
            query = query.order_by(distance)
        elif sort_by == SortBy.price_low:
            query = query.order_by(Property.base_price.asc())
        elif sort_by == SortBy.price_high:
            query = query.order_by(Property.base_price.desc())
        elif sort_by == SortBy.newest:
            query = query.order_by(Property.created_at.desc())
        elif sort_by == SortBy.popular:
            # Sort by like count, then view count
            query = query.order_by(Property.like_count.desc(), Property.view_count.desc())
        elif sort_by == SortBy.relevance:
            if combined_relevance_expr is not None:
                query = query.order_by(combined_relevance_expr.desc())
            elif text_rank_expr is not None:
                query = query.order_by(text_rank_expr.desc())
            elif search_query_obj is not None and search_vector is not None:
                fallback_rank = func.ts_rank(search_vector, search_query_obj)
                query = query.order_by(fallback_rank.desc())
            else:
                query = query.order_by(Property.created_at.desc())
        else:
            # Default sorting
            query = query.order_by(Property.created_at.desc())

        # Count only when requested (avoids extra query on every page)
        count_total: int | None = None
        if with_total:
            count_result = await execute_with_transient_retry(
                db,
                lambda: db.execute(count_query),
                operation_name="property_search_count",
            )
            count_total = count_result.scalar()

        # Fetch limit+1 to detect has_more
        query = query.offset(skip).limit(limit + 1)

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_search_query",
        )

        # Build PropertySchema list directly, avoiding ORM attribute corruption
        # when add_columns() returns Row tuples instead of pure ORM objects.
        if has_additional_columns:
            rows = result.all()
            property_list = []
            for row in rows:
                mapping = row._mapping if hasattr(row, "_mapping") else {}
                prop = mapping.get("Property") or mapping.get(Property)
                if prop is None:
                    prop = row[0] if isinstance(row, tuple) and len(row) > 0 else row
                if not prop:
                    continue
                schema = PropertySchema.model_validate(prop)
                if "distance_km" in mapping and mapping["distance_km"] is not None:
                    schema.distance_km = float(mapping["distance_km"])
                if "vector_distance" in mapping and mapping["vector_distance"] is not None:
                    schema.vector_distance = float(mapping["vector_distance"])
                if "relevance_score" in mapping and mapping["relevance_score"] is not None:
                    schema.relevance_score = float(mapping["relevance_score"])
                property_list.append(schema)
        else:
            properties = list(result.scalars().all())
            property_list = [PropertySchema.model_validate(prop) for prop in properties]

        # Detect has_more and compute next cursor
        has_more = len(property_list) > limit
        if has_more:
            property_list = property_list[:limit]
        next_payload: dict | None = offset_payload(skip + limit) if has_more else None

        logger.info(
            "Found %s properties out of %s total",
            len(property_list),
            count_total,
            extra={
                "result_count": len(property_list),
                "total_count": count_total,
                "offset": skip,
                "limit": limit,
                "user_id": user_id,
                "search_query": filters.search_query,
                "city": filters.city,
                "purpose": filters.purpose.value if filters.purpose else None,
            },
        )

        if should_cache:
            try:
                cache_payload = {
                    "items": [p.model_dump(mode="json") for p in property_list],
                    "total": count_total,
                    "has_more": next_payload is not None,
                }
                await PropertyCacheManager.cache_properties(
                    cache_filters,
                    cache_user_id,
                    1,
                    limit,
                    cache_payload,
                    ttl=settings.CACHE_TTL_PROPERTIES_LIST,
                )
            except Exception as cache_exc:  # noqa: BLE001
                logger.warning("Failed to cache property search: %s", cache_exc)

        return property_list, next_payload, count_total
    except Exception as e:
        logger.error("Failed to search properties: %s", e, exc_info=True)
        raise
