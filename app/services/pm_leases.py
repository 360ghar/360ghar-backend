from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, InsufficientPermissionsError
from app.models.enums import LeaseStatus, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.services.pm_authz import (
    assert_can_access_lease,
    assert_can_access_property,
    assert_can_manage_owner_portfolio,
)


async def create_lease(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int,
    property_id: int,
    tenant_user_id: int | None,
    tenant_name: str | None,
    tenant_phone: str | None,
    tenant_email: str | None,
    status: LeaseStatus = LeaseStatus.draft,
    start_date: date,
    end_date: date,
    monthly_rent: float,
    security_deposit: float,
    late_fee_amount: float | None = None,
    late_fee_percentage: float | None = None,
    grace_period_days: int = 5,
    payment_due_day: int = 1,
    lease_terms: dict | None = None,
    special_clauses: str | None = None,
    lease_document_id: int | None = None,
) -> Lease:
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
    prop = await assert_can_access_property(db, actor=actor, property_id=property_id)

    if prop.owner_id != owner_id and actor.role != UserRole.admin.value:
        raise BadRequestException(detail="property_id does not belong to owner_id")

    if end_date <= start_date:
        raise BadRequestException(detail="end_date must be after start_date")

    # Prevent multiple active leases for the same property.
    if status == LeaseStatus.active:
        existing = await db.execute(
            select(Lease.id).where(
                Lease.property_id == property_id,
                Lease.status == LeaseStatus.active,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise BadRequestException(detail="Property already has an active lease")

    lease = Lease(
        property_id=property_id,
        owner_id=owner_id,
        tenant_user_id=tenant_user_id,
        tenant_name=tenant_name,
        tenant_phone=tenant_phone,
        tenant_email=tenant_email,
        status=status,
        start_date=start_date,
        end_date=end_date,
        monthly_rent=monthly_rent,
        security_deposit=security_deposit,
        late_fee_amount=late_fee_amount,
        late_fee_percentage=late_fee_percentage,
        grace_period_days=grace_period_days,
        payment_due_day=payment_due_day,
        lease_terms=lease_terms,
        special_clauses=special_clauses,
        lease_document_id=lease_document_id,
    )
    try:
        async with db.begin_nested():
            db.add(lease)
            await db.flush()
    except IntegrityError:
        raise BadRequestException(detail="Property already has an active lease (concurrent conflict)") from None
    await db.refresh(lease)

    # Mark property as managed and set convenience pointers when lease is active.
    if getattr(prop, "is_managed", False) is False:
        prop.is_managed = True
    if status == LeaseStatus.active:
        prop.current_lease_id = lease.id
        prop.current_tenant_id = tenant_user_id
    await db.flush()
    return lease


async def list_leases(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    property_id: int | None = None,
    tenant_user_id: int | None = None,
    status: LeaseStatus | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[Lease], dict | None, int | None]:
    # Resolve scope
    if actor.role == UserRole.user.value:
        # Owner list context
        owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
    if owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    stmt = select(Lease).options(
        selectinload(Lease.property).selectinload(Property.images),
        selectinload(Lease.tenant_user),
    )
    if owner_id is not None:
        stmt = stmt.where(Lease.owner_id == owner_id)
    if property_id is not None:
        stmt = stmt.where(Lease.property_id == property_id)
    if tenant_user_id is not None:
        stmt = stmt.where(Lease.tenant_user_id == tenant_user_id)
    if status is not None:
        stmt = stmt.where(Lease.status == status)

    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    predicate = keyset_filter(Lease.created_at, Lease.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(Lease.created_at.desc(), Lease.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_payload = keyset_payload(keyset_sort_value(last.created_at), last.id)
    return rows, next_payload, count_total


async def get_lease(db: AsyncSession, *, actor: User, lease_id: int) -> Lease:
    return await assert_can_access_lease(db, actor=actor, lease_id=lease_id)


async def upload_signed_lease(
    db: AsyncSession,
    *,
    actor: User,
    lease_id: int,
    lease_document_id: int,
    signed_by_owner: bool = True,
    signed_by_tenant: bool = False,
) -> Lease:
    lease = await assert_can_access_lease(db, actor=actor, lease_id=lease_id)

    lease.lease_document_id = lease_document_id
    now = datetime.now(timezone.utc)
    if signed_by_owner:
        lease.signed_by_owner_at = now
    if signed_by_tenant:
        lease.signed_by_tenant_at = now

    await db.flush()
    await db.refresh(lease)
    return lease


async def terminate_lease(
    db: AsyncSession,
    *,
    actor: User,
    lease_id: int,
    termination_date: date | None = None,
    reason: str | None = None,
) -> Lease:
    lease = await assert_can_access_lease(db, actor=actor, lease_id=lease_id)

    # Already terminated or expired - no-op
    if lease.status in {LeaseStatus.terminated, LeaseStatus.expired}:
        return lease

    # Only active or expiring_soon leases can be terminated
    # Draft leases should be deleted, not terminated
    # Renewed leases are historical records
    if lease.status not in {LeaseStatus.active, LeaseStatus.expiring_soon, LeaseStatus.pending_signature}:
        raise BadRequestException(
            detail=f"Cannot terminate a lease with status '{lease.status.value}'. "
            f"Only active, expiring_soon, or pending_signature leases can be terminated."
        )

    lease.status = LeaseStatus.terminated
    if termination_date is not None:
        lease.termination_date = termination_date
    if reason is not None:
        lease.termination_reason = reason
    await db.flush()

    prop = await db.get(Property, lease.property_id)
    if prop and prop.current_lease_id == lease.id:
        prop.current_lease_id = None
        prop.current_tenant_id = None
        await db.flush()

    await db.refresh(lease)
    return lease


async def renew_lease(
    db: AsyncSession,
    *,
    actor: User,
    lease_id: int,
    start_date: date,
    end_date: date,
    monthly_rent: float | None = None,
    security_deposit: float | None = None,
    make_active: bool = False,
) -> Lease:
    old = await assert_can_access_lease(db, actor=actor, lease_id=lease_id)

    if end_date <= start_date:
        raise BadRequestException(detail="end_date must be after start_date")

    new_status = LeaseStatus.active if make_active else LeaseStatus.draft

    # Prevent creating a second active lease for the same property when renewing
    if new_status == LeaseStatus.active:
        existing_active = await db.execute(
            select(Lease.id).where(
                Lease.property_id == old.property_id,
                Lease.status == LeaseStatus.active,
                Lease.id != old.id,
            )
        )
        if existing_active.scalar_one_or_none() is not None:
            raise BadRequestException(detail="Property already has another active lease")

    new = Lease(
        property_id=old.property_id,
        owner_id=old.owner_id,
        tenant_user_id=old.tenant_user_id,
        tenant_name=old.tenant_name,
        tenant_phone=old.tenant_phone,
        tenant_email=old.tenant_email,
        status=new_status,
        start_date=start_date,
        end_date=end_date,
        monthly_rent=float(monthly_rent if monthly_rent is not None else old.monthly_rent),
        security_deposit=float(
            security_deposit if security_deposit is not None else old.security_deposit
        ),
        late_fee_amount=old.late_fee_amount,
        late_fee_percentage=old.late_fee_percentage,
        grace_period_days=old.grace_period_days,
        payment_due_day=old.payment_due_day,
        lease_terms=old.lease_terms,
        special_clauses=old.special_clauses,
    )
    db.add(new)
    old.status = LeaseStatus.renewed
    await db.flush()
    await db.refresh(new)

    if new_status == LeaseStatus.active:
        prop = await db.get(Property, new.property_id)
        if prop:
            prop.is_managed = True
            prop.current_lease_id = new.id
            prop.current_tenant_id = new.tenant_user_id
            await db.flush()

    return new

