from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_report import (
    ExpenseReport,
    IncomeReport,
    MaintenanceReport,
    OccupancyReport,
    PnLReport,
    RentRollItem,
)
from app.schemas.user import User as UserSchema
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
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get rent roll report."""
    rows, next_payload, total = await rent_roll_report(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)


@router.get("/income", response_model=IncomeReport, summary="Get income report")
async def income(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get income report."""
    return await income_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]


@router.get("/expenses", response_model=ExpenseReport, summary="Get expense report")
async def expenses(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get expense report."""
    return await expense_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]


@router.get("/pnl", response_model=PnLReport, summary="Get profit & loss report")
async def pnl(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get profit & loss report."""
    return await pnl_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]


@router.get("/occupancy", response_model=OccupancyReport, summary="Get occupancy report")
async def occupancy(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get occupancy report."""
    return await occupancy_report(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]


@router.get("/maintenance", response_model=MaintenanceReport, summary="Get maintenance report")
async def maintenance(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get maintenance report."""
    return await maintenance_report(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]

