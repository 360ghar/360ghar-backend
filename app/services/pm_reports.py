from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.models.enums import LeaseStatus
from app.models.pm_finance import Expense, RentPayment
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import offset_payload, read_offset
from app.services.pm_dashboard import _resolve_owner_scope

if TYPE_CHECKING:
    from sqlalchemy import Exists


def active_lease_exists() -> Exists:
    """Correlated EXISTS: Property has an active lease.

    Shared "occupied" definition for occupancy reports (pm_reports and the
    platform-wide system stats in services/agent/analytics.py).
    """
    return exists(
        select(1).where(and_(Lease.property_id == Property.id, Lease.status == LeaseStatus.active))
    )


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

    stmt = stmt.order_by(Property.created_at.desc(), Property.id.desc()).offset(offset).limit(limit + 1)
    props_result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="pm_reports_rent_roll_properties",
    )
    props = list(props_result.scalars().all())
    has_more = len(props) > limit
    props = props[:limit]

    # Batched: one query for the newest active lease per property, instead
    # of one query per property (the original N+1 pattern).
    latest_lease: dict[int, Lease] = {}
    if props:
        prop_ids = [p.id for p in props]
        lease_stmt = (
            select(Lease)
            .where(
                Lease.property_id.in_(prop_ids),
                Lease.status == LeaseStatus.active,
            )
            .order_by(Lease.property_id, Lease.created_at.desc())
        )
        lease_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(lease_stmt),
            operation_name="pm_reports_rent_roll_active_leases",
        )
        lease_rows = lease_result.scalars().all()
        # Keep only the newest active lease per property (created_at desc).
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
                "tenant_user_id": getattr(lease, "tenant_user_id", None) if lease else None,
                "monthly_rent": getattr(lease, "monthly_rent", None) if lease else None,
                "lease_end_date": getattr(lease, "end_date", None) if lease else None,
            }
        )

    next_payload = offset_payload(offset + limit) if has_more else None
    return all_items, next_payload, total


async def income_report(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    owner_ids = await _resolve_owner_scope(db, actor=actor, owner_id=owner_id)
    stmt = select(func.coalesce(func.sum(RentPayment.amount_paid), 0.0))
    if start is not None:
        stmt = stmt.where(RentPayment.paid_at >= start)
    if end is not None:
        stmt = stmt.where(RentPayment.paid_at <= end)
    if owner_ids is not None:
        stmt = stmt.where(RentPayment.owner_id.in_(owner_ids))
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="pm_reports_income",
    )
    total = float(result.scalar_one() or 0.0)
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
    stmt = select(func.coalesce(func.sum(Expense.amount), 0.0))
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
    total = float(result.scalar_one() or 0.0)
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

    income_start = datetime.combine(start, datetime.min.time()) if start else None
    income_end = datetime.combine(end, datetime.max.time()) if end else None

    income_stmt = select(func.coalesce(func.sum(RentPayment.amount_paid), 0.0))
    if income_start is not None:
        income_stmt = income_stmt.where(RentPayment.paid_at >= income_start)
    if income_end is not None:
        income_stmt = income_stmt.where(RentPayment.paid_at <= income_end)
    if owner_ids is not None:
        income_stmt = income_stmt.where(RentPayment.owner_id.in_(owner_ids))

    expense_stmt = select(func.coalesce(func.sum(Expense.amount), 0.0))
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
    total_income = float(income_result.scalar_one() or 0.0)
    total_expenses = float(expense_result.scalar_one() or 0.0)
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
