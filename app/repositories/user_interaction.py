from typing import List, Optional, Dict, Any
from supabase import Client
from app.db.base import BaseRepository
from app.core.supabase_client import execute_rpc
from app.db.types import UserSwipeDB, UserFavoriteDB, UserSearchHistoryDB
from app.schemas.property import PropertySwipe
from app.schemas.common import PaginatedResponse
import anyio
from app.core.logging import get_logger

logger = get_logger(__name__)

class UserInteractionRepository(BaseRepository):
    """Repository for user interaction data (swipes, favorites, search history) using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "user_swipes")
    
    # Swipe operations
    async def record_swipe(self, user_id: int, swipe: PropertySwipe) -> bool:
        """Record a user swipe (like or pass) atomically with like count update"""
        try:
            # Try atomic RPC function first
            result = await execute_rpc(
                self.client,
                "record_swipe_with_like_count",
                {
                    "p_user_id": user_id,
                    "p_property_id": swipe.property_id,
                    "p_is_liked": swipe.is_liked,
                    "p_user_location_lat": swipe.user_location_lat,
                    "p_user_location_lng": swipe.user_location_lng,
                    "p_session_id": swipe.session_id
                }
            )
            return result is not None
        except Exception as e:
            logger.error(f"Failed to record swipe via RPC: {str(e)}")
            # Fallback to simple upsert (without atomic like count update)
            try:
                swipe_data = {
                    "user_id": user_id,
                    "property_id": swipe.property_id,
                    "is_liked": swipe.is_liked,
                    "user_location_lat": swipe.user_location_lat,
                    "user_location_lng": swipe.user_location_lng,
                    "session_id": swipe.session_id
                }
                await anyio.to_thread.run_sync(
                    lambda: (
                        self.table
                        .upsert(swipe_data, on_conflict="user_id,property_id")
                        .execute()
                    )
                )
                return True
            except Exception as fallback_e:
                logger.error(f"Fallback swipe recording failed: {str(fallback_e)}")
                return False
    
    async def get_swipe_history(
        self, 
        user_id: int, 
        page: int = 1, 
        limit: int = 20, 
        is_liked: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Get user's swipe history with property details"""
        try:
            filters = {"user_id": user_id}
            if is_liked is not None:
                filters["is_liked"] = is_liked
            
            result = await self.get_multi(
                filters=filters,
                select="*, properties(*)",
                page=page,
                limit=limit,
                sort_field="swipe_timestamp",
                sort_desc=True
            )
            
            return result
        except Exception as e:
            return {"items": [], "total": 0, "page": page, "limit": limit, "total_pages": 0}
    
    async def get_user_liked_properties(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get properties liked by user"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.client
                    .table("user_swipes")
                    .select("properties(*)")
                    .eq("user_id", user_id)
                    .eq("is_liked", True)
                    .order("swipe_timestamp", desc=True)
                    .limit(limit)
                    .execute()
                )
            )
            
            return [item["properties"] for item in (result.data or []) if item.get("properties")]
        except Exception as e:
            return []
    
    async def get_user_disliked_properties(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get properties disliked by user"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.client
                    .table("user_swipes")
                    .select("properties(*)")
                    .eq("user_id", user_id)
                    .eq("is_liked", False)
                    .order("swipe_timestamp", desc=True)
                    .limit(limit)
                    .execute()
                )
            )
            
            return [item["properties"] for item in (result.data or []) if item.get("properties")]
        except Exception as e:
            return []
    
    async def get_swiped_property_ids(self, user_id: int) -> List[int]:
        """Get list of property IDs that user has already swiped on"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("property_id")
                    .eq("user_id", user_id)
                    .execute()
                )
            )
            
            return [item["property_id"] for item in (result.data or [])]
        except Exception as e:
            return []
    
    async def undo_last_swipe(self, user_id: int) -> Optional[UserSwipeDB]:
        """Remove the last swipe for a user atomically with like count update"""
        try:
            # Try atomic RPC function first
            result = await execute_rpc(
                self.client,
                "undo_last_swipe_for_user",
                {"p_user_id": user_id}
            )
            
            if result and len(result) > 0:
                # Convert RPC result to UserSwipeDB format
                swipe_info = result[0]
                return {
                    "id": swipe_info.get("swipe_id"),
                    "user_id": user_id,
                    "property_id": swipe_info.get("property_id"),
                    "is_liked": swipe_info.get("was_liked"),
                    "swipe_timestamp": None,  # Not returned by RPC
                    "user_location_lat": None,
                    "user_location_lng": None,
                    "session_id": None,
                    "created_at": None,
                    "updated_at": None
                }
            return None
        except Exception as e:
            logger.error(f"Failed to undo swipe via RPC: {str(e)}")
            # Fallback to manual undo (without atomic like count update)
            try:
                result = await anyio.to_thread.run_sync(
                    lambda: (
                        self.table
                        .select("*")
                        .eq("user_id", user_id)
                        .order("swipe_timestamp", desc=True)
                        .limit(1)
                        .execute()
                    )
                )
                
                if not result.data:
                    return None
                
                last_swipe = result.data[0]
                await self.delete(last_swipe["id"])
                return last_swipe
            except Exception as fallback_e:
                logger.error(f"Fallback undo swipe failed: {str(fallback_e)}")
                return None
    
    async def toggle_swipe(self, swipe_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Toggle the like status of an existing swipe"""
        try:
            # First get the current swipe
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("*")
                    .eq("id", swipe_id)
                    .eq("user_id", user_id)
                    .limit(1)
                    .execute()
                )
            )
            
            if not result.data:
                return None
            
            current_swipe = result.data[0]
            new_like_status = not current_swipe["is_liked"]
            
            # Update the swipe
            update_result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .update({"is_liked": new_like_status})
                    .eq("id", swipe_id)
                    .eq("user_id", user_id)
                    .execute()
                )
            )
            
            if update_result.data:
                return {
                    "id": swipe_id,
                    "property_id": current_swipe["property_id"],
                    "previous_status": current_swipe["is_liked"],
                    "new_status": new_like_status
                }
            
            return None
        except Exception as e:
            logger.error(f"Failed to toggle swipe: {str(e)}")
            return None

    async def get_swipe_stats(self, user_id: int) -> Dict[str, Any]:
        """Get user swipe statistics"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.client.rpc("get_user_swipe_stats", {"p_user_id": user_id}).execute()
            )
            return result.data[0] if result.data else {
                "total_swipes": 0,
                "liked_count": 0,
                "disliked_count": 0,
                "like_percentage": 0.0
            }
        except Exception as e:
            return {
                "total_swipes": 0,
                "liked_count": 0,
                "disliked_count": 0,
                "like_percentage": 0.0
            }


class UserFavoriteRepository(BaseRepository):
    """Repository for user favorites using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "user_favorites")
    
    async def add_favorite(self, user_id: int, property_id: int, notes: Optional[str] = None) -> UserFavoriteDB:
        """Add property to favorites"""
        data = {
            "user_id": user_id,
            "property_id": property_id,
            "is_favorite": True,
            "notes": notes
        }
        return await self.upsert(data)
    
    async def remove_favorite(self, user_id: int, property_id: int) -> bool:
        """Remove property from favorites"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .delete()
                    .eq("user_id", user_id)
                    .eq("property_id", property_id)
                    .execute()
                )
            )
            return len(result.data or []) > 0
        except Exception:
            return False
    
    async def get_user_favorites(self, user_id: int, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """Get user's favorite properties"""
        return await self.get_multi(
            filters={"user_id": user_id, "is_favorite": True},
            select="*, properties(*)",
            page=page,
            limit=limit,
            sort_field="created_at",
            sort_desc=True
        )
    
    async def is_favorite(self, user_id: int, property_id: int) -> bool:
        """Check if property is in user's favorites"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("id")
                    .eq("user_id", user_id)
                    .eq("property_id", property_id)
                    .eq("is_favorite", True)
                    .limit(1)
                    .execute()
                )
            )
            return len(result.data or []) > 0
        except Exception:
            return False


class UserSearchHistoryRepository(BaseRepository):
    """Repository for user search history using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "user_search_history")
    
    async def record_search(
        self, 
        user_id: int, 
        search_data: Dict[str, Any]
    ) -> UserSearchHistoryDB:
        """Record a user search"""
        data = {
            "user_id": user_id,
            **search_data
        }
        return await self.create(data)
    
    async def get_user_search_history(
        self, 
        user_id: int, 
        page: int = 1, 
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get user's search history"""
        return await self.get_multi(
            filters={"user_id": user_id},
            page=page,
            limit=limit,
            sort_field="created_at",
            sort_desc=True
        )
    
    async def get_popular_searches(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most popular search queries"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("search_query, COUNT(*) as count")
                    .not_.is_("search_query", "null")
                    .order("count", desc=True)
                    .limit(limit)
                    .execute()
                )
            )
            
            return result.data or []
        except Exception:
            return []