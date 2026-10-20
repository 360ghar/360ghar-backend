from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.models.enums import RentPaymentStatus
from app.models.pm_finance import Expense, RentPayment
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import offset_payload, read_offset
from app.services.pm.occupancy import OCCUPIED_LEASE_STATUSES, active_lease_exists
from app.services.pm.rent_rules import money
from app.services.pm_dashboard import SQL_ZERO_MONEY, _resolve_owner_scope

__all__ = [
    "active_lease_exists",
    "rent_roll_report",
    "income_report",
    "expense_report",
    "pnl_report",
]


def _paid_window(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """Payment window for whole UTC days. start is inclusive from 00:00; end is inclusive through its last moment."""
    lower = datetime.combine(start, datetime.min.time(), tzinfo=UTC) if start else None
    upper = (
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC) if end else None
    )
    return lower, upper


async def rent_roll_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    stmt = select(Property).where(Property.is_managed)
    if owner_ids is not None:
        stmt = stmt.where(Property.owner_id.in_(owner_ids))

    total: int | None = None
    if with_total:
        count_stmt = select(func.count(Property.id)).where(Property.is_managed)
        if owner_ids is not None:
            count_stmt = count_stmt.where(Property.owner_id.in_(owner_ids))
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(count_stmt),
            operation_name="pm_reports_rent_roll_count",
        )
        total = int(count_result.scalar_one() or 0)

    stmt = (
        stmt.order_by(Property.created_at.desc(), Property.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    props_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="pm_reports_rent_roll_properties",
    )
    props = list(props_result.scalars().all())
    has_more = len(props) > limit
    props = props[:limit]

    # Batched: one query for the newest occupying lease per property, instead
    # of one query per property (the original N+1 pattern).
    latest_lease: dict[int, Lease] = {}
    if props:
        prop_ids = [p.id for p in props]
        lease_stmt = (
            select(Lease)
            .where(
                Lease.property_id.in_(prop_ids),
                Lease.status.in_(OCCUPIED_LEASE_STATUSES),
            )
            .order_by(Lease.property_id, Lease.created_at.desc())
        )
        lease_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(lease_stmt),
            operation_name="pm_reports_rent_roll_active_leases",
        )
        lease_rows = lease_result.scalars().all()
        # Keep only the newest occupying lease per property (created_at desc).
        for row in lease_rows:
            latest_lease.setdefault(row.property_id, row)

    all_items: list[dict[str, Any]] = []
    for p in props:
        lease = latest_lease.get(p.id)
        all_items.append(
            {
                "property_id": p.id,
                "title": p.title,
                "occupancy": "occupied" if lease else "vacant",
                "tenant_user_id": lease.tenant_user_id if lease else None,
                "monthly_rent": money(lease.monthly_rent) if lease else None,
                "lease_end_date": lease.end_date if lease else None,
            }
        )

    next_payload = offset_payload(offset + limit) if has_more else None
    return all_items, next_payload, total


async def income_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    lower, upper = _paid_window(start, end)
    stmt = select(func.coalesce(func.sum(RentPayment.amount_paid), SQL_ZERO_MONEY)).where(
        RentPayment.status == RentPaymentStatus.settled
    )
    if lower is not None:
        stmt = stmt.where(RentPayment.paid_at >= lower)
    if upper is not None:
        stmt = stmt.where(RentPayment.paid_at < upper)
    if owner_ids is not None:
        stmt = stmt.where(RentPayment.owner_id.in_(owner_ids))
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="pm_reports_income",
    )
    # Money stays Decimal. The Money field of IncomeReport makes the JSON number.
    total = money(result.scalar_one())
    return {"total_income": total, "start": start, "end": end}


async def expense_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    stmt = select(func.coalesce(func.sum(Expense.amount), SQL_ZERO_MONEY))
    if start is not None:
        stmt = stmt.where(Expense.expense_date >= start)
    if end is not None:
        stmt = stmt.where(Expense.expense_date <= end)
    if owner_ids is not None:
        stmt = stmt.where(Expense.owner_id.in_(owner_ids))
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="pm_reports_expenses",
    )
    total = money(result.scalar_one())
    return {"total_expenses": total, "start": start, "end": end}


async def pnl_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    lower, upper = _paid_window(start, end)
    income_stmt = select(func.coalesce(func.sum(RentPayment.amount_paid), SQL_ZERO_MONEY)).where(
        RentPayment.status == RentPaymentStatus.settled
    )
    if lower is not None:
        income_stmt = income_stmt.where(RentPayment.paid_at >= lower)
    if upper is not None:
        income_stmt = income_stmt.where(RentPayment.paid_at < upper)
    if owner_ids is not None:
        income_stmt = income_stmt.where(RentPayment.owner_id.in_(owner_ids))

    expense_stmt = select(func.coalesce(func.sum(Expense.amount), SQL_ZERO_MONEY))
    if start is not None:
        expense_stmt = expense_stmt.where(Expense.expense_date >= start)
    if end is not None:
        expense_stmt = expense_stmt.where(Expense.expense_date <= end)
    if owner_ids is not None:
        expense_stmt = expense_stmt.where(Expense.owner_id.in_(owner_ids))

    income_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(income_stmt),
        operation_name="pm_reports_pnl_income",
    )
    expense_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(expense_stmt),
        operation_name="pm_reports_pnl_expenses",
    )
    total_income = money(income_result.scalar_one())
    total_expenses = money(expense_result.scalar_one())
    net = total_income - total_expenses
    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
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
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)

    occupancy_stmt = select(
        func.count(Property.id),
        func.count(Property.id).filter(active_lease_exists()),
    ).where(Property.is_managed)
    if owner_ids is not None:
        occupancy_stmt = occupancy_stmt.where(Property.owner_id.in_(owner_ids))
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(occupancy_stmt),
        operation_name="pm_reports_occupancy",
    )
    total, occupied = (int(value or 0) for value in result.one())

    return {"total": total, "occupied": occupied, "vacant": max(total - occupied, 0)}


async def maintenance_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
) -> dict[str, int]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    stmt = select(func.count(MaintenanceRequest.id))
    if owner_ids is not None:
        stmt = stmt.where(MaintenanceRequest.owner_id.in_(owner_ids))
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="pm_reports_maintenance",
    )
    total = int(result.scalar_one() or 0)
    return {"total_requests": total}
