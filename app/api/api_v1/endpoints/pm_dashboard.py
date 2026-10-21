from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_cached_active_user
from app.core.database import get_db
from app.core.db_resilience import raise_read_service_unavailable
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_dashboard import ActivityItem, DashboardOverview
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.pm_dashboard import get_dashboard_overview, get_recent_activity

router = APIRouter()


@router.get("/overview", response_model=DashboardOverview, summary="Get PM dashboard overview")
async def dashboard_overview(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get PM dashboard overview."""
    try:
        return await get_dashboard_overview(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_dashboard_overview",
            detail="PM dashboard overview is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get(
    "/activity", response_model=CursorPage[ActivityItem], summary="Get PM dashboard activity"
)
async def dashboard_activity(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get PM dashboard activity."""
    filters = {"owner_id": owner_id}
    try:
        items, next_payload, total = await get_recent_activity(
            db,
            actor=current_user,  # type: ignore[arg-type]
            owner_id=owner_id,
            cursor_payload=page.decoded(filters),
            limit=page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(
            [ActivityItem(**item) for item in items],
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_dashboard_activity",
            detail="PM dashboard activity is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise
