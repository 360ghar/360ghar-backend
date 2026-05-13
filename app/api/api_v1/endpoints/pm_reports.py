from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
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


@router.get("/rent-roll", response_model=list[RentRollItem])
async def rent_roll(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await rent_roll_report(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]


@router.get("/income", response_model=IncomeReport)
async def income(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await income_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]


@router.get("/expenses", response_model=ExpenseReport)
async def expenses(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await expense_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]


@router.get("/pnl", response_model=PnLReport)
async def pnl(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    start: date | None = Query(None),
    end: date | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await pnl_report(db, actor=current_user, owner_id=owner_id, start=start, end=end)  # type: ignore[arg-type]


@router.get("/occupancy", response_model=OccupancyReport)
async def occupancy(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await occupancy_report(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]


@router.get("/maintenance", response_model=MaintenanceReport)
async def maintenance(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await maintenance_report(db, actor=current_user, owner_id=owner_id)  # type: ignore[arg-type]

