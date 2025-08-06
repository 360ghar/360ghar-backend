from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.models.user import User
from app.schemas.property import PropertySwipe
from app.schemas.common import MessageResponse
from app.services.swipe import record_swipe, get_swipe_history

router = APIRouter()

@router.post("/", response_model=MessageResponse)
async def swipe_property(
    swipe: PropertySwipe,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    await record_swipe(db, current_user.id, swipe)
    
    action = "liked" if swipe.is_liked else "passed"
    return MessageResponse(message=f"Property {action} successfully")

@router.get("/history")
async def get_user_swipe_history(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 100
):
    return await get_swipe_history(db, current_user.id, limit)

@router.get("/stats")
async def get_swipe_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.analytics import get_user_swipe_stats
    return await get_user_swipe_stats(db, current_user.id)

@router.post("/undo", response_model=MessageResponse)
async def undo_last_swipe(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.swipe import undo_last_swipe
    success = await undo_last_swipe(db, current_user.id)
    
    if not success:
        raise HTTPException(status_code=400, detail="No recent swipe to undo")
    
    return MessageResponse(message="Last swipe undone successfully")