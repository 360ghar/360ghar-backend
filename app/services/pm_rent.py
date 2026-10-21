from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    InsufficientPermissionsError,
    NotFoundException,
)
from app.models.enums import LeaseStatus, RentChargeStatus, RentPaymentStatus, UserRole
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.users import User
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead
from app.services.pm.lifecycle import (
    OPEN_CHARGE_STATUSES,
    charge_due_total,
    charge_outstanding,
    effective_status,
    pending_late_fee,
    settled_paid_totals,
)
from app.services.pm.rent_rules import (
    DEFAULT_GRACE_DAYS,
    ZERO_MONEY,
    business_today,
    grace_days,
    is_past_grace,
    money,
)
from app.services.pm_authz import assert_can_access_lease, assert_can_manage_owner_portfolio
from app.services.pm_documents import assert_owned_document

# Lease statuses that keep billing. A lease in its notice window still owes rent.
BILLABLE_LEASE_STATUSES = (LeaseStatus.active, LeaseStatus.expiring_soon)
RENT_CHARGE_MONTH_UNIQUE = "uq_rent_charges_lease_month"


def _month_bounds(billing_month: date) -> tuple[date, date]:
    first = billing_month.replace(day=1)
    last_day = calendar.monthrange(first.year, first.month)[1]
    last = first.replace(day=last_day)
    return first, last


def _add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    return date(year, month, 1)


async def generate_rent_charges(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    lease_id: int | None = None,
    start_month: date | None = None,
    months: int = 1,
) -> dict:
    """Generate rent charges for billable leases (idempotent).

    - If lease_id is provided, generates for that lease only.
    - Otherwise generates for billable leases in the owner's scope.
    """
    if months < 1 or months > 24:
        raise BadRequestException(detail="months must be between 1 and 24")

    base_month = (start_month or business_today()).replace(day=1)

    leases: list[Lease] = []
    if lease_id is not None:
        lease = await assert_can_access_lease(db, actor=actor, lease_id=lease_id)
        # Billing belongs to the owner side. A tenant on the lease may read it but not bill it.
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=lease.owner_id)
        if lease.status not in BILLABLE_LEASE_STATUSES:
            raise BadRequestException(
                detail="Only active or expiring_soon leases can generate charges"
            )
        leases = [lease]
    else:
        # Resolve owner scope
        if actor.role == UserRole.user.value:
            owner_id = actor.id
        elif actor.role == UserRole.agent.value:
            if owner_id is None:
                raise InsufficientPermissionsError("owner_id is required for agents")
        if owner_id is not None:
            await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

        stmt = select(Lease).where(Lease.status.in_(BILLABLE_LEASE_STATUSES))
        if owner_id is not None:
            stmt = stmt.where(Lease.owner_id == owner_id)
        res = await db.execute(stmt)
        leases = list(res.scalars().all())

    created = 0
    skipped = 0

    for lease in leases:
        for i in range(months):
            billing_month = _add_months(base_month, i)
            period_start, period_end = _month_bounds(billing_month)

            # Skip months outside lease range
            if period_end < lease.start_date or period_start > lease.end_date:
                continue

            # The DB range check covers new rows. Clamp older rows so a bad value cannot crash the run.
            due_day_raw = min(max(int(lease.payment_due_day or 1), 1), 28)
            # Clamp due_day to the last day of the billing month to avoid overflow
            last_day_of_month = calendar.monthrange(billing_month.year, billing_month.month)[1]
            due_day = min(due_day_raw, last_day_of_month)
            due_date = date(billing_month.year, billing_month.month, due_day)

            charge = RentCharge(
                lease_id=lease.id,
                property_id=lease.property_id,
                owner_id=lease.owner_id,
                tenant_user_id=lease.tenant_user_id,
                billing_month=billing_month,
                period_start=period_start,
                period_end=period_end,
                due_date=due_date,
                amount_due=money(lease.monthly_rent),
                late_fee_assessed=ZERO_MONEY,
                status=RentChargeStatus.pending,
            )
            try:
                async with db.begin_nested():
                    db.add(charge)
                    await db.flush()
            except IntegrityError as exc:
                # Only the unique (lease, billing month) key is a skip. Other errors surface.
                if RENT_CHARGE_MONTH_UNIQUE not in str(exc.orig):
                    raise ConflictException(
                        detail="A referenced record is invalid",
                        error_code="RENT_CHARGE_REFERENCE_INVALID",
                    ) from None
                skipped += 1
                continue
            else:
                created += 1

    return {"created": created, "skipped": skipped}


async def list_rent_charges(
    db: AsyncSession,
    *,
    actor: User,
    as_tenant: bool = False,
    owner_id: int | None = None,
    lease_id: int | None = None,
    property_id: int | None = None,
    status: RentChargeStatus | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict], dict | None, int | None]:
    """List rent charges with settled payment totals and outstanding amounts.

    The status filter ``overdue`` matches stored overdue charges and open charges
    past their grace period, so it does not depend on the daily job.
    """
    if as_tenant:
        if actor.role != UserRole.user.value:
            raise InsufficientPermissionsError("Only user role can view as tenant")
    else:
        # Owner/RM/admin scope
        if actor.role == UserRole.user.value:
            owner_id = actor.id
        elif actor.role == UserRole.agent.value:
            if owner_id is None:
                raise InsufficientPermissionsError("owner_id is required for agents")
        if owner_id is not None:
            await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    today = business_today()
    grace_expr = func.coalesce(Lease.grace_period_days, DEFAULT_GRACE_DAYS)
    # Settled payments of one charge. An alias keeps the outer join on RentPayment from
    # correlating into this subquery, and the count query needs no GROUP BY.
    settled_row = aliased(RentPayment)
    settled_total = (
        select(func.coalesce(func.sum(settled_row.amount_paid), 0))
        .where(
            settled_row.charge_id == RentCharge.id,
            settled_row.status == RentPaymentStatus.settled,
        )
        .correlate(RentCharge)
        .scalar_subquery()
    )
    still_owes = (
        func.coalesce(RentCharge.amount_due, 0)
        + func.coalesce(RentCharge.late_fee_assessed, 0)
        - settled_total
    ) > 0
    # A stored overdue charge with no balance left is not overdue. It reads as paid.
    overdue_predicate = and_(
        still_owes,
        or_(
            RentCharge.status == RentChargeStatus.overdue,
            and_(
                RentCharge.status.in_(OPEN_CHARGE_STATUSES),
                RentCharge.due_date + grace_expr < today,
            ),
        ),
    )

    def _scoped(stmt):
        stmt = stmt.join(Lease, Lease.id == RentCharge.lease_id)
        if as_tenant:
            stmt = stmt.where(RentCharge.tenant_user_id == actor.id)
        elif owner_id is not None:
            stmt = stmt.where(RentCharge.owner_id == owner_id)
        if lease_id is not None:
            stmt = stmt.where(RentCharge.lease_id == lease_id)
        if property_id is not None:
            stmt = stmt.where(RentCharge.property_id == property_id)
        if status is not None:
            if status == RentChargeStatus.overdue:
                stmt = stmt.where(overdue_predicate)
            elif status in OPEN_CHARGE_STATUSES:
                # Read-time status, as on every read: a repaid charge is paid, and a charge past
                # its grace period is overdue. Neither shows as pending or partial.
                stmt = stmt.where(
                    RentCharge.status == status,
                    still_owes,
                    ~overdue_predicate,
                )
            else:
                stmt = stmt.where(RentCharge.status == status)
        return stmt

    count_total: int | None = None
    if with_total:
        count_stmt = _scoped(select(RentCharge.id))
        count_total = (
            await db.execute(select(func.count()).select_from(count_stmt.subquery()))
        ).scalar_one()

    stmt = _scoped(
        select(
            RentCharge,
            Lease.grace_period_days,
            func.coalesce(
                func.sum(RentPayment.amount_paid).filter(
                    RentPayment.status == RentPaymentStatus.settled
                ),
                0,
            ).label("amount_paid_total"),
        )
        .outerjoin(
            RentPayment,
            and_(
                RentPayment.charge_id == RentCharge.id,
                RentPayment.status == RentPaymentStatus.settled,
            ),
        )
        .group_by(RentCharge.id, Lease.id)
    )

    predicate = keyset_filter(RentCharge.due_date, RentCharge.id, cursor_payload, descending=False)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(RentCharge.due_date.asc(), RentCharge.id.asc()).limit(limit + 1)
    res = await db.execute(stmt)
    rows = res.all()
    page_rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda row: row[0].due_date,
        item_id=lambda row: row[0].id,
    )

    items: list[dict] = []
    for charge, lease_grace, paid_total in page_rows:
        due_total = charge_due_total(charge)
        paid = money(paid_total)
        outstanding = charge_outstanding(charge, paid)
        items.append(
            {
                "charge": charge,
                "status": effective_status(
                    charge.status, charge.due_date, grace_days(lease_grace), outstanding, today
                ),
                "amount_paid_total": paid,
                "amount_due_total": due_total,
                "outstanding": outstanding,
            }
        )

    return items, next_payload, count_total


async def record_rent_payment(
    db: AsyncSession,
    *,
    actor: User,
    charge_id: int,
    amount_paid: Decimal | float,
    paid_at: datetime | None = None,
    payment_method: str | None = None,
    reference: str | None = None,
    notes: str | None = None,
    receipt_document_id: int | None = None,
) -> RentPayment:
    """Record a payment against a charge.

    An owner, agent or admin creates a settled payment, which updates the charge
    status. A tenant creates a pending record, which does not change the charge.
    """
    amount = money(amount_paid)
    if amount <= ZERO_MONEY:
        raise BadRequestException(detail="amount_paid must be > 0")

    # Row-level lock so concurrent payment requests can't interleave and
    # corrupt the outstanding-balance calculation.
    charge = await db.get(RentCharge, charge_id, with_for_update=True, populate_existing=True)
    if not charge:
        raise NotFoundException(detail="Rent charge not found")

    is_tenant = False
    if actor.role == UserRole.admin.value:
        pass
    elif actor.role == UserRole.agent.value:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=charge.owner_id)
    elif charge.owner_id == actor.id:
        pass
    elif charge.tenant_user_id == actor.id:
        is_tenant = True
    else:
        raise InsufficientPermissionsError("Not authorized to record payment for this charge")

    if charge.status == RentChargeStatus.waived:
        raise BadRequestException(detail="This charge is waived")

    lease = await db.get(Lease, charge.lease_id)
    if lease is None:
        raise NotFoundException(detail="Lease not found")

    if receipt_document_id is not None:
        await assert_owned_document(db, document_id=receipt_document_id, owner_id=charge.owner_id)

    settled_before = (await settled_paid_totals(db, [charge.id])).get(charge.id, ZERO_MONEY)
    # The late fee the daily job would assess counts in the balance, so a payment of the
    # balance that a rent-due read shows is accepted.
    today = business_today()
    fee = pending_late_fee(charge, lease, settled_before, today)
    outstanding = charge_outstanding(charge, settled_before) + fee
    if outstanding <= ZERO_MONEY:
        raise BadRequestException(detail="This charge is already fully paid")
    if amount > outstanding:
        raise BadRequestException(
            detail=f"Payment amount ({amount:.2f}) exceeds outstanding balance ({outstanding:.2f})"
        )

    payment = RentPayment(
        charge_id=charge.id,
        lease_id=charge.lease_id,
        property_id=charge.property_id,
        owner_id=charge.owner_id,
        tenant_user_id=charge.tenant_user_id,
        paid_at=paid_at or datetime.now(UTC),
        amount_paid=amount,
        payment_method=payment_method,
        status=RentPaymentStatus.pending if is_tenant else RentPaymentStatus.settled,
        reference=reference,
        notes=notes,
        receipt_document_id=receipt_document_id,
    )
    db.add(payment)
    await db.flush()
    await db.refresh(payment)

    if is_tenant:
        # A tenant claim waits for the owner to settle it. The charge status does not change.
        return payment

    await _apply_settled_total(db, charge, lease, settled_before + amount, fee, today)
    return payment


async def _apply_settled_total(
    db: AsyncSession,
    charge: RentCharge,
    lease: Lease,
    total_paid: Decimal,
    fee: Decimal,
    today: date,
) -> None:
    """Store the late fee (``pending_late_fee``), then set the charge status from the settled total."""
    if fee > ZERO_MONEY:
        charge.late_fee_assessed = fee
        await db.flush()

    outstanding_after = charge_outstanding(charge, total_paid)
    grace = grace_days(lease.grace_period_days)
    if outstanding_after <= ZERO_MONEY:
        charge.status = RentChargeStatus.paid
    elif is_past_grace(charge.due_date, grace, today):
        charge.status = RentChargeStatus.overdue
    elif total_paid > ZERO_MONEY:
        charge.status = RentChargeStatus.partial
    else:
        charge.status = RentChargeStatus.pending
    await db.flush()


async def settle_rent_payment(db: AsyncSession, *, actor: User, payment_id: int) -> RentPayment:
    """Owner, agent or admin confirms a pending tenant claim. The claim then counts toward the charge."""
    payment = await db.get(RentPayment, payment_id, with_for_update=True, populate_existing=True)
    if payment is None:
        raise NotFoundException(detail="Rent payment not found")
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=payment.owner_id)
    if payment.status != RentPaymentStatus.pending:
        raise BadRequestException(detail="Only pending payments can be settled")

    charge = await db.get(
        RentCharge, payment.charge_id, with_for_update=True, populate_existing=True
    )
    if charge is None:
        raise NotFoundException(detail="Rent charge not found")
    if charge.status == RentChargeStatus.waived:
        raise BadRequestException(detail="This charge is waived")
    lease = await db.get(Lease, charge.lease_id)
    if lease is None:
        raise NotFoundException(detail="Lease not found")

    # Other payments may have settled since the claim was made. Re-check the balance.
    settled_before = (await settled_paid_totals(db, [charge.id])).get(charge.id, ZERO_MONEY)
    today = business_today()
    fee = pending_late_fee(charge, lease, settled_before, today)
    outstanding = charge_outstanding(charge, settled_before) + fee
    amount = money(payment.amount_paid)
    if amount > outstanding:
        raise BadRequestException(
            detail=f"Payment amount ({amount:.2f}) exceeds outstanding balance ({outstanding:.2f})"
        )

    payment.status = RentPaymentStatus.settled
    await db.flush()
    await _apply_settled_total(db, charge, lease, settled_before + amount, fee, today)
    await db.refresh(payment)
    return payment


async def delete_pending_rent_payment(db: AsyncSession, *, actor: User, payment_id: int) -> None:
    """Withdraw a pending claim (the tenant) or reject it (owner, agent or admin).

    A pending claim never counted toward the charge, so removing it changes no total.
    Settled payments cannot be removed.
    """
    payment = await db.get(RentPayment, payment_id, with_for_update=True, populate_existing=True)
    if payment is None:
        raise NotFoundException(detail="Rent payment not found")
    if payment.tenant_user_id != actor.id:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=payment.owner_id)
    if payment.status != RentPaymentStatus.pending:
        raise BadRequestException(detail="Only pending payments can be removed")
    await db.delete(payment)
    await db.flush()


async def list_rent_payments(
    db: AsyncSession,
    *,
    actor: User,
    as_tenant: bool = False,
    owner_id: int | None = None,
    lease_id: int | None = None,
    property_id: int | None = None,
    status: RentPaymentStatus | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[RentPayment], dict | None, int | None]:
    if as_tenant:
        if actor.role != UserRole.user.value:
            raise InsufficientPermissionsError("Only user role can view as tenant")
        stmt = select(RentPayment).where(RentPayment.tenant_user_id == actor.id)
    else:
        if actor.role == UserRole.user.value:
            owner_id = actor.id
        elif actor.role == UserRole.agent.value:
            if owner_id is None:
                raise InsufficientPermissionsError("owner_id is required for agents")
        if owner_id is not None:
            await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
        stmt = select(RentPayment)
        if owner_id is not None:
            stmt = stmt.where(RentPayment.owner_id == owner_id)

    if lease_id is not None:
        stmt = stmt.where(RentPayment.lease_id == lease_id)
    if property_id is not None:
        stmt = stmt.where(RentPayment.property_id == property_id)
    if status is not None:
        stmt = stmt.where(RentPayment.status == status)

    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    predicate = keyset_filter(RentPayment.paid_at, RentPayment.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(RentPayment.paid_at.desc(), RentPayment.id.desc()).limit(limit + 1)
    res = await db.execute(stmt)
    rows = list(res.scalars().all())
    items, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda payment: payment.paid_at,
        item_id=lambda payment: payment.id,
    )

    return items, next_payload, count_total
