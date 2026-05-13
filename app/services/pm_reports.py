from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeaseStatus
from app.models.pm_finance import Expense, RentPayment
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User
from app.services.pm_dashboard import _resolve_owner_scope


async def rent_roll_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
) -> list[dict[str, Any]]:
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    stmt = select(Property).where(Property.is_managed)
    if owner_ids is not None:
        stmt = stmt.where(Property.owner_id.in_(owner_ids))
    res = await db.execute(stmt)
    props = list(res.scalars().all())

    out: list[dict[str, Any]] = []
    for p in props:
        lease_stmt = (
            select(Lease)
            .where(Lease.property_id == p.id, Lease.status == LeaseStatus.active)
            .order_by(Lease.created_at.desc())
            .limit(1)
        )
        lease = (await db.execute(lease_stmt)).scalar_one_or_none()
        out.append(
            {
                "property_id": p.id,
                "title": p.title,
                "occupancy": "occupied" if lease else "vacant",
                "tenant_user_id": getattr(lease, "tenant_user_id", None) if lease else None,
                "monthly_rent": getattr(lease, "monthly_rent", None) if lease else None,
                "lease_end_date": getattr(lease, "end_date", None) if lease else None,
            }
        )
    return out


async def income_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    stmt = select(func.coalesce(func.sum(RentPayment.amount_paid), 0.0))
    if start is not None:
        stmt = stmt.where(RentPayment.paid_at >= start)
    if end is not None:
        stmt = stmt.where(RentPayment.paid_at <= end)
    if owner_ids is not None:
        stmt = stmt.where(RentPayment.owner_id.in_(owner_ids))
    total = float((await db.execute(stmt)).scalar_one() or 0.0)
    return {"total_income": total, "start": start, "end": end}


async def expense_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    stmt = select(func.coalesce(func.sum(Expense.amount), 0.0))
    if start is not None:
        stmt = stmt.where(Expense.expense_date >= start)
    if end is not None:
        stmt = stmt.where(Expense.expense_date <= end)
    if owner_ids is not None:
        stmt = stmt.where(Expense.owner_id.in_(owner_ids))
    total = float((await db.execute(stmt)).scalar_one() or 0.0)
    return {"total_expenses": total, "start": start, "end": end}


async def pnl_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    income = await income_report(
        db,
        actor=actor,
        owner_id=owner_id,
        start=datetime.combine(start, datetime.min.time()) if start else None,
        end=datetime.combine(end, datetime.max.time()) if end else None,
    )
    expenses = await expense_report(db, actor=actor, owner_id=owner_id, start=start, end=end)
    net = float(income["total_income"]) - float(expenses["total_expenses"])
    return {
        "total_income": income["total_income"],
        "total_expenses": expenses["total_expenses"],
        "net_income": net,
        "start": start,
        "end": end,
    }


async def occupancy_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
) -> dict[str, int]:
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    total_stmt = select(func.count(Property.id)).where(Property.is_managed)
    if owner_ids is not None:
        total_stmt = total_stmt.where(Property.owner_id.in_(owner_ids))
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    active_lease_exists = exists(
        select(1).where(and_(Lease.property_id == Property.id, Lease.status == LeaseStatus.active))
    )
    occupied_stmt = select(func.count(Property.id)).where(Property.is_managed, active_lease_exists)
    if owner_ids is not None:
        occupied_stmt = occupied_stmt.where(Property.owner_id.in_(owner_ids))
    occupied = int((await db.execute(occupied_stmt)).scalar_one() or 0)

    return {"total": total, "occupied": occupied, "vacant": max(total - occupied, 0)}


async def maintenance_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
) -> dict[str, int]:
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    stmt = select(func.count(MaintenanceRequest.id))
    if owner_ids is not None:
        stmt = stmt.where(MaintenanceRequest.owner_id.in_(owner_ids))
    total = int((await db.execute(stmt)).scalar_one() or 0)
    return {"total_requests": total}

