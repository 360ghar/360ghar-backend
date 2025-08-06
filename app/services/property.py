from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.repositories.property import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyFilter, PropertyInterest, UnifiedPropertyFilter

async def create_property(db: AsyncSession, property_data: PropertyCreate):
    property_repo = PropertyRepository(db)
    return await property_repo.create_property(property_data)

async def get_property(db: AsyncSession, property_id: int):
    property_repo = PropertyRepository(db)
    return await property_repo.get_with_images(property_id)

async def get_properties(db: AsyncSession, filters: PropertyFilter, user_id: int, page: int = 1, limit: int = 20):
    property_repo = PropertyRepository(db)
    return await property_repo.get_properties(filters, user_id, page, limit)

async def get_properties_for_discovery(db: AsyncSession, user_id: Optional[int], limit: int = 10):
    property_repo = PropertyRepository(db)
    return await property_repo.get_properties_for_discovery(user_id, limit)

async def get_properties_nearby(db: AsyncSession, latitude: float, longitude: float, radius_km: int, user_id: int, page: int = 1, limit: int = 20):
    property_repo = PropertyRepository(db)
    return await property_repo.get_nearby_properties(latitude, longitude, radius_km, user_id, skip=(page-1)*limit, limit=limit)

async def get_property_recommendations(db: AsyncSession, user_id: Optional[int], limit: int = 10):
    property_repo = PropertyRepository(db)
    return await property_repo.get_property_recommendations_enhanced(user_id, limit)

async def update_property(db: AsyncSession, property_id: int, property_update: PropertyUpdate):
    property_repo = PropertyRepository(db)
    return await property_repo.update_property(property_id, property_update)

async def delete_property(db: AsyncSession, property_id: int):
    property_repo = PropertyRepository(db)
    return await property_repo.delete_property(property_id)

async def get_user_liked_properties(db: AsyncSession, user_id: int):
    property_repo = PropertyRepository(db)
    return await property_repo.get_user_liked_properties(user_id)

async def get_user_disliked_properties(db: AsyncSession, user_id: int):
    property_repo = PropertyRepository(db)
    return await property_repo.get_user_disliked_properties(user_id)

async def get_properties_by_city(db: AsyncSession, city: str):
    property_repo = PropertyRepository(db)
    return await property_repo.get_properties_by_city(city)

async def get_properties_by_locality(db: AsyncSession, locality: str):
    property_repo = PropertyRepository(db)
    return await property_repo.get_properties_by_locality(locality)

async def record_property_interest(db: AsyncSession, user_id: int, interest: PropertyInterest):
    property_repo = PropertyRepository(db)
    return await property_repo.record_property_interest(user_id, interest)

async def increment_property_view_count(db: AsyncSession, property_id: int):
    property_repo = PropertyRepository(db)
    return await property_repo.increment_view_count_direct(property_id)

async def get_unified_properties(db: AsyncSession, filters: UnifiedPropertyFilter, user_id: int, page: int = 1, limit: int = 20):
    property_repo = PropertyRepository(db)
    return await property_repo.get_unified_properties(filters, user_id, page, limit)

async def get_unified_properties_optimized(
    db: AsyncSession, 
    filters: UnifiedPropertyFilter, 
    user_id: int, 
    page: int = 1, 
    limit: int = 20
):
    """Optimized property retrieval with caching"""
    property_repo = PropertyRepository(db)
    return await property_repo.get_unified_properties_optimized(filters, user_id, page, limit)