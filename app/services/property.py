from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, update, case
from sqlalchemy.orm import selectinload, joinedload
from typing import List, Optional, Dict, Any
from app.models.models import Property, PropertyImage, UserSwipe
from app.schemas.property import PropertyCreate, PropertyUpdate, UnifiedPropertyFilter
from app.core.logging import get_logger

logger = get_logger(__name__)

async def create_property(db: AsyncSession, property_data: PropertyCreate, owner_id: int):
    """Create new property"""
    logger.info(f"Creating property for owner {owner_id}, type: {property_data.property_type}")
    
    try:
        property_dict = property_data.model_dump(exclude_unset=True)
        property_dict["owner_id"] = owner_id
        db_property = Property(**property_dict)
        db.add(db_property)
        await db.flush()
        await db.refresh(db_property)
        
        logger.info(f"Property created successfully with ID {db_property.id}")
        return db_property
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
    """Unified property search"""
    logger.info(f"Searching properties for user {user_id}, page {page}, limit {limit}")
    
    try:
        skip = (page - 1) * limit
        
        # Base query
        query = select(Property).options(selectinload(Property.images))
        count_query = select(func.count(Property.id))
        
        # Build conditions
        conditions = [Property.is_available == True]
        
        # Location-based search
        if filters.latitude and filters.longitude and filters.radius_km:
            logger.debug(f"Adding location filter: {filters.latitude}, {filters.longitude}, radius: {filters.radius_km}km")
            # Haversine formula in PostgreSQL
            distance = func.acos(
                func.sin(func.radians(filters.latitude)) * func.sin(func.radians(Property.latitude)) +
                func.cos(func.radians(filters.latitude)) * func.cos(func.radians(Property.latitude)) *
                func.cos(func.radians(Property.longitude) - func.radians(filters.longitude))
            ) * 6371
            
            conditions.append(distance <= filters.radius_km)
            query = query.add_columns(distance.label('distance_km'))
        
        # Text search
        if filters.search_query:
            logger.debug(f"Adding text search filter: {filters.search_query}")
            search_term = f"%{filters.search_query}%"
            text_conditions = or_(
                Property.title.ilike(search_term),
                Property.description.ilike(search_term),
                Property.address.ilike(search_term),
                Property.city.ilike(search_term)
            )
            conditions.append(text_conditions)
        
        # Property type filter
        if filters.property_type:
            logger.debug(f"Adding property type filter: {filters.property_type}")
            conditions.append(Property.property_type == filters.property_type)
        
        # Price range filter
        if filters.price_min:
            logger.debug(f"Adding min price filter: {filters.price_min}")
            conditions.append(Property.base_price >= filters.price_min)
        if filters.price_max:
            logger.debug(f"Adding max price filter: {filters.price_max}")
            conditions.append(Property.base_price <= filters.price_max)
        
        # Apply all conditions
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))
        
        # Add pagination
        query = query.offset(skip).limit(limit)
        
        # Execute queries
        result = await db.execute(query)
        count_result = await db.execute(count_query)
        
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