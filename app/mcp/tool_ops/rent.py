"""Shared rent tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.enums import LeaseStatus
from app.models.pm_finance import RentPayment
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.schemas.user import User as UserSchema
from app.services.pm_authz import assert_can_access_lease

logger = get_logger(__name__)


def _user_schema(user) -> UserSchema:
    return UserSchema.model_validate(user)


async def compute_rent_due_items(
    db: AsyncSession,
    *,
    owner_ids: list[int] | None = None,
    property_id: int | None = None,
    overdue_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """Compute rent-due items from active leases.

    Each item represents a lease with its current month's due date and
    overdue status.
    """
    limit = min(max(1, limit), 100)
    offset = (page - 1) * limit
    today = utc_now().date()

    stmt = select(Lease).where(Lease.status == LeaseStatus.active)

    if owner_ids is not None:
        stmt = stmt.where(Lease.owner_id.in_(owner_ids))
    if property_id:
        stmt = stmt.where(Lease.property_id == property_id)

    stmt = stmt.order_by(Lease.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    leases = result.scalars().all()

    # Batch-load property titles to avoid N+1 queries
    property_ids = {lease.property_id for lease in leases if lease.property_id}
    prop_titles: dict[int, str] = {}
    if property_ids:
        prop_result = await db.execute(
            select(Property.id, Property.title).where(Property.id.in_(property_ids))
        )
        prop_titles = {r[0]: r[1] or "Property" for r in prop_result.all()}

    items: list[dict[str, Any]] = []
    for lease in leases:
        payment_due_day = lease.payment_due_day or 1
        grace_days = lease.grace_period_days or 5

        day = min(payment_due_day, 28)
        try:
            due_date = today.replace(day=day)
        except ValueError:
            due_date = today.replace(day=28)

        grace_day = min(payment_due_day + grace_days, 28)
        try:
            grace_end = today.replace(day=grace_day)
        except ValueError:
            grace_end = today.replace(day=28)

        is_overdue = today > grace_end
        is_due = today >= due_date

        if overdue_only and not is_overdue:
            continue

        prop_title = prop_titles.get(lease.property_id, "Property")

        items.append({
            "lease_id": lease.id,
            "property_id": lease.property_id,
            "property_title": prop_title,
            "owner_id": lease.owner_id,
            "tenant_user_id": lease.tenant_user_id,
            "monthly_rent": float(lease.monthly_rent or 0),
            "due_date": due_date.isoformat(),
            "grace_end": grace_end.isoformat(),
            "is_overdue": is_overdue,
            "is_due": is_due,
            "payment_due_day": payment_due_day,
        })

    total_due = sum(i["monthly_rent"] for i in items if i["is_due"])
    overdue_count = sum(1 for i in items if i["is_overdue"])

    return {
        "items": items,
        "total_due": total_due,
        "overdue_count": overdue_count,
        "page": page,
        "limit": limit,
    }


async def record_rent_payment(
    db: AsyncSession,
    *,
    actor,
    lease_id: int,
    amount: float,
    payment_date: str,
    payment_method: str,
    transaction_reference: str | None = None,
    notes: str | None = None,
) -> dict:
    """Record a rent payment for a lease."""
    actor_schema = _user_schema(actor)

    valid_methods = ("cash", "bank_transfer", "upi", "cheque", "online", "other")
    if payment_method.lower() not in valid_methods:
        return {
            "error": True,
            "message": f"Invalid payment method. Valid: {', '.join(valid_methods)}",
        }

    try:
        lease = await assert_can_access_lease(db, actor=actor_schema, lease_id=lease_id)
    except Exception as e:
        return {"error": True, "message": str(e)}

    try:
        paid_at = datetime.fromisoformat(payment_date)
    except (ValueError, TypeError):
        return {"error": True, "message": "Invalid payment_date. Use ISO-8601."}

    payment = RentPayment(
        lease_id=lease_id,
        property_id=lease.property_id,
        owner_id=lease.owner_id,
        amount_paid=amount,
        paid_at=paid_at,
        payment_method=payment_method.lower(),
        reference=transaction_reference,
        notes=notes,
    )
    db.add(payment)
    await db.flush()
    await db.refresh(payment)
    await db.commit()

    return {
        "message": "Payment recorded successfully",
        "payment": {
            "id": payment.id,
            "amount": float(payment.amount_paid or 0),
            "payment_date": payment.paid_at.isoformat() if payment.paid_at else None,
            "payment_method": payment.payment_method,
            "reference": payment.reference,
        },
    }


async def get_rent_history(
    db: AsyncSession,
    *,
    tenant_user_id: int,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """Get rent payment history for a tenant."""
    limit = min(max(1, limit), 100)

    lease_ids_result = await db.execute(
        select(Lease.id).where(Lease.tenant_user_id == tenant_user_id)
    )
    lease_ids = [r[0] for r in lease_ids_result.all()]

    if not lease_ids:
        return {
            "payments": [],
            "total": 0,
            "total_collected": 0,
            "page": page,
            "limit": limit,
        }

    offset = (page - 1) * limit
    stmt = (
        select(RentPayment)
        .where(RentPayment.lease_id.in_(lease_ids))
        .order_by(RentPayment.paid_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    payments = result.scalars().all()

    items = []
    for p in payments:
        items.append({
            "id": p.id,
            "rent_charge_id": getattr(p, "charge_id", None),
            "amount": float(p.amount_paid or 0),
            "payment_date": p.paid_at.isoformat() if p.paid_at else None,
            "payment_method": p.payment_method,
            "transaction_id": p.reference,
            "created_at": p.created_at.isoformat() if getattr(p, "created_at", None) else None,
        })

    total_collected = sum(float(p.get("amount") or 0) for p in items)

    return {
        "payments": items,
        "total": len(items),
        "total_collected": total_collected,
        "page": page,
        "limit": limit,
    }
