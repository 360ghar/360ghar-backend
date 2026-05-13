"""Shared property tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InsufficientPermissionsError,
    PropertyNotFoundException,
)
from app.core.logging import get_logger
from app.mcp.utils import (
    serialize_lease,
    serialize_property_basic,
    serialize_property_full,
    serialize_user_basic,
)
from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType
from app.models.pm_leases import Lease
from app.models.properties import PropertyAmenity
from app.models.users import User as UserModel
from app.schemas.property import PropertyCreate
from app.schemas.user import User as UserSchema
from app.services.pm_authz import assert_can_access_property
from app.services.pm_properties import (
    create_managed_property,
    get_managed_property_detail,
    list_managed_properties,
)
from app.services.user import get_user_by_id

logger = get_logger(__name__)

TOOL_OPS_NOT_FOUND = "NOT_FOUND"
TOOL_OPS_FORBIDDEN = "FORBIDDEN"
TOOL_OPS_OPERATION_FAILED = "OPERATION_FAILED"
TOOL_OPS_INVALID_INPUT = "INVALID_INPUT"


def _user_schema(user) -> UserSchema:
    return UserSchema.model_validate(user)


async def enrich_properties_with_lease_info(
    db: AsyncSession,
    properties: list,
) -> tuple[list[dict], dict]:
    """Enrich serialized properties with active lease tenant data.

    Returns:
        (items, stats) where items are serialized property dicts with
        ``has_active_lease`` / ``tenant_name`` fields, and stats contains
        occupancy/income aggregates.
    """
    property_ids = [p.id for p in properties]
    active_lease_tenants: dict[int, str | None] = {}

    if property_ids:
        lease_stmt = (
            select(Lease.property_id, UserModel.full_name)
            .join(UserModel, UserModel.id == Lease.tenant_user_id)
            .where(Lease.property_id.in_(property_ids), Lease.status == LeaseStatus.active)
        )
        lease_result = await db.execute(lease_stmt)
        for prop_id, tenant_name in lease_result.all():
            if prop_id not in active_lease_tenants:
                active_lease_tenants[prop_id] = tenant_name

    items: list[dict[str, Any]] = []
    for prop in properties:
        item = serialize_property_basic(prop)
        tenant_name = active_lease_tenants.get(prop.id)
        item["has_active_lease"] = prop.id in active_lease_tenants
        if tenant_name:
            item["tenant_name"] = tenant_name
        items.append(item)

    occupied = sum(1 for p in items if p.get("has_active_lease"))
    vacant = len(items) - occupied
    total_monthly_income = sum(
        float(p.get("monthly_rent") or 0) for p in items if p.get("has_active_lease")
    )

    stats = {
        "total_properties": len(items),
        "occupied": occupied,
        "vacant": vacant,
        "total_monthly_income": total_monthly_income,
    }

    return items, stats


async def list_properties_enriched(
    db: AsyncSession,
    *,
    actor,
    owner_id: int,
    occupancy: str | None = None,
    q: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """List managed properties with active-lease enrichment."""
    limit = min(max(1, limit), 100)
    actor_schema = _user_schema(actor)

    properties = await list_managed_properties(
        db,
        actor=actor_schema,
        owner_id=owner_id,
        occupancy=occupancy,
        q=q,
        limit=limit,
        offset=(page - 1) * limit,
    )

    items, stats = await enrich_properties_with_lease_info(db, properties)

    return {
        "items": items,
        "total": len(items),
        "page": page,
        "limit": limit,
        "stats": stats,
    }


async def create_property(
    db: AsyncSession,
    *,
    actor,
    owner_id: int,
    property_type: str,
    purpose: str,
    title: str,
    full_address: str,
    city: str,
    locality: str,
    latitude: float,
    longitude: float,
    base_price: float,
    description: str | None = None,
    sub_locality: str | None = None,
    pincode: str | None = None,
    state: str | None = None,
    monthly_rent: float | None = None,
    daily_rate: float | None = None,
    security_deposit: float | None = None,
    maintenance_charges: float | None = None,
    area_sqft: float | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    balconies: int | None = None,
    parking_spaces: int | None = None,
    floor_number: int | None = None,
    total_floors: int | None = None,
    max_occupancy: int | None = None,
    minimum_stay_days: int | None = None,
    main_image_url: str | None = None,
    virtual_tour_url: str | None = None,
    amenity_ids: list[int] | None = None,
    payment_due_day: int | None = None,
    grace_period_days: int | None = None,
) -> dict:
    """Create a managed property listing."""
    try:
        prop_type = PropertyType(property_type.lower())
    except ValueError:
        return {"error": True, "message": f"Invalid property_type: {property_type}"}

    try:
        prop_purpose = PropertyPurpose(purpose.lower())
    except ValueError:
        return {"error": True, "message": f"Invalid purpose: {purpose}"}

    actor_schema = _user_schema(actor)

    property_data = PropertyCreate(
        title=title,
        description=description,
        property_type=prop_type,
        purpose=prop_purpose,
        full_address=full_address,
        city=city,
        locality=locality,
        sub_locality=sub_locality,
        pincode=pincode,
        state=state,
        latitude=latitude,
        longitude=longitude,
        base_price=base_price,
        monthly_rent=monthly_rent,
        daily_rate=daily_rate,
        security_deposit=security_deposit,
        maintenance_charges=maintenance_charges,
        area_sqft=area_sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        balconies=balconies,
        parking_spaces=parking_spaces,
        floor_number=floor_number,
        total_floors=total_floors,
        max_occupancy=max_occupancy,
        minimum_stay_days=minimum_stay_days,
        main_image_url=main_image_url,
        virtual_tour_url=virtual_tour_url,
    )

    extra = {}
    if payment_due_day is not None:
        extra["payment_due_day"] = payment_due_day
    if grace_period_days is not None:
        extra["grace_period_days"] = grace_period_days

    prop = await create_managed_property(
        db, actor=actor_schema, owner_id=owner_id, property_data=property_data, **extra  # type: ignore[arg-type]
    )

    # Add amenities if provided
    if amenity_ids:
        for amenity_id in amenity_ids:
            db.add(PropertyAmenity(property_id=prop.id, amenity_id=amenity_id))
        await db.flush()
        await db.refresh(prop)

    await db.commit()

    return {
        "message": "Property created successfully",
        "property": serialize_property_full(prop),
    }


async def get_property_detail(
    db: AsyncSession,
    *,
    actor,
    property_id: int,
    include_owner_tenant: bool = False,
) -> dict:
    """Get detailed property information with optional owner/tenant enrichment."""
    actor_schema = _user_schema(actor)

    try:
        result = await get_managed_property_detail(db, actor=actor_schema, property_id=property_id)
    except PropertyNotFoundException:
        return {"error": True, "code": TOOL_OPS_NOT_FOUND, "message": f"Property {property_id} not found."}
    except InsufficientPermissionsError:
        return {"error": True, "code": TOOL_OPS_FORBIDDEN, "message": "You do not have access to this property."}

    prop = result["property"]
    active_lease = result.get("active_lease")

    response = {
        "property": serialize_property_full(prop),
        "active_lease": serialize_lease(active_lease) if active_lease else None,
    }

    if include_owner_tenant:
        if prop.owner_id:
            owner = await get_user_by_id(db, prop.owner_id)
            if owner:
                response["owner"] = serialize_user_basic(owner)
        if active_lease and active_lease.tenant_user_id:
            tenant = await get_user_by_id(db, active_lease.tenant_user_id)
            if tenant:
                response["tenant"] = serialize_user_basic(tenant)

    return response


async def update_property_fields(
    db: AsyncSession,
    *,
    actor,
    property_id: int,
    updates: dict[str, Any],
) -> dict:
    """Update specific fields on a property."""
    actor_schema = _user_schema(actor)

    prop = await assert_can_access_property(db, actor=actor_schema, property_id=property_id)

    for field, value in updates.items():
        if value is not None:
            setattr(prop, field, value)

    await db.flush()
    await db.refresh(prop)
    await db.commit()

    return {
        "message": "Property updated successfully",
        "property": serialize_property_basic(prop),
    }


async def toggle_property_availability(
    db: AsyncSession,
    *,
    actor,
    property_id: int,
    is_available: bool,
) -> dict:
    """Toggle a property's availability status."""
    actor_schema = _user_schema(actor)

    prop = await assert_can_access_property(db, actor=actor_schema, property_id=property_id)
    prop.is_available = is_available
    await db.flush()
    await db.commit()

    status = "available" if is_available else "unavailable"
    return {"message": f"Property marked as {status}", "property_id": property_id}
