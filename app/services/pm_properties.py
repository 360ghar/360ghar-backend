from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, InsufficientPermissionsError
from app.models.enums import LeaseStatus, ManagedPropertyStatus, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.schemas.property import PropertyCreate
from app.schemas.user import User as UserSchema
from app.services.pm_authz import assert_can_access_property, assert_can_manage_owner_portfolio


async def create_managed_property(
    db: AsyncSession,
    *,
    actor: UserSchema,
    owner_id: int,
    property_data: PropertyCreate,
    management_status: ManagedPropertyStatus = ManagedPropertyStatus.active,
    payment_due_day: int = 1,
    grace_period_days: int = 5,
    late_fee_policy: Optional[dict] = None,
) -> Property:
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    if payment_due_day < 1 or payment_due_day > 28:
        raise BadRequestException(detail="payment_due_day must be between 1 and 28")
    if grace_period_days < 0:
        raise BadRequestException(detail="grace_period_days must be >= 0")

    property_dict = property_data.model_dump(exclude_unset=True)
    property_dict["owner_id"] = owner_id
    property_dict["is_managed"] = True
    property_dict["management_status"] = management_status
    property_dict["payment_due_day"] = payment_due_day
    property_dict["grace_period_days"] = grace_period_days
    property_dict["late_fee_policy"] = late_fee_policy

    # Create WKT for PostGIS location
    if "latitude" in property_dict and "longitude" in property_dict:
        lat = property_dict.get("latitude")
        lon = property_dict.get("longitude")
        if lat is not None and lon is not None:
            property_dict["location"] = f"SRID=4326;POINT({lon} {lat})"

    prop = Property(**property_dict)
    db.add(prop)
    await db.flush()
    await db.refresh(prop, ["images"])

    return prop


async def list_managed_properties(
    db: AsyncSession,
    *,
    actor: UserSchema,
    owner_id: Optional[int] = None,
    occupancy: Optional[str] = None,  # occupied|vacant
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Property]:
    # Resolve scope
    if actor.role == UserRole.user.value:
        owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
    if owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    stmt = select(Property).options(selectinload(Property.images)).where(Property.is_managed == True)
    if owner_id is not None:
        stmt = stmt.where(Property.owner_id == owner_id)

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Property.title.ilike(like), Property.full_address.ilike(like)))

    # Occupancy filter is derived from active lease existence
    if occupancy:
        occupancy_norm = occupancy.lower().strip()
        active_lease_exists = exists(
            select(1).where(and_(Lease.property_id == Property.id, Lease.status == LeaseStatus.active))
        )
        if occupancy_norm == "occupied":
            stmt = stmt.where(active_lease_exists)
        elif occupancy_norm == "vacant":
            stmt = stmt.where(~active_lease_exists)
        else:
            raise BadRequestException(detail="occupancy must be one of: occupied, vacant")

    stmt = stmt.order_by(Property.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_managed_property_detail(
    db: AsyncSession,
    *,
    actor: UserSchema,
    property_id: int,
) -> dict:
    prop = await assert_can_access_property(db, actor=actor, property_id=property_id, allow_tenant=True)

    active_lease_stmt = (
        select(Lease)
        .where(Lease.property_id == property_id, Lease.status == LeaseStatus.active)
        .order_by(Lease.created_at.desc())
        .limit(1)
    )
    lease_res = await db.execute(active_lease_stmt)
    active_lease = lease_res.scalar_one_or_none()

    return {
        "property": prop,
        "active_lease": active_lease,
    }


async def update_managed_property(
    db: AsyncSession,
    *,
    actor: UserSchema,
    property_id: int,
    management_status: Optional[ManagedPropertyStatus] = None,
    payment_due_day: Optional[int] = None,
    grace_period_days: Optional[int] = None,
    late_fee_policy: Optional[dict] = None,
) -> Property:
    prop = await assert_can_access_property(db, actor=actor, property_id=property_id)

    if management_status is not None:
        prop.management_status = management_status
    if payment_due_day is not None:
        if payment_due_day < 1 or payment_due_day > 28:
            raise BadRequestException(detail="payment_due_day must be between 1 and 28")
        prop.payment_due_day = payment_due_day
    if grace_period_days is not None:
        if grace_period_days < 0:
            raise BadRequestException(detail="grace_period_days must be >= 0")
        prop.grace_period_days = grace_period_days
    if late_fee_policy is not None:
        prop.late_fee_policy = late_fee_policy

    prop.is_managed = True
    await db.flush()
    await db.refresh(prop, ["images"])

    return prop

