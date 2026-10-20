"""Shared rent tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.mcp.utils import serialize_rent_payment
from app.models.enums import PaymentMethod
from app.models.pm_finance import RentPayment
from app.models.pm_leases import Lease
from app.schemas.pagination import encode_cursor, read_offset, trim_offset_lookahead
from app.services.pm.rent_due import list_rent_charge_page
from app.services.pm.rent_rules import business_today

logger = get_logger(__name__)


async def compute_rent_due_items(
    db: AsyncSession,
    *,
    owner_ids: list[int] | None = None,
    property_id: int | None = None,
    overdue_only: bool = False,
    cursor_payload: dict | None = None,
    limit: int = 20,
    filters: dict | None = None,
) -> dict:
    """Rent due now: unpaid charges due on or before today, from RentCharge rows.

    ``overdue_only`` applies the PM overdue rule before the page limit. ``totals`` holds
    total_due, total_paid, overdue_count and charges_count over the full matching set.
    ``filters`` binds the returned cursor to the request filters.
    """
    limit = min(max(1, limit), 100)
    today = business_today()
    page = await list_rent_charge_page(
        db,
        owner_ids=owner_ids,
        property_id=property_id,
        unpaid_only=True,
        overdue_only=overdue_only,
        due_on_or_before=today,
        cursor_payload=cursor_payload,
        limit=limit,
        today=today,
    )
    next_cursor = encode_cursor(page.next_payload, filters) if page.next_payload else None
    return {
        "items": page.items,
        "totals": page.totals,
        "next_cursor": next_cursor,
        "has_more": page.next_payload is not None,
        "limit": limit,
    }


async def get_rent_history(
    db: AsyncSession,
    *,
    tenant_user_id: int,
    cursor_payload: dict | None = None,
    limit: int = 20,
    filters: dict | None = None,
    include_total: bool = False,
) -> dict:
    """One page of a tenant's rent payments, newest first.

    ``filters`` binds the returned cursor. ``total`` is the count of all payments
    when ``include_total`` is set, otherwise null. ``total_collected`` is the sum
    over all payments, not over the page.
    """
    limit = min(max(1, limit), 100)
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    lease_ids = [
        r[0]
        for r in (
            await db.execute(select(Lease.id).where(Lease.tenant_user_id == tenant_user_id))
        ).all()
    ]
    if not lease_ids:
        return {
            "items": [],
            "total": 0 if include_total else None,
            "total_collected": 0.0,
            "next_cursor": None,
            "has_more": False,
            "limit": limit,
        }

    scope = RentPayment.lease_id.in_(lease_ids)
    stmt = (
        select(RentPayment)
        .where(scope)
        .order_by(RentPayment.paid_at.desc(), RentPayment.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    payments = list((await db.execute(stmt)).scalars().all())
    page, next_payload = trim_offset_lookahead(payments, limit=limit, offset=offset)

    total = None
    if include_total:
        total = (await db.execute(select(func.count(RentPayment.id)).where(scope))).scalar_one()
    collected = (
        await db.execute(select(func.coalesce(func.sum(RentPayment.amount_paid), 0)).where(scope))
    ).scalar_one()

    return {
        "items": [serialize_rent_payment(p) for p in page],
        "total": total,
        "total_collected": round(float(collected or 0), 2),
        "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
        "has_more": next_payload is not None,
        "limit": limit,
    }


async def record_lease_rent_payment(
    db: AsyncSession,
    *,
    actor,
    lease_id: int,
    amount: float,
    paid_at: datetime,
    payment_method: PaymentMethod,
    reference: str | None = None,
    notes: str | None = None,
) -> RentPayment:
    """Settle the oldest unpaid rent charge of a lease with one payment.

    Unpaid means pending, partial or overdue (a stored overdue charge is included).
    A charge with no balance left is skipped. The actor must be able to access the
    lease. The payment goes through ``services.pm_rent.record_rent_payment``, which
    locks the charge and updates its status. Raises BadRequestException when the lease
    has no unpaid charge. Flushes only; the caller commits, and serializes the payment
    before it does.
    """
    from app.core.exceptions import BadRequestException
    from app.models.pm_finance import RentCharge
    from app.schemas.user import User as UserSchema
    from app.services.pm.lifecycle import (
        UNPAID_CHARGE_STATUSES,
        charge_outstanding,
        settled_paid_totals,
    )
    from app.services.pm.rent_rules import ZERO_MONEY
    from app.services.pm_authz import assert_can_access_lease
    from app.services.pm_rent import record_rent_payment

    await assert_can_access_lease(db, actor=UserSchema.model_validate(actor), lease_id=lease_id)

    unpaid = list(
        (
            await db.execute(
                select(RentCharge)
                .where(
                    RentCharge.lease_id == lease_id,
                    RentCharge.status.in_(UNPAID_CHARGE_STATUSES),
                )
                .order_by(RentCharge.due_date, RentCharge.id)
            )
        )
        .scalars()
        .all()
    )
    paid = await settled_paid_totals(db, [c.id for c in unpaid])
    charge = next(
        (c for c in unpaid if charge_outstanding(c, paid.get(c.id, ZERO_MONEY)) > ZERO_MONEY),
        None,
    )
    if charge is None:
        raise BadRequestException(detail="This lease has no open rent charge")

    return await record_rent_payment(
        db,
        actor=actor,
        charge_id=charge.id,
        amount_paid=amount,
        paid_at=paid_at,
        payment_method=payment_method,
        reference=reference,
        notes=notes,
    )
