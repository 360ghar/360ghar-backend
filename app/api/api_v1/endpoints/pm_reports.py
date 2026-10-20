from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_cached_active_user
from app.core.database import get_db
from app.core.db_resilience import raise_read_service_unavailable
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_report import (
    ExpenseReport,
    IncomeReport,
    MaintenanceReport,
    OccupancyReport,
    PnLReport,
    RentRollItem,
)
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.pm_reports import (
    expense_report,
    income_report,
    maintenance_report,
    occupancy_report,
    pnl_report,
    rent_roll_report,
)

router = APIRouter()


@router.get("/rent-roll", response_model=CursorPage[RentRollItem], summary="Get rent roll report")
async def rent_roll(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get rent roll report."""
    filters = {"owner_id": owner_id}
    try:
        rows, next_payload, total = await rent_roll_report(
            db,
            actor=current_user,  # type: ignore[arg-type]
            owner_id=owner_id,
            cursor_payload=page.decoded(filters),
            limit=page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(
            rows, limit=page.limit, next_payload=next_payload, total=total, filters=filters
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_report_rent_roll",
            detail="Rent roll report is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/income", response_model=IncomeReport, summary="Get income report")
async def income(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: date | None = Query(None, description="First day, inclusive (UTC)"),
    end: date | None = Query(None, description="Last day, inclusive (UTC)"),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get income report."""
    try:
        return await income_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_report_income",
            detail="Income report is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/expenses", response_model=ExpenseReport, summary="Get expense report")
async def expenses(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get expense report."""
    try:
        return await expense_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_report_expenses",
            detail="Expense report is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/pnl", response_model=PnLReport, summary="Get profit & loss report")
async def pnl(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get profit & loss report."""
    try:
        return await pnl_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_report_pnl",
            detail="Profit and loss report is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/occupancy", response_model=OccupancyReport, summary="Get occupancy report")
async def occupancy(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get occupancy report."""
    try:
        return await occupancy_report(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_report_occupancy",
            detail="Occupancy report is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/maintenance", response_model=MaintenanceReport, summary="Get maintenance report")
async def maintenance(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get maintenance report."""
    try:
        return await maintenance_report(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="pm_report_maintenance",
            detail="Maintenance report is temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise
