from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.models.user import User
from app.schemas.user import UserUpdate, User as UserSchema, UserPreferences, LocationUpdate
from app.schemas.common import MessageResponse
from app.services.user import update_user, update_user_preferences, update_user_location

router = APIRouter()

@router.get("/profile", response_model=UserSchema)
def get_user_profile(current_user: User = Depends(get_current_active_user)):
    return current_user

@router.put("/profile", response_model=UserSchema)
def update_user_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    return update_user(db, current_user.id, user_update)

@router.put("/preferences", response_model=MessageResponse)
def update_preferences(
    preferences: UserPreferences,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    update_user_preferences(db, current_user.id, preferences.dict())
    return MessageResponse(message="Preferences updated successfully")

@router.put("/location", response_model=MessageResponse)
def update_location(
    location: LocationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    update_user_location(db, current_user.id, location.latitude, location.longitude)
    return MessageResponse(message="Location updated successfully")

@router.get("/search-history")
def get_search_history(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from app.services.analytics import get_user_search_history
    return get_user_search_history(db, current_user.id)

@router.delete("/search-history", response_model=MessageResponse)
def clear_search_history(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from app.services.analytics import clear_user_search_history
    clear_user_search_history(db, current_user.id)
    return MessageResponse(message="Search history cleared successfully")

@router.get("/liked-properties")
def get_liked_properties(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from app.services.property import get_user_liked_properties
    return get_user_liked_properties(db, current_user.id)

@router.get("/disliked-properties")
def get_disliked_properties(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from app.services.property import get_user_disliked_properties
    return get_user_disliked_properties(db, current_user.id)