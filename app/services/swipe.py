from __future__ import annotations

from sqlalchemy import and_, case, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.utils import utc_now
from app.models.properties import Amenity, Property, PropertyAmenity
from app.models.users import UserSwipe
from app.schemas.pagination import offset_payload, read_offset
from app.schemas.property import PropertySwipe, SortBy, UnifiedPropertyFilter
from app.utils.geo import normalize_city


async def record_swipe(db: AsyncSession, user_id: int, swipe_data: PropertySwipe):
    """Record or update swipe"""
    # First check if the property exists and user is not swiping their own property
    property_check = await db.execute(
        select(Property.id, Property.owner_id).where(Property.id == swipe_data.property_id)
    )
    property_row = property_check.one_or_none()
    if not property_row:
        # Property doesn't exist, silently return success to avoid client errors
        # This handles cases where properties are deleted after being shown to users
        return False

    if property_row[1] == user_id:
        # User is trying to swipe their own property — silently ignore
        return False

    # Check if swipe exists
    stmt = select(UserSwipe).where(
        and_(
            UserSwipe.user_id == user_id,
            UserSwipe.property_id == swipe_data.property_id
        )
    )
    result = await db.execute(stmt)
    existing_swipe = result.scalar_one_or_none()

    if existing_swipe:
        # Update existing swipe. Adjust like_count only if the status actually
        # flipped. The in-memory `old_liked` could be stale under interleaved
        # like→dislike→like toggles from the same user, so we re-read the DB
        # inside the same savepoint and gate the diff on the fresh value.
        async with db.begin_nested():
            await db.refresh(existing_swipe)
            old_liked_db = existing_swipe.is_liked
            existing_swipe.is_liked = swipe_data.is_liked
            existing_swipe.updated_at = utc_now()

            if old_liked_db and not swipe_data.is_liked:
                # Changed from like to dislike — decrement
                await db.execute(
                    update(Property).where(Property.id == swipe_data.property_id).values(
                        like_count=Property.like_count - 1
                    )
                )
            elif not old_liked_db and swipe_data.is_liked:
                # Changed from dislike to like — increment
                await db.execute(
                    update(Property).where(Property.id == swipe_data.property_id).values(
                        like_count=Property.like_count + 1
                    )
                )
    else:
        # Create new swipe
        swipe = UserSwipe(
            user_id=user_id,
            property_id=swipe_data.property_id,
            is_liked=swipe_data.is_liked
        )
        db.add(swipe)

        # Update property like count
        if swipe_data.is_liked:
            update_stmt = update(Property).where(Property.id == swipe_data.property_id).values(
                like_count=Property.like_count + 1
            )
            await db.execute(update_stmt)

    await db.flush()
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
    """Get user's swipe history with comprehensive property filtering"""
    offset = read_offset(cursor_payload)

    # Base query with optimized eager loading
    # Use outerjoin to include swipes even if property was deleted, then filter nulls
    query = select(UserSwipe).options(
        selectinload(UserSwipe.property).selectinload(Property.images),
        selectinload(UserSwipe.property).selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity)
    ).join(UserSwipe.property)  # Inner join to exclude deleted properties

    count_query = select(func.count(UserSwipe.id)).join(UserSwipe.property)  # Inner join for count too

    from app.models.enums import PG_FLATMATE_TYPES

    # Always filter by user_id
    conditions = [UserSwipe.user_id == user_id]

    # Only show swipes on available, live properties (mirrors main search filter)
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

    # Swipe-specific filter
    if is_liked is not None:
        conditions.append(UserSwipe.is_liked == is_liked)

    # Location-based search
    user_location = None
    distance = None
    if filters.latitude is not None and filters.longitude is not None and filters.radius_km:
        # Create a point from the user's location, ensuring SRID is set
        user_location = func.ST_SetSRID(func.ST_MakePoint(filters.longitude, filters.latitude), 4326)

        # Use ST_DWithin for efficient, index-based distance filtering
        radius_m = filters.radius_km * 1000
        conditions.append(func.ST_DWithin(Property.location, user_location, radius_m))

        # Calculate distance for ordering and display
        distance = func.ST_Distance(Property.location, user_location) / 1000
        query = query.add_columns(distance.label('distance_km'))

    # Text search using PostgreSQL full-text search
    search_query_obj = None
    if filters.search_query:
        search_query_obj = func.plainto_tsquery('english', filters.search_query)
        # Use SQLAlchemy's proper text search functions to avoid SQL injection
        search_vector = func.to_tsvector('english', func.concat(
            Property.title, ' ',
            Property.description, ' ',
            Property.locality, ' ',
            Property.city
        ))
        conditions.append(search_vector.op('@@')(search_query_obj))

    # Property type filter
    if filters.property_type:
        if isinstance(filters.property_type, list) and len(filters.property_type) > 0:
            conditions.append(Property.property_type.in_(filters.property_type))
        elif not isinstance(filters.property_type, list):
            conditions.append(Property.property_type == filters.property_type)

    # Purpose filter
    if filters.purpose:
        conditions.append(Property.purpose == filters.purpose)

    # Price range filters
    if filters.price_min is not None:
        conditions.append(Property.base_price >= filters.price_min)
    if filters.price_max is not None:
        conditions.append(Property.base_price <= filters.price_max)

    # Bedroom filters
    if filters.bedrooms_min is not None:
        conditions.append(Property.bedrooms >= filters.bedrooms_min)
    if filters.bedrooms_max is not None:
        conditions.append(Property.bedrooms <= filters.bedrooms_max)

    # Bathroom filters
    if filters.bathrooms_min is not None:
        conditions.append(Property.bathrooms >= filters.bathrooms_min)
    if filters.bathrooms_max is not None:
        conditions.append(Property.bathrooms <= filters.bathrooms_max)

    # Area filters
    if filters.area_min is not None:
        conditions.append(Property.area_sqft >= filters.area_min)
    if filters.area_max is not None:
        conditions.append(Property.area_sqft <= filters.area_max)

    # Location filters — normalize city via alias map, then filtered LIKE
    if filters.city:
        normalized_city = normalize_city(filters.city)
        conditions.append(func.lower(Property.city).like(f"%{normalized_city.lower()}%"))
    if filters.locality:
        conditions.append(Property.locality.ilike(f"%{filters.locality}%"))
    if filters.pincode:
        conditions.append(Property.pincode == filters.pincode)

    # Additional filters
    if filters.parking_spaces_min is not None:
        conditions.append(Property.parking_spaces >= filters.parking_spaces_min)

    if filters.floor_number_min is not None:
        conditions.append(Property.floor_number >= filters.floor_number_min)
    if filters.floor_number_max is not None:
        conditions.append(Property.floor_number <= filters.floor_number_max)

    if filters.age_max is not None:
        conditions.append(Property.age_of_property <= filters.age_max)

    # Amenities filter
    if filters.amenities:
        amenity_ids = []
        amenity_names = []

        for amenity in filters.amenities:
            if isinstance(amenity, int) or (isinstance(amenity, str) and amenity.isdigit()):
                amenity_ids.append(int(amenity))
            else:
                amenity_names.append(amenity)

        # Get amenity IDs from names if any
        if amenity_names:
            amenity_result = await db.execute(
                select(Amenity.id).where(Amenity.title.in_(amenity_names))
            )
            amenity_ids.extend([row[0] for row in amenity_result.fetchall()])

        if amenity_ids:
            amenity_subquery = (
                select(PropertyAmenity.property_id)
                .where(PropertyAmenity.amenity_id.in_(amenity_ids))
                .group_by(PropertyAmenity.property_id)
                .having(func.count(PropertyAmenity.amenity_id) >= len(amenity_ids))
            )
            conditions.append(Property.id.in_(amenity_subquery))

    # Guests filter (max occupancy)
    if filters.guests is not None:
        conditions.append(Property.max_occupancy >= filters.guests)

    # Apply all conditions
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    # Apply sorting
    sort_by = filters.sort_by or SortBy.newest

    if sort_by == SortBy.distance and distance is not None:
        query = query.order_by(distance)
    elif sort_by == SortBy.price_low:
        query = query.order_by(Property.base_price.asc())
    elif sort_by == SortBy.price_high:
        query = query.order_by(Property.base_price.desc())
    elif sort_by == SortBy.newest:
        query = query.order_by(desc(UserSwipe.created_at))
    elif sort_by == SortBy.popular:
        query = query.order_by(Property.like_count.desc(), Property.view_count.desc())
    elif sort_by == SortBy.relevance and search_query_obj is not None:
        # Calculate relevance score using SQLAlchemy functions
        search_vector = func.to_tsvector('english', func.concat(
            Property.title, ' ',
            Property.description, ' ',
            Property.locality, ' ',
            Property.city
        ))
        relevance_score = func.ts_rank(search_vector, search_query_obj)
        query = query.order_by(relevance_score.desc())
    else:
        # Default sorting by swipe creation date
        query = query.order_by(desc(UserSwipe.created_at))

    # Compute total count before applying offset/limit if requested
    count_total: int | None = None
    if with_total:
        count_result = await db.execute(count_query)
        count_total = int(count_result.scalar() or 0)

    # Add cursor-based offset pagination
    query = query.offset(offset).limit(limit + 1)

    # Execute main query
    result = await db.execute(query)

    # Handle results - check if we have additional columns (distance)
    if distance is not None:
        rows = result.all()
        swipes = [row[0] for row in rows]  # First column is the UserSwipe object
    else:
        swipes = list(result.scalars().all())

    # Determine if there's a next page
    next_payload: dict | None = offset_payload(offset + limit) if len(swipes) > limit else None
    swipes = swipes[:limit]

    # Add liked attribute to properties
    for swipe in swipes:
        if swipe.property:
            swipe.property.liked = swipe.is_liked

    return swipes, next_payload, count_total

async def undo_last_swipe(db: AsyncSession, user_id: int):
    """Undo last swipe"""
    stmt = select(UserSwipe).where(
        UserSwipe.user_id == user_id
    ).order_by(desc(UserSwipe.created_at)).limit(1)

    result = await db.execute(stmt)
    last_swipe = result.scalar_one_or_none()

    if last_swipe:
        # Use savepoint to ensure like count decrement + delete are atomic
        async with db.begin_nested():
            if last_swipe.is_liked:
                update_stmt = update(Property).where(Property.id == last_swipe.property_id).values(
                    like_count=Property.like_count - 1
                )
                await db.execute(update_stmt)
            await db.delete(last_swipe)
        await db.flush()
        return last_swipe

    return None

async def toggle_swipe(db: AsyncSession, swipe_id: int, user_id: int):
    """Toggle swipe like status"""
    swipe = await db.get(UserSwipe, swipe_id)

    if swipe and swipe.user_id == user_id:
        # Use savepoint to ensure toggle + like count update are atomic.
        # The attribute mutation MUST happen inside the savepoint so that a
        # failed UPDATE rolls back the in-memory change too — otherwise the
        # returned new_status and like_count would drift from the DB.
        async with db.begin_nested():
            swipe.is_liked = not swipe.is_liked
            if swipe.is_liked:
                update_stmt = update(Property).where(Property.id == swipe.property_id).values(
                    like_count=Property.like_count + 1
                )
            else:
                update_stmt = update(Property).where(Property.id == swipe.property_id).values(
                    like_count=Property.like_count - 1
                )
            await db.execute(update_stmt)

        await db.flush()
        return {"new_status": swipe.is_liked, "property_id": swipe.property_id}

    return None

async def get_swipe_stats(db: AsyncSession, user_id: int):
    """Get swipe statistics"""
    stmt = select(
        func.count(UserSwipe.id).label('total_swipes'),
        func.sum(case((UserSwipe.is_liked, 1), else_=0)).label('liked_count'),
        func.sum(case((~UserSwipe.is_liked, 1), else_=0)).label('disliked_count')
    ).where(UserSwipe.user_id == user_id)

    result = await db.execute(stmt)
    stats = result.one()

    total = stats.total_swipes or 0
    liked = stats.liked_count or 0
    disliked = stats.disliked_count or 0

    return {
        "total_swipes": total,
        "liked_count": liked,
        "disliked_count": disliked,
        "like_percentage": (liked / total * 100) if total > 0 else 0
    }

async def get_user_like_for_property(db: AsyncSession, user_id: int, property_id: int) -> bool | None:
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


async def batch_unswipe(db: AsyncSession, user_id: int, property_ids: list[int]) -> int:
    """Remove many liked swipes for a user in a single transaction.

    Decrements property like_count for each removed like. Returns the number
    of swipes actually deleted.
    """
    if not property_ids:
        return 0

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
        return 0

    stmt = select(UserSwipe).where(
        and_(
            UserSwipe.user_id == user_id,
            UserSwipe.property_id.in_(unique_ids),
        )
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return 0

    async with db.begin_nested():
        for swipe in rows:
            if swipe.is_liked:
                await db.execute(
                    update(Property)
                    .where(Property.id == swipe.property_id)
                    .values(like_count=Property.like_count - 1)
                )
            await db.delete(swipe)
    await db.flush()
    return len(rows)
