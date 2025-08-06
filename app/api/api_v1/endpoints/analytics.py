from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.models.user import User
from app.schemas.common import AnalyticsData, MessageResponse
from app.services.analytics import (
    record_user_event, get_user_analytics, get_user_search_history,
    get_user_swipe_stats, record_property_view
)

router = APIRouter()

@router.post("/event", response_model=MessageResponse)
async def track_user_event(
    event: AnalyticsData,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    event.user_id = current_user.id
    await record_user_event(db, event)
    return MessageResponse(message="Event tracked successfully")

@router.get("/dashboard")
async def get_user_analytics_dashboard(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_user_analytics(db, current_user.id)

@router.get("/search-history")
async def get_search_analytics(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_user_search_history(db, current_user.id)

@router.get("/swipe-stats")
async def get_swipe_analytics(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_user_swipe_stats(db, current_user.id)

@router.get("/property-views")
async def get_property_view_history(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.analytics import get_user_property_views
    return await get_user_property_views(db, current_user.id)

@router.get("/preferences-insights")
async def get_user_preferences_insights(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.analytics import analyze_user_preferences
    return await analyze_user_preferences(db, current_user.id)