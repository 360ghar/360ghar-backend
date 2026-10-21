"""Unified property search with comprehensive filtering and geospatial optimization."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    Table,
    and_,
    bindparam,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.config import settings
from app.core.cache import PropertyCacheManager
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.properties import Amenity, Property, PropertyAmenity, PropertyImage
from app.models.users import User
from app.repositories.property_query_builder import PropertyQueryBuilder
from app.schemas.pagination import keyset_payload
from app.schemas.property import Property as PropertySchema
from app.schemas.property import SortBy, UnifiedPropertyFilter
from app.services.flatmates.compatibility import (
    score_viewer_owner_compatibility,
    snapshot_user_for_compat,
    user_has_lifestyle_profile,
)
from app.services.property.crud import attach_owner_agents
from app.services.property.keyset import cursor_kinds, json_key, keyset_after, read_cursor_key
from app.vector.embedding_client import embed_query

# Columns needed to score property-owner lifestyle compatibility.
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


def _property_ts_vector_column() -> ColumnElement[Any]:
    """Return the named table column used for PostgreSQL full-text search."""
    return Property.__table__.c["__ts_vector__"]


async def get_unified_properties_optimized(
    db: AsyncSession,
    filters: UnifiedPropertyFilter,
    user_id: int | None,
    cursor_payload: dict,
    limit: int,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """Unified property search with comprehensive filtering and geospatial optimization.

    Pages use a keyset cursor on (sort key(s), id). Rows that are removed between
    two requests (for example by a swipe) do not shift the next page.
    """
    first_page = not cursor_payload
    logger.info(
        "Searching properties for user %s, limit %s, filters: %s",
        user_id,
        limit,
        filters,
        extra={
            "user_id": user_id,
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
        # include_total is part of the key: a page with a total and a page without one
        # are different responses.
        cache_filters = {
            **filters.model_dump(exclude_none=True, mode="json"),
            "include_total": with_total,
        }
        cache_user_id = user_id or 0
        # Only cache unauthenticated first-page results
        should_cache = user_id is None and first_page
        if should_cache:
            cached = await PropertyCacheManager.get_cached_properties(
                cache_filters, cache_user_id, 1, limit
            )
            if cached:
                try:
                    cached_items = [
                        PropertySchema.model_validate(item) for item in cached.get("items", [])
                    ]
                    # Entries written before the keyset cursor have no "next". Skip them
                    # when another page exists, so the cursor is never lost.
                    cached_has_more = bool(cached.get("has_more", False))
                    cached_next = cached.get("next")
                    if not cached_has_more or cached_next is not None:
                        # Return as 3-tuple: (items, next_payload, total). total is set only
                        # when the caller asked for it.
                        cached_total = cached.get("total") if with_total else None
                        return cached_items[:limit], cached_next, cached_total
                except Exception as cache_exc:  # noqa: BLE001
                    logger.warning("Ignoring invalid property search cache: %s", cache_exc)

        # Bound this read so a stalled DB backend fails fast instead of holding
        # a pooler connection until the 2-minute server default and cascading
        # into pool exhaustion. Scoped to the current transaction (SET LOCAL).
        await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)

        # Base query with eager loading. Owner lifestyle columns are loaded only
        # when the viewer has a lifestyle profile (otherwise scoring is a no-op).
        query_options = [
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
        ]
        # Snapshot lifestyle fields before any execute_with_transient_retry call.
        # A retry invalidates the session and detaches this ORM User; later
        # access to current_user.id would raise DetachedInstanceError.
        current_user = await db.get(User, user_id) if user_id else None
        score_compatibility = user_has_lifestyle_profile(current_user)
        viewer_for_compat = snapshot_user_for_compat(current_user) if score_compatibility else None
        viewer_id = viewer_for_compat.id if viewer_for_compat is not None else None
        # Read before any retry. Only an admin may list unavailable listings by status.
        viewer_is_admin = current_user is not None and current_user.role == UserRole.admin
        if score_compatibility:
            query_options.append(selectinload(Property.owner).load_only(*_OWNER_COMPAT_LOAD_ONLY))
        query = select(Property).options(*query_options)
        count_query = select(func.count(Property.id))

        # Semantic search embeds the query first. Any failure falls back to text search.
        semantic_enabled = bool(filters.semantic_search and filters.search_query)
        semantic_embedding = None
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

        # Every property filter comes from the shared builder. The text match is a hard
        # filter only when semantic search is not in use.
        conditions, distance, search_meta = await PropertyQueryBuilder(filters).build(
            db,
            include_unavailable=filters.include_unavailable,
            hard_filter_text=not semantic_enabled,
            viewer_id=user_id,
            viewer_is_admin=viewer_is_admin,
        )
        text_rank_expr = search_meta["text_rank_expr"]
        combined_relevance_expr = None

        if distance is not None:
            query = query.add_columns(distance.label("distance_km"))

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
            # The combined score orders the results. The API does not return it.
            combined_relevance_expr = (VECTOR_WEIGHT * vector_score_expr) + (
                TEXT_WEIGHT * text_component
            )

        # Apply all conditions
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        # Apply sorting. Each sort lists its keys. id is the last key, so every row has
        # a unique position for the keyset cursor.
        sort_by = filters.sort_by
        if semantic_enabled and sort_by in (SortBy.distance, SortBy.newest):
            sort_by = SortBy.relevance
        if sort_by is None:
            sort_by = (
                SortBy.distance
                if (filters.latitude is not None and filters.longitude is not None)
                else SortBy.newest
            )

        newest_keys: list[tuple[Any, Any, bool]] = [
            (Property.created_at, DateTime(timezone=True), True)
        ]
        rank_expr = (
            combined_relevance_expr if combined_relevance_expr is not None else text_rank_expr
        )
        sort_keys: list[tuple[Any, Any, bool]]
        if sort_by == SortBy.distance and distance is not None:
            sort_keys = [(distance, Float(), False)]
        elif sort_by == SortBy.price_low:
            sort_keys = [(Property.base_price, Numeric(), False)]
        elif sort_by == SortBy.price_high:
            sort_keys = [(Property.base_price, Numeric(), True)]
        elif sort_by == SortBy.newest:
            sort_keys = newest_keys
        elif sort_by == SortBy.popular:
            # Most liked first, then most viewed
            sort_keys = [
                (Property.like_count, Integer(), True),
                (Property.view_count, Integer(), True),
            ]
        elif sort_by == SortBy.relevance and rank_expr is not None:
            sort_keys = [(rank_expr, Float(), True)]
        else:
            sort_keys = newest_keys
        id_desc = sort_keys[-1][2]

        # Labelled sort keys come back with each row, so the next cursor can be built.
        for index, (sort_expr, _sql_type, _desc) in enumerate(sort_keys):
            query = query.add_columns(sort_expr.label(f"sk{index}"))

        cursor_key = read_cursor_key(cursor_payload, cursor_kinds(sort_keys))
        if cursor_key is not None:
            cursor_values, cursor_id = cursor_key
            query = query.where(keyset_after(sort_keys, id_desc, cursor_values, cursor_id))

        order_terms = [expr.desc() if desc else expr.asc() for expr, _t, desc in sort_keys]
        order_terms.append(Property.id.desc() if id_desc else Property.id.asc())
        query = query.order_by(*order_terms)

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
        query = query.limit(limit + 1)

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_search_query",
        )

        # Build PropertySchema list from the row mapping: the entity, the computed
        # columns and the sort keys. The sort keys feed the next cursor.
        property_list: list[PropertySchema] = []
        key_values: list[list[Any]] = []
        for row in result.all():
            mapping = row._mapping if hasattr(row, "_mapping") else {}
            prop = mapping.get("Property") or mapping.get(Property)
            if prop is None:
                prop = row[0] if isinstance(row, tuple) and len(row) > 0 else row
            if not prop:
                continue
            schema = PropertySchema.model_validate(prop)
            if mapping.get("distance_km") is not None:
                schema.distance_km = float(mapping["distance_km"])
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
            property_list.append(schema)
            key_values.append([json_key(mapping.get(f"sk{i}")) for i in range(len(sort_keys))])

        # Detect has_more and build the next keyset cursor from the last row kept
        has_more = len(property_list) > limit
        if has_more:
            property_list = property_list[:limit]
            key_values = key_values[:limit]
        next_payload: dict | None = (
            keyset_payload(key_values[-1], property_list[-1].id)
            if has_more and property_list
            else None
        )
        # The owner-contact fallback needs the agent on every row, cache entries included.
        await attach_owner_agents(db, property_list)

        logger.info(
            "Found %s properties out of %s total",
            len(property_list),
            count_total,
            extra={
                "result_count": len(property_list),
                "total_count": count_total,
                "has_more": next_payload is not None,
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
                    "items": [p.cache_payload() for p in property_list],
                    "total": count_total,
                    "has_more": next_payload is not None,
                    "next": next_payload,
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

        return property_list, next_payload, (count_total if with_total else None)
    except Exception as e:
        logger.error("Failed to search properties: %s", e, exc_info=True)
        raise
