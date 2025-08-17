from supabase import Client
from typing import List, Optional, Dict, Any
from app.repositories.user_interaction import UserInteractionRepository
from app.schemas.property import PropertySwipe

async def record_swipe(supabase: Client, user_id: int, swipe_data: PropertySwipe):
    """Record a user swipe"""
    repo = UserInteractionRepository(supabase)
    return await repo.record_swipe(user_id, swipe_data)

async def get_swipe_history(supabase: Client, user_id: int, page: int = 1, limit: int = 20, is_liked: Optional[bool] = None):
    """Get user's swipe history"""
    repo = UserInteractionRepository(supabase)
    return await repo.get_swipe_history(user_id, page, limit, is_liked)

async def get_user_liked_properties(supabase: Client, user_id: int, limit: int = 50):
    """Get properties liked by user"""
    repo = UserInteractionRepository(supabase)
    return await repo.get_user_liked_properties(user_id, limit)

async def get_swiped_property_ids(supabase: Client, user_id: int):
    """Get list of property IDs user has swiped on"""
    repo = UserInteractionRepository(supabase)
    return await repo.get_swiped_property_ids(user_id)

async def undo_last_swipe(supabase: Client, user_id: int):
    """Undo the last swipe for a user"""
    repo = UserInteractionRepository(supabase)
    return await repo.undo_last_swipe(user_id)

async def toggle_swipe(supabase: Client, swipe_id: int, user_id: int):
    """Toggle the like status of an existing swipe"""
    repo = UserInteractionRepository(supabase)
    return await repo.toggle_swipe(swipe_id, user_id)

async def get_swipe_stats(supabase: Client, user_id: int):
    """Get user swipe statistics"""
    repo = UserInteractionRepository(supabase)
    return await repo.get_swipe_stats(user_id)