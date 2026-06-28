from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.models.enums import LeaseStatus, RentChargeStatus, UserRole
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.users import User
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.services.pm_authz import assert_can_access_lease, assert_can_manage_owner_portfolio


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
    """Generate rent charges for active leases (idempotent).

    - If lease_id is provided, generates for that lease only.
    - Otherwise generates for active leases in the owner's scope.
    """
    if months < 1 or months > 24:
        raise BadRequestException(detail="months must be between 1 and 24")

    base_month = (start_month or date.today()).replace(day=1)

    leases: list[Lease] = []
    if lease_id is not None:
        lease = await assert_can_access_lease(db, actor=actor, lease_id=lease_id)
        if lease.status != LeaseStatus.active:
            raise BadRequestException(detail="Only active leases can generate charges")
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

        stmt = select(Lease).where(Lease.status == LeaseStatus.active)
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

            due_day_raw = int(getattr(lease, "payment_due_day", 1) or 1)
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
                amount_due=float(lease.monthly_rent),
                late_fee_assessed=0.0,
                status=RentChargeStatus.pending,
            )
            try:
                async with db.begin_nested():
                    db.add(charge)
                    await db.flush()
            except IntegrityError:
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
    """List rent charges with computed payment totals and outstanding amounts."""
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

    # Base filter stmt (without keyset) — used for total count
    filter_stmt = select(RentCharge.id)
    if as_tenant:
        filter_stmt = filter_stmt.where(RentCharge.tenant_user_id == actor.id)
    elif owner_id is not None:
        filter_stmt = filter_stmt.where(RentCharge.owner_id == owner_id)
    if lease_id is not None:
        filter_stmt = filter_stmt.where(RentCharge.lease_id == lease_id)
    if property_id is not None:
        filter_stmt = filter_stmt.where(RentCharge.property_id == property_id)
    if status is not None:
        filter_stmt = filter_stmt.where(RentCharge.status == status)

    count_total: int | None = None
    if with_total:
        count_stmt = select(func.count()).select_from(filter_stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    # Build the aggregating query for items
    stmt = (
        select(
            RentCharge,
            func.coalesce(func.sum(RentPayment.amount_paid), 0.0).label("amount_paid_total"),
        )
        .outerjoin(RentPayment, RentPayment.charge_id == RentCharge.id)
        .group_by(RentCharge.id)
    )

    if as_tenant:
        stmt = stmt.where(RentCharge.tenant_user_id == actor.id)
    elif owner_id is not None:
        stmt = stmt.where(RentCharge.owner_id == owner_id)

    if lease_id is not None:
        stmt = stmt.where(RentCharge.lease_id == lease_id)
    if property_id is not None:
        stmt = stmt.where(RentCharge.property_id == property_id)
    if status is not None:
        stmt = stmt.where(RentCharge.status == status)

    predicate = keyset_filter(RentCharge.due_date, RentCharge.id, cursor_payload, descending=False)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(RentCharge.due_date.asc(), RentCharge.id.asc()).limit(limit + 1)
    res = await db.execute(stmt)
    rows = res.all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items: list[dict] = []
    for charge, paid_total in page_rows:
        due_total = float(charge.amount_due or 0) + float(charge.late_fee_assessed or 0)
        paid_total_f = float(paid_total or 0)
        outstanding = max(due_total - paid_total_f, 0.0)
        items.append(
            {
                "charge": charge,
                "amount_paid_total": paid_total_f,
                "amount_due_total": due_total,
                "outstanding": outstanding,
            }
        )

    next_payload: dict | None = None
    if has_more and items:
        last = items[-1]["charge"]
        next_payload = keyset_payload(keyset_sort_value(last.due_date), last.id)

    return items, next_payload, count_total


async def record_rent_payment(
    db: AsyncSession,
    *,
    actor: User,
    charge_id: int,
    amount_paid: float,
    paid_at: datetime | None = None,
    payment_method: str | None = None,
    reference: str | None = None,
    notes: str | None = None,
    receipt_document_id: int | None = None,
) -> RentPayment:
    if amount_paid <= 0:
        raise BadRequestException(detail="amount_paid must be > 0")

    charge = await db.get(RentCharge, charge_id)
    if not charge:
        raise NotFoundException(detail="Rent charge not found")

    # Authorization
    if actor.role == UserRole.admin.value:
        pass
    elif actor.role == UserRole.agent.value:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=charge.owner_id)
    else:
        # Owner or tenant
        if charge.owner_id != actor.id and charge.tenant_user_id != actor.id:
            raise InsufficientPermissionsError("Not authorized to record payment for this charge")

    # Guard against overpayment: compute current outstanding before recording
    existing_paid_res = await db.execute(
        select(func.coalesce(func.sum(RentPayment.amount_paid), 0.0)).where(
            RentPayment.charge_id == charge.id
        )
    )
    existing_paid = float(existing_paid_res.scalar_one() or 0.0)
    due_total = float(charge.amount_due or 0) + float(charge.late_fee_assessed or 0)
    outstanding = max(due_total - existing_paid, 0.0)
    if outstanding <= 0:
        raise BadRequestException(detail="This charge is already fully paid")
    if amount_paid > outstanding:
        raise BadRequestException(
            detail=f"Payment amount ({amount_paid}) exceeds outstanding balance ({outstanding:.2f})"
        )

    payment = RentPayment(
        charge_id=charge.id,
        lease_id=charge.lease_id,
        property_id=charge.property_id,
        owner_id=charge.owner_id,
        tenant_user_id=charge.tenant_user_id,
        paid_at=paid_at or datetime.now(timezone.utc),
        amount_paid=float(amount_paid),
        payment_method=payment_method,
        reference=reference,
        notes=notes,
        receipt_document_id=receipt_document_id,
    )
    db.add(payment)
    await db.flush()
    await db.refresh(payment)

    # Recompute status for the charge
    res = await db.execute(
        select(func.coalesce(func.sum(RentPayment.amount_paid), 0.0)).where(
            RentPayment.charge_id == charge.id
        )
    )
    total_paid = float(res.scalar_one() or 0.0)
    due_total = float(charge.amount_due or 0) + float(charge.late_fee_assessed or 0)
    outstanding = max(due_total - total_paid, 0.0)

    today = date.today()
    if outstanding <= 0.0:
        charge.status = RentChargeStatus.paid
    elif total_paid > 0:
        # Keep partial even if overdue — partial payment is more informative
        charge.status = RentChargeStatus.partial
    elif today > charge.due_date:
        charge.status = RentChargeStatus.overdue
    else:
        charge.status = RentChargeStatus.pending

    await db.flush()
    return payment


async def list_rent_payments(
    db: AsyncSession,
    *,
    actor: User,
    as_tenant: bool = False,
    owner_id: int | None = None,
    lease_id: int | None = None,
    property_id: int | None = None,
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

    has_more = len(rows) > limit
    items = rows[:limit]

    next_payload: dict | None = None
    if has_more and items:
        last = items[-1]
        next_payload = keyset_payload(keyset_sort_value(last.paid_at), last.id)

    return items, next_payload, count_total
