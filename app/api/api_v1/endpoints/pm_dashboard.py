from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.schemas.pm_dashboard import ActivityItem, DashboardOverview
from app.schemas.user import User as UserSchema
from app.services.pm_dashboard import get_dashboard_overview, get_recent_activity

router = APIRouter()


@router.get("/overview", response_model=DashboardOverview)
async def dashboard_overview(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    data = await get_dashboard_overview(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]
    return data


@router.get("/activity", response_model=list[ActivityItem])
async def dashboard_activity(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    limit: int = Query(20, ge=1, le=100),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    items = await get_recent_activity(db, actor=current_user, owner_id=owner_id, limit=limit)  # type: ignore[arg-type]
    return items

