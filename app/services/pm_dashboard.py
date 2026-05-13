from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientPermissionsError
from app.models.enums import LeaseStatus, UserRole
from app.models.pm_finance import Expense, RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User


async def _resolve_owner_scope(
    db: AsyncSession, *, actor: User, owner_id: int | None
) -> Sequence[int] | None:
    if actor.role == UserRole.admin.value:
        return [owner_id] if owner_id is not None else None

    if actor.role == UserRole.agent.value:
        if actor.agent_id is None:
            return []
        if owner_id is not None:
            owner = await db.get(User, owner_id)
            if not owner or owner.agent_id != actor.agent_id:
                raise InsufficientPermissionsError("Agent not authorized for this owner")
            return [owner_id]
        res = await db.execute(select(User.id).where(User.agent_id == actor.agent_id))
        return [int(r[0]) for r in res.all()]

    # user role: treat as owner dashboard
    return [actor.id]


def _month_start(d: date) -> datetime:
    return datetime(d.year, d.month, 1)


def _next_month_start(d: date) -> datetime:
    if d.month == 12:
        return datetime(d.year + 1, 1, 1)
    return datetime(d.year, d.month + 1, 1)


async def get_dashboard_overview(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
) -> dict[str, Any]:
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    prop_stmt = select(func.count(Property.id)).where(Property.is_managed)
    if owner_ids is not None:
        prop_stmt = prop_stmt.where(Property.owner_id.in_(owner_ids))
    total_properties = int((await db.execute(prop_stmt)).scalar_one() or 0)

    active_lease_exists = exists(
        select(1).where(and_(Lease.property_id == Property.id, Lease.status == LeaseStatus.active))
    )

    occupied_stmt = select(func.count(Property.id)).where(
        Property.is_managed, active_lease_exists
    )
    if owner_ids is not None:
        occupied_stmt = occupied_stmt.where(Property.owner_id.in_(owner_ids))
    occupied_properties = int((await db.execute(occupied_stmt)).scalar_one() or 0)
    vacant_properties = max(total_properties - occupied_properties, 0)

    maintenance_stmt = select(func.count(Property.id)).where(
        Property.is_managed, Property.status == "maintenance"  # PropertyStatus enum stored as string in DB
    )
    if owner_ids is not None:
        maintenance_stmt = maintenance_stmt.where(Property.owner_id.in_(owner_ids))
    under_maintenance_properties = int((await db.execute(maintenance_stmt)).scalar_one() or 0)

    today = date.today()
    cur_start = _month_start(today)
    cur_end = _next_month_start(today)

    # previous month
    prev_month = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
    prev_start = _month_start(prev_month)
    prev_end = _next_month_start(prev_month)

    revenue_stmt = select(func.coalesce(func.sum(RentPayment.amount_paid), 0.0)).where(
        RentPayment.paid_at >= cur_start, RentPayment.paid_at < cur_end
    )
    if owner_ids is not None:
        revenue_stmt = revenue_stmt.where(RentPayment.owner_id.in_(owner_ids))
    monthly_revenue_current = float((await db.execute(revenue_stmt)).scalar_one() or 0.0)

    revenue_prev_stmt = select(func.coalesce(func.sum(RentPayment.amount_paid), 0.0)).where(
        RentPayment.paid_at >= prev_start, RentPayment.paid_at < prev_end
    )
    if owner_ids is not None:
        revenue_prev_stmt = revenue_prev_stmt.where(RentPayment.owner_id.in_(owner_ids))
    monthly_revenue_previous = float((await db.execute(revenue_prev_stmt)).scalar_one() or 0.0)

    # Outstanding rent: sum over charges (due+late - paid)
    charges_stmt = (
        select(
            RentCharge.id,
            (RentCharge.amount_due + func.coalesce(RentCharge.late_fee_assessed, 0.0)).label("due_total"),
            func.coalesce(func.sum(RentPayment.amount_paid), 0.0).label("paid_total"),
        )
        .outerjoin(RentPayment, RentPayment.charge_id == RentCharge.id)
        .group_by(RentCharge.id)
    )
    if owner_ids is not None:
        charges_stmt = charges_stmt.where(RentCharge.owner_id.in_(owner_ids))
    charges_rows = (await db.execute(charges_stmt)).all()
    outstanding_rent_total = 0.0
    for _cid, due_total, paid_total in charges_rows:
        outstanding_rent_total += max(float(due_total or 0.0) - float(paid_total or 0.0), 0.0)

    # Upcoming expenses: next 30 days
    upcoming_to = today + timedelta(days=30)
    expenses_stmt = select(func.coalesce(func.sum(Expense.amount), 0.0)).where(
        Expense.expense_date >= today, Expense.expense_date <= upcoming_to
    )
    if owner_ids is not None:
        expenses_stmt = expenses_stmt.where(Expense.owner_id.in_(owner_ids))
    upcoming_expenses_total = float((await db.execute(expenses_stmt)).scalar_one() or 0.0)

    return {
        "total_properties": total_properties,
        "occupied_properties": occupied_properties,
        "vacant_properties": vacant_properties,
        "under_maintenance_properties": under_maintenance_properties,
        "monthly_revenue_current": monthly_revenue_current,
        "monthly_revenue_previous": monthly_revenue_previous,
        "outstanding_rent_total": outstanding_rent_total,
        "upcoming_expenses_total": upcoming_expenses_total,
    }


async def get_recent_activity(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    activities: list[dict[str, Any]] = []

    pay_stmt = select(RentPayment).order_by(RentPayment.paid_at.desc()).limit(limit)
    if owner_ids is not None:
        pay_stmt = pay_stmt.where(RentPayment.owner_id.in_(owner_ids))
    payments = list((await db.execute(pay_stmt)).scalars().all())
    for p in payments:
        activities.append(
            {
                "type": "rent_payment",
                "at": p.paid_at.isoformat(),
                "property_id": p.property_id,
                "lease_id": p.lease_id,
                "amount": p.amount_paid,
                "id": p.id,
            }
        )

    maint_stmt = select(MaintenanceRequest).order_by(MaintenanceRequest.created_at.desc()).limit(limit)
    if owner_ids is not None:
        maint_stmt = maint_stmt.where(MaintenanceRequest.owner_id.in_(owner_ids))
    requests = list((await db.execute(maint_stmt)).scalars().all())
    for r in requests:
        activities.append(
            {
                "type": "maintenance_request",
                "at": r.created_at.isoformat(),
                "property_id": r.property_id,
                "lease_id": r.lease_id,
                "status": getattr(r.request_status, "value", r.request_status),
                "id": r.id,
            }
        )

    lease_stmt = select(Lease).order_by(Lease.created_at.desc()).limit(limit)
    if owner_ids is not None:
        lease_stmt = lease_stmt.where(Lease.owner_id.in_(owner_ids))
    leases = list((await db.execute(lease_stmt)).scalars().all())
    for lease in leases:
        activities.append(
            {
                "type": "lease",
                "at": lease.created_at.isoformat(),
                "property_id": lease.property_id,
                "lease_id": lease.id,
                "status": getattr(lease.status, "value", lease.status),
            }
        )

    activities.sort(key=lambda x: x.get("at") or "", reverse=True)
    return activities[:limit]

