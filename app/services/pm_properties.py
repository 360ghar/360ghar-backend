from __future__ import annotations

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, InsufficientPermissionsError
from app.core.logging import get_logger
from app.models.enums import ImageCategory, LeaseStatus, ManagedPropertyStatus, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property, PropertyAmenity, PropertyImage
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.schemas.property import PropertyCreate
from app.schemas.user import User as UserSchema
from app.services.pm_authz import assert_can_access_property, assert_can_manage_owner_portfolio
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


async def create_managed_property(
    db: AsyncSession,
    *,
    actor: UserSchema,
    owner_id: int,
    property_data: PropertyCreate,
    management_status: ManagedPropertyStatus = ManagedPropertyStatus.active,
    payment_due_day: int = 1,
    grace_period_days: int = 5,
    late_fee_policy: dict | None = None,
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
    await db.refresh(prop, ["images", "property_amenities"])

    return prop


async def list_managed_properties(
    db: AsyncSession,
    *,
    actor: UserSchema,
    owner_id: int | None = None,
    occupancy: str | None = None,  # occupied|vacant
    q: str | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[Property], dict | None, int | None]:
    # Resolve scope
    if actor.role == UserRole.user.value:
        owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
    if owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    stmt = select(Property).options(
        selectinload(Property.images),
        selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
    ).where(Property.is_managed)
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

    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    predicate = keyset_filter(Property.created_at, Property.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(Property.created_at.desc(), Property.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_payload = keyset_payload(keyset_sort_value(last.created_at), last.id)
    return rows, next_payload, count_total


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
    management_status: ManagedPropertyStatus | None = None,
    payment_due_day: int | None = None,
    grace_period_days: int | None = None,
    late_fee_policy: dict | None = None,
    images: list[str] | None = None,
    floor_plans: list[str] | None = None,
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

    # Handle images: delete existing and create new ones
    stored_images: list[str] = []
    if images is not None:
        # Delete existing property images (except floor plans)
        await db.execute(
            delete(PropertyImage).where(
                and_(
                    PropertyImage.property_id == property_id,
                    PropertyImage.image_category != ImageCategory.floor_plan,
                )
            )
        )
        # Create new image records
        for idx, url in enumerate(images):
            stripped = url.strip() if url else ""
            if not stripped:
                continue
            if not ValidationUtils.is_absolute_url(stripped):
                logger.warning("Skipping non-absolute image URL for property %s: %s", property_id, stripped)
                continue
            stored_images.append(stripped)
            img = PropertyImage(
                property_id=property_id,
                image_url=stripped,
                image_category=ImageCategory.others,
                display_order=idx,
                is_main_image=(idx == 0),  # First image is main
            )
            db.add(img)

    # Handle floor plans
    if floor_plans is not None:
        # Delete existing floor plan images
        await db.execute(
            delete(PropertyImage).where(
                and_(
                    PropertyImage.property_id == property_id,
                    PropertyImage.image_category == ImageCategory.floor_plan,
                )
            )
        )
        # Create new floor plan records
        for idx, url in enumerate(floor_plans):
            stripped = url.strip() if url else ""
            if not stripped:
                continue
            if not ValidationUtils.is_absolute_url(stripped):
                logger.warning("Skipping non-absolute floor plan URL for property %s: %s", property_id, stripped)
                continue
            img = PropertyImage(
                property_id=property_id,
                image_url=stripped,
                image_category=ImageCategory.floor_plan,
                display_order=idx,
                is_main_image=False,
            )
            db.add(img)

    # Update main_image_url on property from stored images
    if stored_images:
        prop.main_image_url = stored_images[0]

    prop.is_managed = True
    await db.flush()
    await db.refresh(prop, ["images"])

    return prop

