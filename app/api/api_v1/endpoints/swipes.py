from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.schemas.property import PropertySwipe, UnifiedPropertyFilter, UnifiedPropertyResponse, SortBy
from app.schemas.user import User as UserSchema
from app.models.enums import PropertyType, PropertyPurpose
from app.schemas.common import MessageResponse
from app.services.swipe import record_swipe, get_swipe_history, undo_last_swipe, get_swipe_stats, toggle_swipe
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.post("/", response_model=MessageResponse)
async def swipe_property(
    swipe: PropertySwipe,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Record a property swipe (like/dislike)"""
    await record_swipe(db, current_user.id, swipe)
    
    action = "liked" if swipe.is_liked else "passed"
    logger.debug("Property swipe recorded", extra={"user_id": current_user.id, "property_id": swipe.property_id, "action": action})
    return MessageResponse(message=f"Property {action} successfully")

@router.get("/")
async def get_user_swipe_history(
    # Filter options
    is_liked: Optional[bool] = Query(None, description="Filter by liked (true) or disliked (false)"),
    
    # Pagination
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's swipe history with property details"""
    result = await get_swipe_history(db, current_user.id, page, limit, is_liked)
    return result

@router.delete("/undo", response_model=MessageResponse)
async def undo_last_swipe_endpoint(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Undo the last swipe for the user"""
    undone_swipe = await undo_last_swipe(db, current_user.id)
    
    if not undone_swipe:
        raise HTTPException(status_code=404, detail="No swipes to undo")
    
    return MessageResponse(message="Last swipe undone successfully")

@router.put("/{swipe_id}/toggle", response_model=MessageResponse)
async def toggle_swipe_like(
    swipe_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Toggle the like status of an existing swipe"""
    result = await toggle_swipe(db, swipe_id, current_user.id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Swipe not found or does not belong to user")
    
    action = "liked" if result["new_status"] else "unliked"
    return MessageResponse(message=f"Property {action} successfully")

@router.get("/stats")
async def get_user_swipe_statistics(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's swipe statistics"""
    stats = await get_swipe_stats(db, current_user.id)
    return stats