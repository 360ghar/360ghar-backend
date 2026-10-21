"""Daily lifecycle steps: assess overdue rent charges and move leases through expiry.

Each step is idempotent. Run the pair once a day from ``app/services/pm_scheduler.py``.
Money stays a Decimal here. See ``app/services/pm/rent_rules.py``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeaseStatus, RentChargeStatus, RentPaymentStatus
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.services.pm.rent_rules import (
    LEASE_EXPIRY_NOTICE_DAYS,
    ZERO_MONEY,
    grace_days,
    is_overdue,
    late_fee,
    money,
)

OPEN_CHARGE_STATUSES = (RentChargeStatus.pending, RentChargeStatus.partial)
# Charges still owed in some form. A stored overdue charge can be repaid before the job runs.
UNPAID_CHARGE_STATUSES = (*OPEN_CHARGE_STATUSES, RentChargeStatus.overdue)


async def settled_paid_totals(db: AsyncSession, charge_ids: list[int]) -> dict[int, Decimal]:
    """Settled payment totals per charge. Pending tenant claims are excluded."""
    if not charge_ids:
        return {}
    stmt = (
        select(RentPayment.charge_id, func.coalesce(func.sum(RentPayment.amount_paid), 0))
        .where(
            RentPayment.charge_id.in_(charge_ids),
            RentPayment.status == RentPaymentStatus.settled,
        )
        .group_by(RentPayment.charge_id)
    )
    return {int(cid): money(total) for cid, total in (await db.execute(stmt)).all()}


def charge_due_total(charge: RentCharge) -> Decimal:
    """Rent plus assessed late fees."""
    return money(charge.amount_due) + money(charge.late_fee_assessed)


def charge_outstanding(charge: RentCharge, settled_paid: Decimal) -> Decimal:
    """Balance still owed after settled payments. Never negative."""
    return max(charge_due_total(charge) - settled_paid, ZERO_MONEY)


def effective_status(
    stored: RentChargeStatus,
    due_date: date,
    grace: int,
    outstanding: Decimal,
    today: date,
) -> RentChargeStatus:
    """Status to show on a read. The daily job may not have run yet.

    A charge with no balance left is paid, whatever the stored value. An open charge past
    its grace period is overdue. Any other stored status is returned unchanged.
    """
    if stored in UNPAID_CHARGE_STATUSES and outstanding <= ZERO_MONEY:
        return RentChargeStatus.paid
    if stored in OPEN_CHARGE_STATUSES and is_overdue(due_date, grace, today, outstanding):
        return RentChargeStatus.overdue
    return stored


def pending_late_fee(
    charge: RentCharge, lease: Lease, settled_paid: Decimal, today: date
) -> Decimal:
    """The late fee the PM rules assess for this charge today, or 0.00.

    One function for the daily job, the payment path and every rent-due read, so a fee shown
    before the job runs equals the fee the job stores. The fee is ``rent_rules.late_fee``. It
    is assessed once: a charge with a stored fee returns 0.00. The charge must be unpaid
    (pending, partial or overdue), owe a balance before the fee, and be past its grace period.
    """
    if charge.status not in UNPAID_CHARGE_STATUSES or money(charge.late_fee_assessed) > ZERO_MONEY:
        return ZERO_MONEY
    outstanding = charge_outstanding(charge, settled_paid)
    if not is_overdue(charge.due_date, grace_days(lease.grace_period_days), today, outstanding):
        return ZERO_MONEY
    return late_fee(charge.amount_due, lease.late_fee_amount, lease.late_fee_percentage)


async def assess_overdue_charges(db: AsyncSession, *, today: date) -> dict[str, int]:
    """Mark unpaid charges past their grace period as overdue, and assess the late fee once.

    A stored charge with no balance left is set to paid. This repairs rows written before
    exact money math, so a repaid charge never stays overdue.
    """
    stmt = (
        select(RentCharge, Lease)
        .join(Lease, Lease.id == RentCharge.lease_id)
        .where(RentCharge.status.in_(UNPAID_CHARGE_STATUSES))
        .with_for_update(of=RentCharge)
    )
    rows = (await db.execute(stmt)).all()
    paid = await settled_paid_totals(db, [charge.id for charge, _ in rows])

    marked = 0
    fees = 0
    settled = 0
    for charge, lease in rows:
        settled_paid = paid.get(charge.id, ZERO_MONEY)
        outstanding = charge_outstanding(charge, settled_paid)
        if outstanding <= ZERO_MONEY:
            charge.status = RentChargeStatus.paid
            settled += 1
            continue
        fee = pending_late_fee(charge, lease, settled_paid, today)
        if fee > ZERO_MONEY:
            charge.late_fee_assessed = fee
            fees += 1
        if charge.status != RentChargeStatus.overdue and is_overdue(
            charge.due_date, grace_days(lease.grace_period_days), today, outstanding
        ):
            charge.status = RentChargeStatus.overdue
            marked += 1
    await db.flush()
    return {"charges_overdue": marked, "late_fees_assessed": fees, "charges_settled": settled}


async def expire_leases(db: AsyncSession, *, today: date) -> dict[str, int]:
    """Move leases by end date: past end -> expired; inside the notice window -> expiring_soon."""
    expired_rows = (
        await db.execute(
            update(Lease)
            .where(
                Lease.status.in_([LeaseStatus.active, LeaseStatus.expiring_soon]),
                Lease.end_date < today,
            )
            .values(status=LeaseStatus.expired)
            .returning(Lease.id, Lease.property_id)
            .execution_options(synchronize_session=False)
        )
    ).all()

    expired_ids = [lease_id for lease_id, _ in expired_rows]
    if expired_ids:
        # Expired leases no longer point the property at a current lease or tenant.
        await db.execute(
            update(Property)
            .where(Property.current_lease_id.in_(expired_ids))
            .values(current_lease_id=None, current_tenant_id=None)
            .execution_options(synchronize_session=False)
        )

    notice_end = today + timedelta(days=LEASE_EXPIRY_NOTICE_DAYS)
    expiring = await db.execute(
        update(Lease)
        .where(
            Lease.status == LeaseStatus.active,
            Lease.end_date >= today,
            Lease.end_date <= notice_end,
        )
        .values(status=LeaseStatus.expiring_soon)
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return {
        "leases_expired": len(expired_rows),
        "leases_expiring_soon": int(getattr(expiring, "rowcount", 0) or 0),
    }


async def run_lifecycle(db: AsyncSession, *, today: date) -> dict[str, Any]:
    """Run both daily steps in the caller's transaction."""
    charges = await assess_overdue_charges(db, today=today)
    leases = await expire_leases(db, today=today)
    return {**charges, **leases}


__all__ = [
    "OPEN_CHARGE_STATUSES",
    "UNPAID_CHARGE_STATUSES",
    "assess_overdue_charges",
    "charge_due_total",
    "charge_outstanding",
    "effective_status",
    "expire_leases",
    "pending_late_fee",
    "run_lifecycle",
    "settled_paid_totals",
]
