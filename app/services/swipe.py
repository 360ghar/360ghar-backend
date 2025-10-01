from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, desc, func, case
from sqlalchemy.orm import selectinload
from typing import Optional
from app.models.users import UserSwipe
from app.models.properties import Property, PropertyAmenity, Amenity
from app.schemas.property import PropertySwipe, UnifiedPropertyFilter, SortBy

async def record_swipe(db: AsyncSession, user_id: int, swipe_data: PropertySwipe):
    """Record or update swipe"""
    # First check if the property exists
    property_check = await db.execute(
        select(Property.id).where(Property.id == swipe_data.property_id)
    )
    if not property_check.scalar_one_or_none():
        # Property doesn't exist, silently return success to avoid client errors
        # This handles cases where properties are deleted after being shown to users
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
        # Update existing swipe
        existing_swipe.is_liked = swipe_data.is_liked
        existing_swipe.updated_at = func.now()
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
            stmt = update(Property).where(Property.id == swipe_data.property_id).values(
                like_count=Property.like_count + 1
            )
            await db.execute(stmt)
    
    await db.flush()
    return True

async def get_swipe_history(db: AsyncSession, user_id: int, filters: UnifiedPropertyFilter, page: int, limit: int, is_liked: Optional[bool]):
    """Get user's swipe history with comprehensive property filtering"""
    skip = (page - 1) * limit

    # Base query with optimized eager loading
    # Use outerjoin to include swipes even if property was deleted, then filter nulls
    query = select(UserSwipe).options(
        selectinload(UserSwipe.property).selectinload(Property.images),
        selectinload(UserSwipe.property).selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity)
    ).join(UserSwipe.property)  # Inner join to exclude deleted properties

    count_query = select(func.count(UserSwipe.id)).join(UserSwipe.property)  # Inner join for count too

    # Always filter by user_id
    conditions = [UserSwipe.user_id == user_id]

    # Swipe-specific filter
    if is_liked is not None:
        conditions.append(UserSwipe.is_liked == is_liked)

    # Location-based search
    user_location = None
    distance = None
    if filters.latitude and filters.longitude and filters.radius_km:
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

    # Location filters
    if filters.city:
        conditions.append(Property.city.ilike(f"%{filters.city}%"))
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

    # Add pagination
    query = query.offset(skip).limit(limit)

    # Execute queries
    result = await db.execute(query)
    count_result = await db.execute(count_query)

    # Handle results - check if we have additional columns (distance)
    if distance is not None:
        rows = result.all()
        swipes = [row[0] for row in rows]  # First column is the UserSwipe object
    else:
        swipes = result.scalars().all()

    total_count = count_result.scalar()

    # Add liked attribute to properties
    for swipe in swipes:
        if swipe.property:
            swipe.property.liked = swipe.is_liked

    return {
        "items": swipes,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": (total_count + limit - 1) // limit if total_count else 0
    }

async def undo_last_swipe(db: AsyncSession, user_id: int):
    """Undo last swipe"""
    stmt = select(UserSwipe).where(
        UserSwipe.user_id == user_id
    ).order_by(desc(UserSwipe.created_at)).limit(1)
    
    result = await db.execute(stmt)
    last_swipe = result.scalar_one_or_none()
    
    if last_swipe:
        # Update like count if it was liked
        if last_swipe.is_liked:
            stmt = update(Property).where(Property.id == last_swipe.property_id).values(
                like_count=Property.like_count - 1
            )
            await db.execute(stmt)
        
        await db.delete(last_swipe)
        await db.flush()
        return last_swipe
    
    return None

async def toggle_swipe(db: AsyncSession, swipe_id: int, user_id: int):
    """Toggle swipe like status"""
    swipe = await db.get(UserSwipe, swipe_id)
    
    if swipe and swipe.user_id == user_id:
        old_status = swipe.is_liked
        swipe.is_liked = not old_status
        
        # Update property like count
        if swipe.is_liked:
            stmt = update(Property).where(Property.id == swipe.property_id).values(
                like_count=Property.like_count + 1
            )
        else:
            stmt = update(Property).where(Property.id == swipe.property_id).values(
                like_count=Property.like_count - 1
            )
        await db.execute(stmt)
        
        await db.flush()
        return {"new_status": swipe.is_liked, "property_id": swipe.property_id}
    
    return None

async def get_swipe_stats(db: AsyncSession, user_id: int):
    """Get swipe statistics"""
    stmt = select(
        func.count(UserSwipe.id).label('total_swipes'),
        func.sum(case((UserSwipe.is_liked == True, 1), else_=0)).label('liked_count'),
        func.sum(case((UserSwipe.is_liked == False, 1), else_=0)).label('disliked_count')
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

async def get_user_like_for_property(db: AsyncSession, user_id: int, property_id: int) -> Optional[bool]:
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
