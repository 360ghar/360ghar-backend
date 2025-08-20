from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update, text
from sqlalchemy.orm import selectinload
from typing import Optional
from app.models.models import Property, PropertyAmenity, Amenity
from app.schemas.property import PropertyCreate, PropertyUpdate, UnifiedPropertyFilter, SortBy
from app.core.logging import get_logger

logger = get_logger(__name__)

async def create_property(db: AsyncSession, property_data: PropertyCreate, owner_id: int):
    """Create new property"""
    logger.info(f"Creating property for owner {owner_id}, type: {property_data.property_type}")
    
    try:
        property_dict = property_data.model_dump(exclude_unset=True)
        property_dict["owner_id"] = owner_id

        # Create WKT for location
        if 'latitude' in property_dict and 'longitude' in property_dict:
            lat = property_dict['latitude']
            lon = property_dict['longitude']
            property_dict['location'] = f'SRID=4326;POINT({lon} {lat})'

        db_property = Property(**property_dict)
        db.add(db_property)
        await db.flush()
        await db.refresh(db_property)
        
        logger.info(f"Property created successfully with ID {db_property.id}")
        from app.schemas.property import Property as PropertySchema
        return PropertySchema.model_validate(db_property)
    except Exception as e:
        logger.error(f"Failed to create property: {str(e)}", exc_info=True)
        raise

async def get_property(db: AsyncSession, property_id: int):
    """Get property with images and owner"""
    logger.debug(f"Fetching property {property_id}")
    
    try:
        stmt = select(Property).options(
            selectinload(Property.images),
            selectinload(Property.owner)
        ).where(Property.id == property_id)
        
        result = await db.execute(stmt)
        property_obj = result.scalar_one_or_none()
        
        if property_obj:
            logger.debug(f"Property {property_id} found with {len(property_obj.images) if property_obj.images else 0} images")
            from app.schemas.property import Property as PropertySchema
            return PropertySchema.model_validate(property_obj)
        else:
            logger.warning(f"Property {property_id} not found")
            return None
    except Exception as e:
        logger.error(f"Failed to fetch property {property_id}: {str(e)}", exc_info=True)
        raise

async def update_property(db: AsyncSession, property_id: int, property_update: PropertyUpdate):
    """Update property"""
    logger.info(f"Updating property {property_id}")
    
    try:
        stmt = select(Property).options(
            selectinload(Property.images),
            selectinload(Property.owner)
        ).where(Property.id == property_id)
        
        result = await db.execute(stmt)
        property_obj = result.scalar_one_or_none()
        
        if not property_obj:
            logger.warning(f"Property {property_id} not found for update")
            return None
        
        update_data = property_update.model_dump(exclude_unset=True)

        # Handle location update
        if 'latitude' in update_data or 'longitude' in update_data:
            lat = update_data.get('latitude', property_obj.latitude)
            lon = update_data.get('longitude', property_obj.longitude)
            if lat is not None and lon is not None:
                update_data['location'] = f'SRID=4326;POINT({lon} {lat})'

        for field, value in update_data.items():
            setattr(property_obj, field, value)
        
        await db.flush()
        await db.refresh(property_obj)
        
        logger.info(f"Property {property_id} updated successfully")
        from app.schemas.property import Property as PropertySchema
        return PropertySchema.model_validate(property_obj)
    except Exception as e:
        logger.error(f"Failed to update property {property_id}: {str(e)}", exc_info=True)
        raise

async def delete_property(db: AsyncSession, property_id: int):
    """Delete property"""
    logger.info(f"Deleting property {property_id}")
    
    try:
        stmt = select(Property).where(Property.id == property_id)
        result = await db.execute(stmt)
        property_obj = result.scalar_one_or_none()
        
        if property_obj:
            await db.delete(property_obj)
            await db.flush()
            logger.info(f"Property {property_id} deleted successfully")
            return True
        else:
            logger.warning(f"Property {property_id} not found for deletion")
            return False
    except Exception as e:
        logger.error(f"Failed to delete property {property_id}: {str(e)}", exc_info=True)
        raise

async def get_unified_properties_optimized(
    db: AsyncSession,
    filters: UnifiedPropertyFilter,
    user_id: Optional[int],
    page: int,
    limit: int
):
    """Unified property search with comprehensive filtering and geospatial optimization."""
    logger.info(f"Searching properties for user {user_id}, page {page}, limit {limit}")
    
    try:
        skip = (page - 1) * limit
        
        # Base query with eager loading
        query = select(Property).options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity)
        )
        count_query = select(func.count(Property.id))
        
        # Build base conditions
        conditions = []
        
        # Always filter by availability unless explicitly requested
        if not filters.include_unavailable:
            conditions.append(Property.is_available == True)
        
        # Location-based search
        user_location = None
        distance = None
        if filters.latitude and filters.longitude and filters.radius_km:
            logger.debug(f"Adding location filter: {filters.latitude}, {filters.longitude}, radius: {filters.radius_km}km")
            
            # Create a point from the user's location, ensuring SRID is set
            user_location = func.ST_SetSRID(func.ST_MakePoint(filters.longitude, filters.latitude), 4326)

            # Use ST_DWithin for efficient, index-based distance filtering.
            # ST_DWithin takes distance in meters.
            radius_m = filters.radius_km * 1000
            conditions.append(func.ST_DWithin(Property.location, user_location, radius_m))

            # Calculate distance for ordering and display, converting from meters to km.
            distance = func.ST_Distance(Property.location, user_location) / 1000
            query = query.add_columns(distance.label('distance_km'))
        
        # Text search using PostgreSQL full-text search with GIN index
        search_query_obj = None
        if filters.search_query:
            logger.debug(f"Adding full-text search filter: {filters.search_query}")
            
            # Use PostgreSQL full-text search with the indexed __ts_vector__ column
            # plainto_tsquery handles normalization and is safer for user input than to_tsquery
            search_query_obj = func.plainto_tsquery('english', filters.search_query)
            # Use text() to properly reference the ts_vector column
            conditions.append(text("properties.__ts_vector__ @@ plainto_tsquery('english', :search_query)").params(search_query=filters.search_query))
        
        # Property type filter - handle list of property types
        if filters.property_type:
            logger.debug(f"Adding property type filter: {filters.property_type}")
            if isinstance(filters.property_type, list) and len(filters.property_type) > 0:
                conditions.append(Property.property_type.in_(filters.property_type))
            elif not isinstance(filters.property_type, list):
                conditions.append(Property.property_type == filters.property_type)
        
        # Purpose filter
        if filters.purpose:
            logger.debug(f"Adding purpose filter: {filters.purpose}")
            conditions.append(Property.purpose == filters.purpose)
        
        # Price range filters
        if filters.price_min is not None:
            logger.debug(f"Adding min price filter: {filters.price_min}")
            conditions.append(Property.base_price >= filters.price_min)
        if filters.price_max is not None:
            logger.debug(f"Adding max price filter: {filters.price_max}")
            conditions.append(Property.base_price <= filters.price_max)
        
        # Bedroom filters
        if filters.bedrooms_min is not None:
            logger.debug(f"Adding min bedrooms filter: {filters.bedrooms_min}")
            conditions.append(Property.bedrooms >= filters.bedrooms_min)
        if filters.bedrooms_max is not None:
            logger.debug(f"Adding max bedrooms filter: {filters.bedrooms_max}")
            conditions.append(Property.bedrooms <= filters.bedrooms_max)
        
        # Bathroom filters
        if filters.bathrooms_min is not None:
            logger.debug(f"Adding min bathrooms filter: {filters.bathrooms_min}")
            conditions.append(Property.bathrooms >= filters.bathrooms_min)
        if filters.bathrooms_max is not None:
            logger.debug(f"Adding max bathrooms filter: {filters.bathrooms_max}")
            conditions.append(Property.bathrooms <= filters.bathrooms_max)
        
        # Area filters
        if filters.area_min is not None:
            logger.debug(f"Adding min area filter: {filters.area_min}")
            conditions.append(Property.area_sqft >= filters.area_min)
        if filters.area_max is not None:
            logger.debug(f"Adding max area filter: {filters.area_max}")
            conditions.append(Property.area_sqft <= filters.area_max)
        
        # Location filters
        if filters.city:
            logger.debug(f"Adding city filter: {filters.city}")
            conditions.append(Property.city.ilike(f"%{filters.city}%"))
        if filters.locality:
            logger.debug(f"Adding locality filter: {filters.locality}")
            conditions.append(Property.locality.ilike(f"%{filters.locality}%"))
        if filters.pincode:
            logger.debug(f"Adding pincode filter: {filters.pincode}")
            conditions.append(Property.pincode == filters.pincode)
        
        # Additional filters
        if filters.parking_spaces_min is not None:
            logger.debug(f"Adding min parking spaces filter: {filters.parking_spaces_min}")
            conditions.append(Property.parking_spaces >= filters.parking_spaces_min)
        
        if filters.floor_number_min is not None:
            logger.debug(f"Adding min floor number filter: {filters.floor_number_min}")
            conditions.append(Property.floor_number >= filters.floor_number_min)
        if filters.floor_number_max is not None:
            logger.debug(f"Adding max floor number filter: {filters.floor_number_max}")
            conditions.append(Property.floor_number <= filters.floor_number_max)
        
        if filters.age_max is not None:
            logger.debug(f"Adding max age filter: {filters.age_max}")
            conditions.append(Property.age_of_property <= filters.age_max)
        
        # Amenities filter
        if filters.amenities:
            logger.debug(f"Adding amenities filter: {filters.amenities}")
            # Join with PropertyAmenity and Amenity tables
            
            # Convert amenity names to IDs if needed
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
                # Subquery to find properties with all required amenities
                amenity_subquery = (
                    select(PropertyAmenity.property_id)
                    .where(PropertyAmenity.amenity_id.in_(amenity_ids))
                    .group_by(PropertyAmenity.property_id)
                    .having(func.count(PropertyAmenity.amenity_id) >= len(amenity_ids))
                )
                conditions.append(Property.id.in_(amenity_subquery))
        
        # Features filter - TODO: Implement proper JSON filtering once schema is clarified
        if filters.features:
            logger.debug(f"Features filter requested but not yet implemented: {filters.features}")
            # Features are stored as JSON dict, need to determine proper filtering logic
            # For now, skip this filter to avoid errors
            pass
        
        # Short stay filters
        if filters.guests is not None:
            logger.debug(f"Adding max occupancy filter for guests: {filters.guests}")
            conditions.append(Property.max_occupancy >= filters.guests)
        
        # TODO: Implement check-in/check-out date availability filtering
        # This would require checking against booking calendar
        
        # Exclude properties already swiped by the user if authenticated
        if user_id:
            from app.models.models import UserSwipe
            swiped_subquery = select(UserSwipe.property_id).where(UserSwipe.user_id == user_id)
            conditions.append(~Property.id.in_(swiped_subquery))
        
        # Apply all conditions
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))
        
        # Apply sorting
        sort_by = filters.sort_by or SortBy.distance
        
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
        elif sort_by == SortBy.relevance and search_query_obj is not None:
            # Sort by text search relevance using ts_rank
            # Create a simple ranking expression for ordering
            query = query.order_by(text("ts_rank(properties.__ts_vector__, plainto_tsquery('english', :search_query)) DESC").params(search_query=filters.search_query))
        else:
            # Default sorting
            query = query.order_by(Property.created_at.desc())
        
        # Add pagination
        query = query.offset(skip).limit(limit)
        
        # Execute queries
        result = await db.execute(query)
        count_result = await db.execute(count_query)
        
        # Handle results - check if we have additional columns (distance)
        if distance is not None:
            rows = result.all()
            properties = [row[0] for row in rows]  # First column is the Property object
            
            # Additional computed columns (distance_km) can be extracted here if needed
            # For now, we just extract the property objects
        else:
            properties = result.scalars().all()
        
        total_count = count_result.scalar()
        
        logger.info(f"Found {len(properties)} properties out of {total_count} total")
        
        from app.schemas.property import Property as PropertySchema
        property_list = [PropertySchema.model_validate(prop) for prop in properties]
        
        # Calculate total pages
        total_pages = (total_count + limit - 1) // limit
        
        return {
            "items": property_list,
            "total": total_count,
            "total_pages": total_pages
        }
    except Exception as e:
        logger.error(f"Failed to search properties: {str(e)}", exc_info=True)
        raise

async def get_property_recommendations(
    db: AsyncSession,
    user_id: Optional[int],
    limit: int = 10
):
    """Get property recommendations for a user"""
    logger.info(f"Getting property recommendations for user {user_id}, limit: {limit}")
    
    try:
        # Simple recommendation: get available properties
        # TODO: Implement proper recommendation algorithm based on user preferences
        query = select(Property).options(selectinload(Property.images)).where(
            Property.is_available == True
        ).limit(limit)
        
        result = await db.execute(query)
        properties = result.scalars().all()
        
        logger.info(f"Found {len(properties)} recommended properties for user {user_id}")
        
        from app.schemas.property import Property as PropertySchema
        return [PropertySchema.model_validate(prop) for prop in properties]
    except Exception as e:
        logger.error(f"Failed to get recommendations for user {user_id}: {str(e)}", exc_info=True)
        raise

async def increment_property_view_count(db: AsyncSession, property_id: int):
    """Increment view count for a property"""
    logger.debug(f"Incrementing view count for property {property_id}")
    
    try:
        # Update view count
        stmt = update(Property).where(Property.id == property_id).values(
            view_count=Property.view_count + 1
        )
        
        result = await db.execute(stmt)
        await db.flush()
        
        if result.rowcount > 0:
            logger.debug(f"View count incremented for property {property_id}")
        else:
            logger.warning(f"Property {property_id} not found for view count increment")
        
        return result.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to increment view count for property {property_id}: {str(e)}", exc_info=True)
        raise