from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.schemas.user import UserUpdate, User as UserSchema, UserPreferences, LocationUpdate
from app.schemas.common import MessageResponse
from app.services.user import update_user, update_user_preferences, update_user_location

router = APIRouter()

@router.get("/profile", response_model=UserSchema)
async def get_user_profile(current_user: UserSchema = Depends(get_current_active_user)):
    """Get current user profile"""
    return current_user

@router.put("/profile", response_model=UserSchema)
async def update_user_profile(
    user_update: UserUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user profile"""
    updated_user = await update_user(db, current_user.id, user_update)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

@router.put("/preferences", response_model=MessageResponse)
async def update_preferences(
    preferences: UserPreferences,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user preferences"""
    await update_user_preferences(db, current_user.id, preferences.dict())
    return MessageResponse(message="Preferences updated successfully")

@router.put("/location", response_model=MessageResponse)
async def update_location(
    location_update: LocationUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user's current location"""
    await update_user_location(
        db, 
        current_user.id, 
        location_update.latitude, 
        location_update.longitude
    )
    return MessageResponse(message="Location updated successfully")

