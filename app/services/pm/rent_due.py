"""Unpaid and overdue rent charges, read from RentCharge rows with the PM rent rules.

The owner, agent and admin rent tools share this query. Rules, as in the daily job
(app/services/pm/lifecycle.py):

- A charge has a balance when rent plus late fee is more than the settled payments.
- A charge is overdue when its stored status is overdue, or when it is still open
  (pending or partial), has a balance, and is past its grace period.
- The late fee that the daily job has not assessed yet is added at read time, with the
  function the job uses (``lifecycle.pending_late_fee``). The amounts shown equal the amounts
  the job stores. ``late_fee``, ``amount_due`` and ``balance`` include it.

The page uses keyset pagination on (due_date, id). ``totals`` are aggregates over the
whole matching set, not over the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RentChargeStatus, RentPaymentStatus
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead
from app.services.pm.lifecycle import (
    OPEN_CHARGE_STATUSES,
    UNPAID_CHARGE_STATUSES,
    charge_due_total,
    effective_status,
    pending_late_fee,
)
from app.services.pm.rent_rules import (
    DEFAULT_GRACE_DAYS,
    ZERO_MONEY,
    business_today,
    grace_days,
    money,
)


@dataclass(frozen=True)
class RentChargePage:
    items: list[dict[str, Any]]
    next_payload: dict[str, Any] | None
    totals: dict[str, Any]


def _expressions(today: date) -> dict[str, Any]:
    """SQL expressions for one charge row, grouped by RentCharge.id and Lease.id."""
    grace = func.coalesce(Lease.grace_period_days, DEFAULT_GRACE_DAYS)
    paid = func.coalesce(
        func.sum(RentPayment.amount_paid).filter(RentPayment.status == RentPaymentStatus.settled),
        0,
    )
    due = func.coalesce(RentCharge.amount_due, 0) + func.coalesce(RentCharge.late_fee_assessed, 0)
    outstanding = func.greatest(due - paid, 0)
    overdue = or_(
        RentCharge.status == RentChargeStatus.overdue,
        and_(
            RentCharge.status.in_(OPEN_CHARGE_STATUSES),
            RentCharge.due_date + grace < today,
        ),
    )
    return {
        "grace": grace,
        "paid": paid,
        "outstanding": outstanding,
        "overdue": overdue,
        "overdue_open": and_(overdue, outstanding > 0),
    }


def _charges_query(
    columns: list[Any],
    *,
    exprs: dict[str, Any],
    conditions: list[Any],
    unpaid_only: bool,
):
    stmt = (
        select(*columns)
        .join(Lease, Lease.id == RentCharge.lease_id)
        .outerjoin(
            RentPayment,
            and_(
                RentPayment.charge_id == RentCharge.id,
                RentPayment.status == RentPaymentStatus.settled,
            ),
        )
        .group_by(RentCharge.id, Lease.id)
    )
    for condition in conditions:
        stmt = stmt.where(condition)
    if unpaid_only:
        stmt = stmt.having(exprs["outstanding"] > 0)
    return stmt


async def list_rent_charge_page(
    db: AsyncSession,
    *,
    owner_ids: list[int] | None = None,
    property_id: int | None = None,
    unpaid_only: bool = True,
    overdue_only: bool = False,
    due_on_or_before: date | None = None,
    cursor_payload: dict[str, Any] | None = None,
    limit: int = 20,
    today: date | None = None,
) -> RentChargePage:
    """One page of charges plus totals over the full matching set.

    ``owner_ids`` None means no owner filter. The caller checks the scope.
    ``unpaid_only`` keeps charges with a balance in pending, partial or overdue status.
    ``overdue_only`` keeps overdue charges by the rule above, before the page limit.
    """
    today = today or business_today()
    limit = min(max(1, limit), 100)
    exprs = _expressions(today)

    conditions: list[Any] = []
    if owner_ids is not None:
        conditions.append(RentCharge.owner_id.in_(owner_ids))
    if property_id:
        conditions.append(RentCharge.property_id == property_id)
    if unpaid_only:
        conditions.append(RentCharge.status.in_(UNPAID_CHARGE_STATUSES))
    if overdue_only:
        conditions.append(exprs["overdue"])
    if due_on_or_before is not None:
        conditions.append(RentCharge.due_date <= due_on_or_before)

    page_stmt = _charges_query(
        [
            RentCharge,
            Lease,
            exprs["paid"].label("paid_total"),
            exprs["overdue_open"].label("is_overdue"),
        ],
        exprs=exprs,
        conditions=conditions,
        unpaid_only=unpaid_only,
    )
    predicate = keyset_filter(
        RentCharge.due_date, RentCharge.id, cursor_payload or {}, descending=False
    )
    if predicate is not None:
        page_stmt = page_stmt.where(predicate)
    page_stmt = page_stmt.order_by(RentCharge.due_date.asc(), RentCharge.id.asc()).limit(limit + 1)
    rows = (await db.execute(page_stmt)).all()
    page_rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda row: row[0].due_date,
        item_id=lambda row: row[0].id,
    )

    items: list[dict[str, Any]] = []
    for charge, lease, paid_total, is_overdue in page_rows:
        grace = grace_days(lease.grace_period_days)
        # Exact arithmetic (Decimal). The floats below are the JSON numbers of this response.
        paid = money(paid_total)
        pending_fee = pending_late_fee(charge, lease, paid, today)
        due = charge_due_total(charge) + pending_fee
        balance = max(due - paid, ZERO_MONEY)
        status = effective_status(charge.status, charge.due_date, grace, balance, today)
        items.append(
            {
                "id": charge.id,
                "lease_id": charge.lease_id,
                "property_id": charge.property_id,
                "owner_id": charge.owner_id,
                "tenant_user_id": charge.tenant_user_id,
                "billing_month": charge.billing_month.isoformat() if charge.billing_month else None,
                "due_date": charge.due_date.isoformat() if charge.due_date else None,
                "grace_end": (charge.due_date + timedelta(days=grace)).isoformat(),
                "amount_due": float(due),
                "amount_paid": float(paid),
                "balance": float(balance),
                "late_fee": float(money(charge.late_fee_assessed) + pending_fee),
                "status": getattr(status, "value", status),
                "is_overdue": bool(is_overdue) and balance > ZERO_MONEY,
            }
        )

    totals = await _totals(
        db,
        exprs=exprs,
        conditions=conditions,
        unpaid_only=unpaid_only,
        today=today,
    )
    return RentChargePage(items=items, next_payload=next_payload, totals=totals)


async def _unassessed_fees_total(
    db: AsyncSession,
    *,
    exprs: dict[str, Any],
    conditions: list[Any],
    today: date,
) -> Decimal:
    """Sum of the late fees that the daily job has not assessed yet, over the matching charges.

    The SQL narrows to charges that can have a pending fee (no stored fee, past grace, a late fee
    policy on the lease). The fee itself comes from ``pending_late_fee``, the function the job
    uses. After the job has run, this set is empty.
    """
    narrowed = [
        *conditions,
        RentCharge.status.in_(UNPAID_CHARGE_STATUSES),
        func.coalesce(RentCharge.late_fee_assessed, 0) == 0,
        RentCharge.due_date + exprs["grace"] < today,
        or_(Lease.late_fee_amount > 0, Lease.late_fee_percentage > 0),
    ]
    stmt = _charges_query(
        [RentCharge, Lease, exprs["paid"].label("paid_total")],
        exprs=exprs,
        conditions=narrowed,
        unpaid_only=True,
    )
    total = ZERO_MONEY
    for charge, lease, paid_total in (await db.execute(stmt)).all():
        total += pending_late_fee(charge, lease, money(paid_total), today)
    return total


async def _totals(
    db: AsyncSession,
    *,
    exprs: dict[str, Any],
    conditions: list[Any],
    unpaid_only: bool,
    today: date,
) -> dict[str, Any]:
    """Count, balance, paid and overdue count over every matching charge, in one query.

    The balance adds the late fees that the daily job has not assessed yet.
    """
    grouped = _charges_query(
        [
            RentCharge.id.label("charge_id"),
            exprs["outstanding"].label("outstanding"),
            exprs["paid"].label("paid"),
            exprs["overdue_open"].label("overdue_open"),
        ],
        exprs=exprs,
        conditions=conditions,
        unpaid_only=unpaid_only,
    ).subquery()
    agg = select(
        func.count(),
        func.coalesce(func.sum(grouped.c.outstanding), 0),
        func.coalesce(func.sum(grouped.c.paid), 0),
        func.coalesce(func.sum(case((grouped.c.overdue_open, 1), else_=0)), 0),
    )
    count, balance, paid, overdue = (await db.execute(agg)).one()
    unassessed = await _unassessed_fees_total(db, exprs=exprs, conditions=conditions, today=today)
    return {
        "total_due": float(money(balance) + unassessed),
        "total_paid": float(money(paid)),
        "overdue_count": int(overdue or 0),
        "charges_count": int(count or 0),
    }
