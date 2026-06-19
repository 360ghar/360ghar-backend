from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_dashboard import ActivityItem, DashboardOverview
from app.schemas.user import User as UserSchema
from app.services.pm_dashboard import get_dashboard_overview, get_recent_activity

router = APIRouter()


@router.get("/overview", response_model=DashboardOverview, summary="Get PM dashboard overview")
async def dashboard_overview(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get PM dashboard overview."""
    data = await get_dashboard_overview(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]
    return data


@router.get("/activity", response_model=CursorPage[ActivityItem], summary="Get PM dashboard activity")
async def dashboard_activity(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get PM dashboard activity."""
    items, next_payload, total = await get_recent_activity(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [ActivityItem(**item) for item in items],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )
