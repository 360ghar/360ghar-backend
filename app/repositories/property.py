from typing import List, Optional, Dict, Any
import math
from datetime import datetime
from supabase import Client
from app.db.base import BaseRepository
from app.db.types import PropertyDB, PropertyImageDB, PaginatedResponse
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyFilter, PropertyInterest, UnifiedPropertyFilter, SortBy
from app.core.supabase_client import execute_rpc, build_filters, build_pagination, build_sorting
from app.core.logging import get_logger
import anyio

logger = get_logger(__name__)

class PropertyRepository(BaseRepository):
    """Repository for property-related database operations using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "properties")
    
    async def get_with_images(self, property_id: int) -> Optional[PropertyDB]:
        """Get property with all images loaded"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select("*, property_images(*)").eq("id", property_id).limit(1).execute()
            )
            if not result.data:
                return None
            item = dict(result.data[0])
            # Normalize relation key to match schema
            if "property_images" in item and "images" not in item:
                item["images"] = item.pop("property_images")
            # Apply enum normalization
            return self._normalize_enum_response(item)
        except Exception as e:
            logger.error(f"Failed to get property {property_id} with images: {str(e)}")
            raise
    
    async def get_nearby_properties(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        user_id: Optional[int] = None,
        page: int = 1,
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get properties within a radius using database function"""
        try:
            params = {
                "p_latitude": latitude,
                "p_longitude": longitude,
                "p_radius_km": radius_km,
                "p_user_id": user_id,
                "p_limit": limit,
                "p_offset": (page - 1) * limit
            }
            
            result = await execute_rpc(self.client, "get_nearby_properties", params)

            # Count total for pagination
            count_params = {
                "p_latitude": latitude,
                "p_longitude": longitude,
                "p_radius_km": radius_km,
                "p_user_id": user_id,
                "p_limit": 10000,  # Large number to get total count
                "p_offset": 0
            }

            count_result = await execute_rpc(self.client, "get_nearby_properties", count_params)
            total = len(count_result) if count_result else 0

            # Apply enum normalization to RPC results
            normalized_items = [self._normalize_enum_response(item) for item in (result or [])]
            
            return {
                "items": normalized_items,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit
            }
        except Exception as e:
            logger.error(f"Failed to get nearby properties RPC: {str(e)}")
            # Return empty result with helpful error information
            logger.warning("get_nearby_properties RPC function may not be deployed to Supabase")
            return {
                "items": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "total_pages": 0,
                "error": "Location-based search temporarily unavailable"
            }
    
    async def get_recommendations(
        self,
        user_id: int,
        limit: int = 10
    ) -> List[PropertyDB]:
        """Get property recommendations using database function"""
        try:
            params = {
                "p_user_id": user_id,
                "p_limit": limit
            }
            
            result = await execute_rpc(self.client, "get_property_recommendations", params)
            # Apply enum normalization to RPC results
            return [self._normalize_enum_response(item) for item in (result or [])]
        except Exception as e:
            logger.error(f"Failed to get recommendations for user {user_id}: {str(e)}")
            logger.warning("get_property_recommendations RPC function may not be deployed to Supabase")
            return []
    
    async def create_property(self, property_data: PropertyCreate) -> PropertyDB:
        """Create a new property"""
        data = property_data.dict(exclude_unset=True)
        return await self.create(data)
    
    async def update_property(self, property_id: int, property_update: PropertyUpdate) -> Optional[PropertyDB]:
        """Update property"""
        data = property_update.dict(exclude_unset=True)
        return await self.update(property_id, data)
    
    async def delete_property(self, property_id: int) -> bool:
        """Delete property"""
        return await self.delete(property_id)
    
    async def increment_view_count(self, property_id: int) -> None:
        """Increment property view count using database function"""
        try:
            # Try RPC first (if available)
            await execute_rpc(self.client, "increment_property_view_count", {"p_property_id": property_id})
        except Exception as e:
            logger.error(f"Failed to increment view count via RPC for property {property_id}: {str(e)}")
            logger.warning("increment_property_view_count RPC function may not be deployed to Supabase")
            # View count increment is not critical, so we can continue silently
    
    
    async def search_properties(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Search properties with text query and filters"""
        try:
            def build_search_query():
                # Use full-text search
                search_query = self.table.select("*", count="exact")
                
                if query:
                    # Use PostgreSQL full-text search
                    search_query = search_query.text_search("search_keywords", query, config="english")
                
                # Apply additional filters
                if filters:
                    search_query = build_filters(search_query, filters)
                
                # Apply pagination
                search_query = build_pagination(search_query, page, limit)
                
                return search_query.execute()
            
            result = await anyio.to_thread.run_sync(build_search_query)
            
            # Apply enum normalization
            normalized_items = [self._normalize_enum_response(item) for item in (result.data or [])]
            
            return {
                "items": normalized_items,
                "total": result.count or 0,
                "page": page,
                "limit": limit,
                "total_pages": ((result.count or 0) + limit - 1) // limit
            }
        except Exception as e:
            logger.error(f"Failed to search properties: {str(e)}")
            raise
    
    async def get_unified_properties(
        self,
        filters: UnifiedPropertyFilter,
        user_id: Optional[int] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get properties with unified filtering and sorting"""
        try:
            # Start with base query
            query = self.table.select("*", count="exact").eq("is_available", True)
            
            # Location-based filtering
            if filters.latitude and filters.longitude and filters.radius_km:
                return await self.get_nearby_properties(
                    filters.latitude,
                    filters.longitude,
                    filters.radius_km,
                    user_id,
                    page,
                    limit,
                    self._build_filter_dict(filters)
                )
            
            # Text search
            if filters.search_query:
                query = query.text_search("search_keywords", filters.search_query, config="english")
            
            # Property type filter
            if filters.property_type:
                if isinstance(filters.property_type, list):
                    normalized_types = [getattr(t, "value", t) for t in filters.property_type]
                    quoted = ",".join([f'"{str(v)}"' for v in normalized_types])
                    query = query.filter("property_type", "in", f"({quoted})")
                else:
                    prop_type_value = getattr(filters.property_type, "value", filters.property_type)
                    query = query.filter("property_type", "eq", str(prop_type_value))
            
            # Purpose filter
            if filters.purpose:
                purpose_value = getattr(filters.purpose, "value", filters.purpose)
                query = query.filter("purpose", "eq", str(purpose_value))
            
            # Price filters
            if filters.price_min:
                query = query.gte("base_price", filters.price_min)
            if filters.price_max:
                query = query.lte("base_price", filters.price_max)
            
            # Room filters
            if filters.bedrooms_min:
                query = query.gte("bedrooms", filters.bedrooms_min)
            if filters.bedrooms_max:
                query = query.lte("bedrooms", filters.bedrooms_max)
            if filters.bathrooms_min:
                query = query.gte("bathrooms", filters.bathrooms_min)
            if filters.bathrooms_max:
                query = query.lte("bathrooms", filters.bathrooms_max)
            
            # Area filters
            if filters.area_min:
                query = query.gte("area_sqft", filters.area_min)
            if filters.area_max:
                query = query.lte("area_sqft", filters.area_max)
            
            # Location filters
            if filters.city:
                query = query.eq("city", filters.city)
            if filters.locality:
                query = query.eq("locality", filters.locality)
            if filters.pincode:
                query = query.eq("pincode", filters.pincode)
            
            def build_unified_query():
                # Use a local variable to avoid Python closure assignment issues
                q = query
                # Exclude swiped properties if user is provided
                if user_id:
                    swiped_query = self.client.table("user_swipes").select("property_id").eq("user_id", user_id)
                    swiped_result = swiped_query.execute()
                    swiped_ids = [item["property_id"] for item in (swiped_result.data or [])]
                    
                    if swiped_ids:
                        q = q.not_.in_("id", swiped_ids)
                
                # Apply sorting
                if filters.sort_by:
                    if filters.sort_by == SortBy.price_low:
                        q = q.order("base_price")
                    elif filters.sort_by == SortBy.price_high:
                        q = q.order("base_price", desc=True)
                    elif filters.sort_by == SortBy.newest:
                        q = q.order("created_at", desc=True)
                    elif filters.sort_by == SortBy.popular:
                        q = q.order("like_count", desc=True)
                    else:  # relevance or distance - default to newest
                        q = q.order("created_at", desc=True)
                else:
                    q = q.order("created_at", desc=True)
                
                # Apply pagination
                q = build_pagination(q, page, limit)
                
                return q.execute()
            
            result = await anyio.to_thread.run_sync(build_unified_query)
            
            # Apply enum normalization
            normalized_items = [self._normalize_enum_response(item) for item in (result.data or [])]
            
            return {
                "items": normalized_items,
                "total": result.count or 0,
                "page": page,
                "limit": limit,
                "total_pages": ((result.count or 0) + limit - 1) // limit
            }
        except Exception as e:
            logger.error(f"Failed to get unified properties: {str(e)}")
            raise
    
    async def get_user_liked_properties(self, user_id: int) -> List[PropertyDB]:
        """Get properties liked by user"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.client
                    .table("user_swipes")
                    .select("property_id, properties(*)")
                    .eq("user_id", user_id)
                    .eq("is_liked", True)
                    .execute()
                )
            )
            
            # Apply enum normalization
            properties = [item["properties"] for item in (result.data or []) if item.get("properties")]
            return [self._normalize_enum_response(prop) for prop in properties]
        except Exception as e:
            logger.error(f"Failed to get liked properties for user {user_id}: {str(e)}")
            return []
    
    async def get_user_disliked_properties(self, user_id: int) -> List[PropertyDB]:
        """Get properties disliked by user"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.client
                    .table("user_swipes")
                    .select("property_id, properties(*)")
                    .eq("user_id", user_id)
                    .eq("is_liked", False)
                    .execute()
                )
            )
            
            # Apply enum normalization
            properties = [item["properties"] for item in (result.data or []) if item.get("properties")]
            return [self._normalize_enum_response(prop) for prop in properties]
        except Exception as e:
            logger.error(f"Failed to get disliked properties for user {user_id}: {str(e)}")
            return []
    
    async def get_properties_by_city(self, city: str) -> List[PropertyDB]:
        """Get properties by city"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select("*").eq("city", city).eq("is_available", True).execute()
            )
            # Apply enum normalization
            return [self._normalize_enum_response(item) for item in (result.data or [])]
        except Exception as e:
            logger.error(f"Failed to get properties by city {city}: {str(e)}")
            return []
    
    async def get_properties_by_locality(self, locality: str) -> List[PropertyDB]:
        """Get properties by locality"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select("*").eq("locality", locality).eq("is_available", True).execute()
            )
            # Apply enum normalization
            return [self._normalize_enum_response(item) for item in (result.data or [])]
        except Exception as e:
            logger.error(f"Failed to get properties by locality {locality}: {str(e)}")
            return []
    
    def _build_filter_dict(self, filters: UnifiedPropertyFilter) -> Dict[str, Any]:
        """Convert UnifiedPropertyFilter to dict for database filtering"""
        filter_dict = {}
        
        if filters.property_type:
            filter_dict["property_type"] = filters.property_type
        if filters.purpose:
            filter_dict["purpose"] = filters.purpose
        if filters.city:
            filter_dict["city"] = filters.city
        if filters.locality:
            filter_dict["locality"] = filters.locality
        if filters.pincode:
            filter_dict["pincode"] = filters.pincode
        
        # Price range
        if filters.price_min or filters.price_max:
            price_range = {}
            if filters.price_min:
                price_range["min"] = filters.price_min
            if filters.price_max:
                price_range["max"] = filters.price_max
            filter_dict["base_price"] = price_range
        
        # Room range
        if filters.bedrooms_min or filters.bedrooms_max:
            bedroom_range = {}
            if filters.bedrooms_min:
                bedroom_range["min"] = filters.bedrooms_min
            if filters.bedrooms_max:
                bedroom_range["max"] = filters.bedrooms_max
            filter_dict["bedrooms"] = bedroom_range
        
        if filters.bathrooms_min or filters.bathrooms_max:
            bathroom_range = {}
            if filters.bathrooms_min:
                bathroom_range["min"] = filters.bathrooms_min
            if filters.bathrooms_max:
                bathroom_range["max"] = filters.bathrooms_max
            filter_dict["bathrooms"] = bathroom_range
        
        # Area range
        if filters.area_min or filters.area_max:
            area_range = {}
            if filters.area_min:
                area_range["min"] = filters.area_min
            if filters.area_max:
                area_range["max"] = filters.area_max
            filter_dict["area_sqft"] = area_range
        
        return filter_dict