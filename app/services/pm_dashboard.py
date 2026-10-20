from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Numeric, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.core.exceptions import InsufficientPermissionsError
from app.models.enums import PropertyStatus, RentPaymentStatus, UserRole
from app.models.pm_finance import Expense, RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import offset_payload, read_offset
from app.services.pm.occupancy import active_lease_exists
from app.services.pm.rent_rules import money

# Typed zero for SQL sums. A float literal here makes Postgres sum in double precision.
SQL_ZERO_MONEY = cast(0, Numeric(12, 2))


async def _resolve_owner_scope(
    db: AsyncSession, *, actor: User, owner_id: int | None
) -> Sequence[int] | None:
    if actor.role == UserRole.admin.value:
        return [owner_id] if owner_id is not None else None

    if actor.role == UserRole.agent.value:
        if actor.agent_id is None:
            return []
        if owner_id is not None:
            owner = await execute_with_transient_retry(
                db,
                lambda: db.get(User, owner_id),
                operation_name="pm_owner_scope_owner_lookup",
            )
            if not owner or owner.agent_id != actor.agent_id:
                raise InsufficientPermissionsError("Agent not authorized for this owner")
            return [owner_id]
        owner_stmt = select(User.id).where(User.agent_id == actor.agent_id)
        res = await execute_with_transient_retry(
            db,
            lambda: db.execute(owner_stmt),
            operation_name="pm_owner_scope_agent_owners",
        )
        return [int(r[0]) for r in res.all()]

    # user role: treat as owner dashboard
    return [actor.id]


def _month_start(d: date) -> datetime:
    return datetime(d.year, d.month, 1, tzinfo=UTC)


def _next_month_start(d: date) -> datetime:
    if d.month == 12:
        return datetime(d.year + 1, 1, 1, tzinfo=UTC)
    return datetime(d.year, d.month + 1, 1, tzinfo=UTC)


async def get_dashboard_overview(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
) -> dict[str, Any]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    property_metrics_stmt = select(
        func.count(Property.id),
        func.count(Property.id).filter(active_lease_exists()),
        func.count(Property.id).filter(Property.status == PropertyStatus.maintenance),
    ).where(
        Property.is_managed,
    )
    if owner_ids is not None:
        property_metrics_stmt = property_metrics_stmt.where(Property.owner_id.in_(owner_ids))
    property_metrics = await execute_with_transient_retry(
        db,
        lambda: db.execute(property_metrics_stmt),
        operation_name="pm_dashboard_property_metrics",
    )
    total_properties, occupied_properties, under_maintenance_properties = (
        int(value or 0) for value in property_metrics.one()
    )
    vacant_properties = max(total_properties - occupied_properties, 0)

    today = datetime.now(UTC).date()
    cur_start = _month_start(today)
    cur_end = _next_month_start(today)

    # previous month
    prev_month = (
        date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
    )
    prev_start = _month_start(prev_month)
    prev_end = _next_month_start(prev_month)

    settled = RentPaymentStatus.settled
    revenue_stmt = select(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(RentPayment.paid_at >= cur_start, RentPayment.paid_at < cur_end),
                        RentPayment.amount_paid,
                    ),
                    else_=SQL_ZERO_MONEY,
                )
            ),
            SQL_ZERO_MONEY,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(RentPayment.paid_at >= prev_start, RentPayment.paid_at < prev_end),
                        RentPayment.amount_paid,
                    ),
                    else_=SQL_ZERO_MONEY,
                )
            ),
            SQL_ZERO_MONEY,
        ),
    ).where(
        RentPayment.status == settled,
        RentPayment.paid_at >= prev_start,
        RentPayment.paid_at < cur_end,
    )
    if owner_ids is not None:
        revenue_stmt = revenue_stmt.where(RentPayment.owner_id.in_(owner_ids))
    revenue_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(revenue_stmt),
        operation_name="pm_dashboard_revenue_metrics",
    )
    # Money stays Decimal here. The Money fields of DashboardOverview make the JSON numbers.
    monthly_revenue_current, monthly_revenue_previous = (
        money(value) for value in revenue_result.one()
    )

    # Outstanding rent: sum over charges (due+late - paid), computed in SQL to avoid
    # loading every charge row into process memory.
    charges_subquery = (
        select(
            RentCharge.id,
            (
                RentCharge.amount_due + func.coalesce(RentCharge.late_fee_assessed, SQL_ZERO_MONEY)
            ).label("due_total"),
            func.coalesce(func.sum(RentPayment.amount_paid), SQL_ZERO_MONEY).label("paid_total"),
        )
        .outerjoin(
            RentPayment,
            and_(RentPayment.charge_id == RentCharge.id, RentPayment.status == settled),
        )
        .group_by(RentCharge.id)
    )
    if owner_ids is not None:
        charges_subquery = charges_subquery.where(RentCharge.owner_id.in_(owner_ids))
    charges_sq = charges_subquery.subquery()
    outstanding_stmt = select(
        func.coalesce(
            func.sum(
                func.greatest(charges_sq.c.due_total - charges_sq.c.paid_total, SQL_ZERO_MONEY)
            ),
            SQL_ZERO_MONEY,
        )
    )
    outstanding_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(outstanding_stmt),
        operation_name="pm_dashboard_outstanding_rent",
    )
    outstanding_rent_total = money(outstanding_result.scalar_one())

    # Upcoming expenses: next 30 days
    upcoming_to = today + timedelta(days=30)
    expenses_stmt = select(func.coalesce(func.sum(Expense.amount), SQL_ZERO_MONEY)).where(
        Expense.expense_date >= today, Expense.expense_date <= upcoming_to
    )
    if owner_ids is not None:
        expenses_stmt = expenses_stmt.where(Expense.owner_id.in_(owner_ids))
    expenses_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(expenses_stmt),
        operation_name="pm_dashboard_upcoming_expenses",
    )
    upcoming_expenses_total = money(expenses_result.scalar_one())

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
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    offset = read_offset(cursor_payload)

    # Each per-source query must fetch enough rows to cover the cursor offset plus
    # the full page size (+1 lookahead), since the sources are merged and re-sorted.
    fetch_limit = offset + limit + 1

    activities: list[dict[str, Any]] = []

    pay_stmt = (
        select(RentPayment)
        .where(RentPayment.status == RentPaymentStatus.settled)
        .order_by(RentPayment.paid_at.desc())
        .limit(fetch_limit)
    )
    if owner_ids is not None:
        pay_stmt = pay_stmt.where(RentPayment.owner_id.in_(owner_ids))
    payments_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(pay_stmt),
        operation_name="pm_dashboard_recent_payments",
    )
    payments = list(payments_result.scalars().all())
    for p in payments:
        activities.append(
            {
                "type": "rent_payment",
                "at": p.paid_at,
                "title": "Rent payment received",
                "description": f"Amount {money(p.amount_paid):.2f}",
                "property_id": p.property_id,
                "lease_id": p.lease_id,
                "amount": money(p.amount_paid),
                "id": p.id,
            }
        )

    maint_stmt = (
        select(MaintenanceRequest).order_by(MaintenanceRequest.created_at.desc()).limit(fetch_limit)
    )
    if owner_ids is not None:
        maint_stmt = maint_stmt.where(MaintenanceRequest.owner_id.in_(owner_ids))
    requests_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(maint_stmt),
        operation_name="pm_dashboard_recent_maintenance",
    )
    requests = list(requests_result.scalars().all())
    for r in requests:
        activities.append(
            {
                "type": "maintenance_request",
                "at": r.created_at,
                "title": f"Maintenance request: {r.title}",
                "description": r.description,
                "property_id": r.property_id,
                "lease_id": r.lease_id,
                "status": getattr(r.request_status, "value", r.request_status),
                "id": r.id,
            }
        )

    lease_stmt = select(Lease).order_by(Lease.created_at.desc()).limit(fetch_limit)
    if owner_ids is not None:
        lease_stmt = lease_stmt.where(Lease.owner_id.in_(owner_ids))
    leases_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(lease_stmt),
        operation_name="pm_dashboard_recent_leases",
    )
    leases = list(leases_result.scalars().all())
    for lease in leases:
        activities.append(
            {
                "type": "lease",
                "at": lease.created_at,
                "title": f"Lease {getattr(lease.status, 'value', lease.status)}",
                "description": None,
                "property_id": lease.property_id,
                "lease_id": lease.id,
                "status": getattr(lease.status, "value", lease.status),
            }
        )

    activities.sort(key=lambda x: x["at"], reverse=True)

    # Compute total via per-source SQL COUNT queries so the sum is not capped
    # by fetch_limit.  Each count mirrors the exact WHERE filters used above.
    if with_total:
        pay_count_stmt = select(func.count(RentPayment.id)).where(
            RentPayment.status == RentPaymentStatus.settled
        )
        if owner_ids is not None:
            pay_count_stmt = pay_count_stmt.where(RentPayment.owner_id.in_(owner_ids))

        maint_count_stmt = select(func.count(MaintenanceRequest.id))
        if owner_ids is not None:
            maint_count_stmt = maint_count_stmt.where(MaintenanceRequest.owner_id.in_(owner_ids))

        lease_count_stmt = select(func.count(Lease.id))
        if owner_ids is not None:
            lease_count_stmt = lease_count_stmt.where(Lease.owner_id.in_(owner_ids))

        total_stmt = select(
            pay_count_stmt.scalar_subquery()
            + maint_count_stmt.scalar_subquery()
            + lease_count_stmt.scalar_subquery()
        )
        total_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(total_stmt),
            operation_name="pm_dashboard_recent_activity_total",
        )
        count_total: int | None = int(total_result.scalar_one() or 0)
    else:
        count_total = None

    # Apply cursor-based offset pagination with +1 lookahead
    sliced = activities[offset : offset + limit + 1]
    next_payload: dict | None = offset_payload(offset + limit) if len(sliced) > limit else None
    sliced = sliced[:limit]

    return sliced, next_payload, count_total
