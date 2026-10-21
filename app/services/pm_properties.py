from __future__ import annotations

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, InsufficientPermissionsError
from app.core.logging import get_logger
from app.models.enums import ImageCategory, ManagedPropertyStatus, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property, PropertyAmenity, PropertyImage
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.schemas.pm_property import ManagedPropertyUpdate
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.schemas.user import User as UserSchema
from app.services.pm.occupancy import OCCUPIED_LEASE_STATUSES
from app.services.pm_authz import assert_can_access_property, assert_can_manage_owner_portfolio
from app.services.property.crud import create_property as create_core_property
from app.services.property.crud import update_property as update_core_property
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
    """Create a managed property through the shared core create helper, then set the PM terms."""
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    if payment_due_day < 1 or payment_due_day > 28:
        raise BadRequestException(detail="payment_due_day must be between 1 and 28")
    if grace_period_days < 0:
        raise BadRequestException(detail="grace_period_days must be >= 0")

    created = await create_core_property(db, property_data, owner_id, actor)

    prop = await db.get(Property, created.id)
    if prop is None:
        raise BadRequestException(detail="Property could not be loaded after create")
    prop.is_managed = True
    prop.management_status = management_status
    prop.payment_due_day = payment_due_day
    prop.grace_period_days = grace_period_days
    prop.late_fee_policy = late_fee_policy
    await db.flush()
    await db.commit()
    return await _load_property(db, prop.id)


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

    stmt = (
        select(Property)
        .options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        )
        .where(Property.is_managed)
    )
    if owner_id is not None:
        stmt = stmt.where(Property.owner_id == owner_id)

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Property.title.ilike(like), Property.full_address.ilike(like)))

    # Occupancy filter is derived from an occupying lease (active or in its notice window)
    if occupancy:
        occupancy_norm = occupancy.lower().strip()
        active_lease_exists = exists(
            select(1).where(
                and_(Lease.property_id == Property.id, Lease.status.in_(OCCUPIED_LEASE_STATUSES))
            )
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
    prop = await assert_can_access_property(
        db, actor=actor, property_id=property_id, allow_tenant=True
    )

    active_lease_stmt = (
        select(Lease)
        .where(Lease.property_id == property_id, Lease.status.in_(OCCUPIED_LEASE_STATUSES))
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
    body: ManagedPropertyUpdate,
) -> Property:
    """Apply a PATCH. Core listing fields go through the shared core update; PM fields are set here.

    Only keys in ``body.model_fields_set`` change. An explicit null clears a nullable field.
    """
    await assert_can_access_property(db, actor=actor, property_id=property_id)
    sent = body.model_fields_set

    core_names = sent & set(PropertyUpdate.model_fields)
    if core_names:
        core_update = PropertyUpdate(**{name: getattr(body, name) for name in core_names})
        await update_core_property(db, property_id, core_update, actor)

    prop = await db.get(Property, property_id, populate_existing=True)
    if prop is None:
        raise BadRequestException(detail="Property not found after update")

    # management_status, payment_due_day and grace_period_days are NOT NULL: the schema rejects null.
    if body.management_status is not None and "management_status" in sent:
        prop.management_status = body.management_status
    if body.payment_due_day is not None and "payment_due_day" in sent:
        prop.payment_due_day = body.payment_due_day
    if body.grace_period_days is not None and "grace_period_days" in sent:
        prop.grace_period_days = body.grace_period_days
    if "late_fee_policy" in sent:
        prop.late_fee_policy = body.late_fee_policy

    # Images and floor plans are replaced as a whole. An explicit null clears them.
    if "images" in sent:
        await _replace_images(db, property_id, body.images or [], ImageCategory.others)
    if "floor_plans" in sent:
        await _replace_images(db, property_id, body.floor_plans or [], ImageCategory.floor_plan)

    prop.is_managed = True
    await db.flush()
    return await _load_property(db, property_id)


async def _load_property(db: AsyncSession, property_id: int) -> Property:
    """Reload a property with the relations the response needs. Avoids lazy loads after a write."""
    stmt = (
        select(Property)
        .options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        )
        .where(Property.id == property_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _replace_images(
    db: AsyncSession,
    property_id: int,
    urls: list[str],
    category: ImageCategory,
) -> None:
    """Replace one image category. Non-absolute URLs are skipped with a warning."""
    if category == ImageCategory.floor_plan:
        condition = PropertyImage.image_category == ImageCategory.floor_plan
    else:
        condition = PropertyImage.image_category != ImageCategory.floor_plan
    await db.execute(
        delete(PropertyImage).where(and_(PropertyImage.property_id == property_id, condition))
    )

    kept = 0
    for url in urls:
        stripped = url.strip() if url else ""
        if not stripped:
            continue
        if not ValidationUtils.is_absolute_url(stripped):
            logger.warning(
                "Skipping non-absolute image URL for property %s: %s", property_id, stripped
            )
            continue
        db.add(
            PropertyImage(
                property_id=property_id,
                image_url=stripped,
                image_category=category,
                display_order=kept,
                is_main_image=(category == ImageCategory.others and kept == 0),
            )
        )
        kept += 1

    if category == ImageCategory.others:
        first = next((u.strip() for u in urls if u and u.strip()), None)
        if first and ValidationUtils.is_absolute_url(first):
            prop_row = await db.get(Property, property_id)
            if prop_row is not None:
                prop_row.main_image_url = first
