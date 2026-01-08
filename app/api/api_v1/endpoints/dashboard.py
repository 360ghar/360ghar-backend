"""
Dashboard API Endpoints.

This module provides REST API endpoints for dashboard statistics
related to 360 virtual tours.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.tour import DashboardRealtimeStats, DashboardStats
from app.schemas.user import User as UserSchema
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get dashboard statistics for the current user.

    Returns aggregate stats including:
    - Total tours and published tours
    - Total views across all tours
    - Total scenes
    - Storage usage and limits
    """
    stats = await tour_service.get_dashboard_stats(
        db=db,
        user_id=current_user.id,
    )
    return stats


@router.get("/realtime", response_model=DashboardRealtimeStats)
async def get_dashboard_realtime_stats(
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """Get realtime analytics metrics for the current user's tours."""
    stats = await tour_service.get_dashboard_realtime_stats(
        db=db,
        user_id=current_user.id,
    )
    return stats
