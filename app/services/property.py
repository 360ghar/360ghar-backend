from supabase import Client
from typing import List, Optional, Dict, Any
from app.repositories.property import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyFilter, PropertyInterest, UnifiedPropertyFilter, SortBy
from app.schemas.common import PaginatedResponse

async def create_property(supabase: Client, property_data: PropertyCreate):
    property_repo = PropertyRepository(supabase)
    return await property_repo.create_property(property_data)

async def get_property(supabase: Client, property_id: int):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_with_images(property_id)


async def get_properties_nearby(supabase: Client, latitude: float, longitude: float, radius_km: float, user_id: Optional[int] = None, page: int = 1, limit: int = 20):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_nearby_properties(latitude, longitude, radius_km, user_id, page, limit)

async def get_property_recommendations(supabase: Client, user_id: int, limit: int = 10):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_recommendations(user_id, limit)

async def update_property(supabase: Client, property_id: int, property_update: PropertyUpdate):
    property_repo = PropertyRepository(supabase)
    return await property_repo.update_property(property_id, property_update)

async def delete_property(supabase: Client, property_id: int):
    property_repo = PropertyRepository(supabase)
    return await property_repo.delete_property(property_id)

async def get_user_liked_properties(supabase: Client, user_id: int):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_user_liked_properties(user_id)

async def get_user_disliked_properties(supabase: Client, user_id: int):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_user_disliked_properties(user_id)

async def get_properties_by_city(supabase: Client, city: str):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_properties_by_city(city)

async def get_properties_by_locality(supabase: Client, locality: str):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_properties_by_locality(locality)

async def increment_property_view_count(supabase: Client, property_id: int):
    property_repo = PropertyRepository(supabase)
    return await property_repo.increment_view_count(property_id)

async def get_unified_properties(supabase: Client, filters: UnifiedPropertyFilter, user_id: Optional[int] = None, page: int = 1, limit: int = 20):
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_unified_properties(filters, user_id, page, limit)

async def get_unified_properties_optimized(
    supabase: Client, 
    filters: UnifiedPropertyFilter, 
    user_id: Optional[int] = None, 
    page: int = 1, 
    limit: int = 20
):
    """Optimized property retrieval - uses same method as unified for now"""
    property_repo = PropertyRepository(supabase)
    return await property_repo.get_unified_properties(filters, user_id, page, limit)

async def search_properties(supabase: Client, query: str, filters: Optional[Dict[str, Any]] = None, page: int = 1, limit: int = 20):
    """Search properties with text query"""
    property_repo = PropertyRepository(supabase)
    return await property_repo.search_properties(query, filters, page, limit)