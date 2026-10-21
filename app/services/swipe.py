from __future__ import annotations

from sqlalchemy import and_, case, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.utils import utc_now
from app.models.enums import SwipeTargetType
from app.models.properties import Property, PropertyAmenity
from app.models.users import UserSwipe
from app.repositories.property_query_builder import PropertyQueryBuilder
from app.schemas.pagination import offset_payload, read_offset
from app.schemas.property import PropertySwipe, SortBy, UnifiedPropertyFilter


def _property_swipe_scope(user_id: int) -> tuple:
    """Predicates for the caller's property swipes.

    Flatmates peer swipes share the user_swipes table (target_type='user', target_user_id
    set, property_id NULL). They are not property swipes, so undo, toggle, stats, batch
    remove and the feed never read them.
    """
    return (
        UserSwipe.user_id == user_id,
        UserSwipe.target_type == SwipeTargetType.property.value,
        UserSwipe.target_user_id.is_(None),
    )


def _is_property_swipe(swipe: UserSwipe) -> bool:
    return swipe.target_type == SwipeTargetType.property.value and swipe.target_user_id is None


async def _upsert_user_swipe(
    db: AsyncSession,
    user_id: int,
    *,
    property_id: int | None,
    target_user_id: int | None,
    context_property_id: int | None,
    target_type: str,
    swipe_action: str,
    is_liked: bool,
) -> tuple[UserSwipe, bool, bool]:
    """Atomically insert or lock-and-update a user swipe.

    Returns:
        A tuple of (swipe, was_liked, created). `was_liked` is the previous
        `is_liked` value, and `created` is True when a new row was inserted.
    """
    if target_type == "property":
        conflict_cols = ["user_id", "property_id"]
        conflict_where = None
        where_clause = and_(
            UserSwipe.user_id == user_id,
            UserSwipe.property_id == property_id,
        )
    else:
        conflict_cols = ["user_id", "target_user_id"]
        conflict_where = UserSwipe.target_user_id.is_not(None)
        where_clause = and_(
            UserSwipe.user_id == user_id,
            UserSwipe.target_user_id == target_user_id,
        )

    now = utc_now()
    insert_stmt = (
        pg_insert(UserSwipe)
        .values(
            user_id=user_id,
            property_id=property_id,
            target_user_id=target_user_id,
            context_property_id=context_property_id,
            target_type=target_type,
            swipe_action=swipe_action,
            is_liked=is_liked,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=conflict_cols, index_where=conflict_where)
        .returning(UserSwipe.id)
    )
    result = await db.execute(insert_stmt)
    swipe_id = result.scalar_one_or_none()
    if swipe_id is not None:
        swipe = await db.get(UserSwipe, swipe_id)
        if swipe is None:
            raise RuntimeError("Failed to load newly created user swipe")
        return swipe, False, True

    swipe = (await db.execute(select(UserSwipe).where(where_clause).with_for_update())).scalar_one()
    old_is_liked = swipe.is_liked
    swipe.target_type = target_type
    swipe.swipe_action = swipe_action
    swipe.is_liked = is_liked
    swipe.context_property_id = context_property_id
    return swipe, old_is_liked, False


async def upsert_property_swipe(
    db: AsyncSession, user_id: int, property_id: int, is_liked: bool
) -> tuple[UserSwipe, bool]:
    """Store a like or pass for a property. Returns (swipe, created).

    Raises NotFoundException when the property does not exist, and ForbiddenException
    when the user swipes their own property.
    """
    property_row = (
        await db.execute(select(Property.id, Property.owner_id).where(Property.id == property_id))
    ).one_or_none()
    if property_row is None:
        raise NotFoundException(detail="Property not found", error_code="PROPERTY_NOT_FOUND")
    if property_row[1] == user_id:
        raise ForbiddenException(
            detail="You cannot swipe your own property", error_code="OWN_PROPERTY_SWIPE"
        )

    swipe_action = "like" if is_liked else "pass"
    swipe, was_liked, created = await _upsert_user_swipe(
        db,
        user_id,
        property_id=property_id,
        target_user_id=None,
        context_property_id=None,
        target_type="property",
        swipe_action=swipe_action,
        is_liked=is_liked,
    )

    if is_liked and not was_liked:
        await db.execute(
            update(Property)
            .where(Property.id == property_id)
            .values(like_count=func.coalesce(Property.like_count, 0) + 1)
        )
    elif was_liked and not is_liked:
        await db.execute(
            update(Property)
            .where(Property.id == property_id)
            .values(like_count=func.greatest(func.coalesce(Property.like_count, 0) - 1, 0))
        )

    await db.flush()
    return swipe, created


async def record_swipe(db: AsyncSession, user_id: int, swipe_data: PropertySwipe) -> bool:
    """Record or update a swipe. Returns False when the property is missing or owned by the user.

    MCP tools use this boolean form. The HTTP route uses upsert_property_swipe.
    """
    try:
        await upsert_property_swipe(db, user_id, swipe_data.property_id, swipe_data.is_liked)
    except (NotFoundException, ForbiddenException):
        return False
    return True


async def get_swipe_history(
    db: AsyncSession,
    user_id: int,
    filters: UnifiedPropertyFilter,
    cursor_payload: dict,
    limit: int,
    is_liked: bool | None,
    with_total: bool = False,
) -> tuple[list, dict | None, int | None]:
    """Get user's swipe history with comprehensive property filtering."""
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    offset = read_offset(cursor_payload)

    # Base query with optimized eager loading.
    # Inner join excludes swipes whose property was deleted.
    query = (
        select(UserSwipe)
        .options(
            selectinload(UserSwipe.property).selectinload(Property.images),
            selectinload(UserSwipe.property)
            .selectinload(Property.property_amenities)
            .selectinload(PropertyAmenity.amenity),
        )
        .join(UserSwipe.property)
    )

    count_query = select(func.count(UserSwipe.id)).join(UserSwipe.property)

    # Swipe-scoped predicates (not property filters).
    conditions: list = list(_property_swipe_scope(user_id))
    if is_liked is not None:
        conditions.append(UserSwipe.is_liked == is_liked)

    # Canonical property filters (availability, FTS via __ts_vector__, geo, etc.).
    builder = PropertyQueryBuilder(filters)
    property_conditions, distance_expr, search_meta = await builder.build(db)
    conditions.extend(property_conditions)

    if distance_expr is not None:
        query = query.add_columns(distance_expr.label("distance_km"))

    query = query.where(and_(*conditions))
    count_query = count_query.where(and_(*conditions))

    # newest / default sort by swipe time; other sorts use shared builder path.
    sort_by = filters.sort_by or SortBy.newest
    query = builder.apply_sort(
        query,
        sort_by,
        distance_expr=distance_expr,
        text_rank_expr=search_meta.get("text_rank_expr"),
        newest_column=UserSwipe.created_at,
    )

    count_total: int | None = None
    if with_total:
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(count_query),
            operation_name="swipe_history_count",
        )
        count_total = int(count_result.scalar() or 0)

    query = query.offset(offset).limit(limit + 1)

    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(query),
        operation_name="swipe_history_query",
    )

    if distance_expr is not None:
        rows = result.all()
        swipes = [row[0] for row in rows]
    else:
        swipes = list(result.scalars().all())

    next_payload: dict | None = offset_payload(offset + limit) if len(swipes) > limit else None
    swipes = swipes[:limit]

    for swipe in swipes:
        if swipe.property:
            swipe.property.liked = swipe.is_liked

    return swipes, next_payload, count_total


async def undo_last_swipe(db: AsyncSession, user_id: int):
    """Undo last swipe"""
    stmt = (
        select(UserSwipe)
        .where(*_property_swipe_scope(user_id))
        .order_by(desc(UserSwipe.created_at))
        .limit(1)
    )

    result = await db.execute(stmt)
    last_swipe = result.scalar_one_or_none()

    if last_swipe:
        # Use savepoint to ensure like count decrement + delete are atomic
        async with db.begin_nested():
            if last_swipe.is_liked:
                update_stmt = (
                    update(Property)
                    .where(Property.id == last_swipe.property_id)
                    .values(like_count=func.greatest(func.coalesce(Property.like_count, 0) - 1, 0))
                )
                await db.execute(update_stmt)
            await db.delete(last_swipe)
        await db.flush()
        return last_swipe

    return None


async def toggle_swipe(db: AsyncSession, swipe_id: int, user_id: int):
    """Toggle swipe like status"""
    swipe = await db.get(UserSwipe, swipe_id)

    if swipe and swipe.user_id == user_id and _is_property_swipe(swipe):
        # Use savepoint to ensure toggle + like count update are atomic.
        # The attribute mutation MUST happen inside the savepoint so that a
        # failed UPDATE rolls back the in-memory change too — otherwise the
        # returned new_status and like_count would drift from the DB.
        async with db.begin_nested():
            swipe.is_liked = not swipe.is_liked
            if swipe.is_liked:
                update_stmt = (
                    update(Property)
                    .where(Property.id == swipe.property_id)
                    .values(like_count=func.coalesce(Property.like_count, 0) + 1)
                )
            else:
                update_stmt = (
                    update(Property)
                    .where(Property.id == swipe.property_id)
                    .values(like_count=func.greatest(func.coalesce(Property.like_count, 0) - 1, 0))
                )
            await db.execute(update_stmt)

        await db.flush()
        return {"id": swipe.id, "new_status": swipe.is_liked, "property_id": swipe.property_id}

    return None


async def get_swipe_stats(db: AsyncSession, user_id: int):
    """Get swipe statistics"""
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    stmt = select(
        func.count(UserSwipe.id).label("total_swipes"),
        func.sum(case((UserSwipe.is_liked, 1), else_=0)).label("liked_count"),
        func.sum(case((~UserSwipe.is_liked, 1), else_=0)).label("disliked_count"),
    ).where(*_property_swipe_scope(user_id))

    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="swipe_stats",
    )
    stats = result.one()

    total = stats.total_swipes or 0
    liked = stats.liked_count or 0
    disliked = stats.disliked_count or 0

    return {
        "total_swipes": total,
        "liked_count": liked,
        "disliked_count": disliked,
        "like_percentage": (liked / total * 100) if total > 0 else 0,
    }


async def get_user_like_for_property(
    db: AsyncSession, user_id: int, property_id: int
) -> bool | None:
    """Return whether the user has a swipe for the property and if it's liked.

    Returns:
        True if liked, False if explicitly disliked, None if no swipe exists.
    """
    stmt = select(UserSwipe.is_liked).where(
        and_(UserSwipe.user_id == user_id, UserSwipe.property_id == property_id)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    return row[0] if row is not None else None


async def batch_unswipe(db: AsyncSession, user_id: int, property_ids: list[int]) -> list[int]:
    """Remove the user's swipes for many properties in a single transaction.

    Decrements property like_count for each removed like. Returns the property ids
    whose swipe was deleted.
    """
    if not property_ids:
        return []

    # Normalize ids to a deduplicated list of ints.
    unique_ids: list[int] = []
    seen: set[int] = set()
    for pid in property_ids:
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_int in seen:
            continue
        seen.add(pid_int)
        unique_ids.append(pid_int)
    if not unique_ids:
        return []

    stmt = select(UserSwipe).where(
        and_(
            *_property_swipe_scope(user_id),
            UserSwipe.property_id.in_(unique_ids),
        )
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return []

    async with db.begin_nested():
        for swipe in rows:
            if swipe.is_liked:
                await db.execute(
                    update(Property)
                    .where(Property.id == swipe.property_id)
                    .values(like_count=func.greatest(func.coalesce(Property.like_count, 0) - 1, 0))
                )
            await db.delete(swipe)
    await db.flush()
    return [swipe.property_id for swipe in rows if swipe.property_id is not None]
