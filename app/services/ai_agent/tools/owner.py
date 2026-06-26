"""
Owner and agent/owner property, lease, rent, and maintenance tools.

Includes both user-facing owner tools and admin/agent tools for managing
owner resources — properties, leases, rent collection, and maintenance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic_ai import RunContext
from sqlalchemy import func, select

from app.core.logging import get_logger
from app.mcp.utils import (
    serialize_lease,
    serialize_maintenance_request,
    serialize_property_basic,
    serialize_property_full,
)
from app.services.ai_agent.tools.helpers import AgentDeps, _user_schema
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


# ============================================================================
# USER TOOLS — Owner Property Management
# ============================================================================

async def owner_properties_list(
    ctx: RunContext[AgentDeps],
    page: int = 1,
    limit: int = 20,
    occupancy: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """List all properties owned by the current user with occupancy stats."""
    from app.models.enums import LeaseStatus
    from app.models.pm_leases import Lease
    from app.models.users import User as UserModel
    from app.services.pm_properties import list_managed_properties

    limit = min(max(1, limit), 100)
    db, user = ctx.deps.db, ctx.deps.user
    actor = _user_schema(user)

    properties, _next, _total = await list_managed_properties(
        db, actor=actor, owner_id=user.id, occupancy=occupancy, q=q,
        cursor_payload={}, limit=limit,
    )

    property_ids = [p.id for p in properties]
    active_lease_tenants: dict[int, str | None] = {}
    if property_ids:
        stmt = (
            select(Lease.property_id, UserModel.full_name)
            .join(UserModel, UserModel.id == Lease.tenant_user_id)
            .where(Lease.property_id.in_(property_ids), Lease.status == LeaseStatus.active)
        )
        for prop_id, tenant_name in (await db.execute(stmt)).all():
            if prop_id not in active_lease_tenants:
                active_lease_tenants[prop_id] = tenant_name

    items = []
    for prop in properties:
        item = serialize_property_basic(prop)
        tenant_name = active_lease_tenants.get(prop.id)
        item["has_active_lease"] = prop.id in active_lease_tenants
        if tenant_name:
            item["tenant_name"] = tenant_name
        items.append(item)

    occupied = sum(1 for p in items if p.get("has_active_lease"))
    return {
        "items": items,
        "total": len(items),
        "page": page,
        "stats": {
            "total_properties": len(items),
            "occupied": occupied,
            "vacant": len(items) - occupied,
            "total_monthly_income": sum(
                float(p.get("monthly_rent") or 0)
                for p in items if p.get("has_active_lease")
            ),
        },
    }


async def owner_properties_create(
    ctx: RunContext[AgentDeps],
    title: str,
    property_type: str,
    purpose: str,
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
) -> dict[str, Any]:
    """Create a new property listing for the current user.

    Note: For rent/flatmate/PG listings, ``monthly_rent`` must be a positive
    number. The schema validator will reject the request otherwise.
    """
    from app.models.enums import PropertyPurpose, PropertyType
    from app.schemas.property import PropertyCreate
    from app.services.pm_properties import create_managed_property

    db, user = ctx.deps.db, ctx.deps.user
    prop_type = PropertyType(property_type.lower())
    prop_purpose = PropertyPurpose(purpose.lower())

    if main_image_url is not None and not ValidationUtils.is_absolute_url(main_image_url):
        logger.warning("Non-absolute main_image_url in AI agent owner_properties_create: %s", main_image_url)
    if virtual_tour_url is not None and not ValidationUtils.is_absolute_url(virtual_tour_url):
        logger.warning("Non-absolute virtual_tour_url in AI agent owner_properties_create: %s", virtual_tour_url)

    data = PropertyCreate(
        title=title, description=description, property_type=prop_type,
        purpose=prop_purpose, full_address=full_address, city=city,
        locality=locality, sub_locality=sub_locality, pincode=pincode,
        state=state, latitude=latitude, longitude=longitude,
        base_price=base_price, monthly_rent=monthly_rent,
        daily_rate=daily_rate, security_deposit=security_deposit,
        maintenance_charges=maintenance_charges, area_sqft=area_sqft,
        bedrooms=bedrooms, bathrooms=bathrooms, balconies=balconies,
        parking_spaces=parking_spaces, floor_number=floor_number,
        total_floors=total_floors, max_occupancy=max_occupancy,
        minimum_stay_days=minimum_stay_days, main_image_url=main_image_url,
        virtual_tour_url=virtual_tour_url,
    )
    prop = await create_managed_property(db, actor=_user_schema(user), owner_id=user.id,
                                         property_data=data)
    await db.commit()
    return {"message": "Property created successfully", "property": serialize_property_basic(prop)}


async def owner_properties_get(
    ctx: RunContext[AgentDeps],
    property_id: int,
) -> dict[str, Any]:
    """Get detailed information about one of the user's properties."""
    from app.services.pm_properties import get_managed_property_detail

    db, user = ctx.deps.db, ctx.deps.user
    result = await get_managed_property_detail(db, actor=_user_schema(user),
                                               property_id=property_id)
    prop = result["property"]
    active_lease = result.get("active_lease")
    return {
        "property": serialize_property_full(prop),
        "active_lease": serialize_lease(active_lease) if active_lease else None,
    }


async def owner_properties_update(
    ctx: RunContext[AgentDeps],
    property_id: int,
    title: str | None = None,
    description: str | None = None,
    base_price: float | None = None,
    monthly_rent: float | None = None,
    daily_rate: float | None = None,
    is_available: bool | None = None,
    max_occupancy: int | None = None,
    main_image_url: str | None = None,
) -> dict[str, Any]:
    """Update one of the user's properties (partial update)."""
    from app.services.pm_authz import assert_can_access_property

    db, user = ctx.deps.db, ctx.deps.user
    prop = await assert_can_access_property(db, actor=_user_schema(user),
                                            property_id=property_id)

    if main_image_url is not None and not ValidationUtils.is_absolute_url(main_image_url):
        logger.warning("Non-absolute main_image_url in AI agent owner_properties_update: %s", main_image_url)

    updates = {
        "title": title, "description": description, "base_price": base_price,
        "monthly_rent": monthly_rent, "daily_rate": daily_rate,
        "is_available": is_available, "max_occupancy": max_occupancy,
        "main_image_url": main_image_url,
    }
    for field, value in updates.items():
        if value is not None:
            setattr(prop, field, value)
    await db.flush()
    await db.refresh(prop)
    await db.commit()
    return {"message": "Property updated successfully", "property": serialize_property_basic(prop)}


async def owner_properties_toggle_availability(
    ctx: RunContext[AgentDeps],
    property_id: int,
    is_available: bool,
) -> dict[str, Any]:
    """Toggle a property's availability status."""
    from app.services.pm_authz import assert_can_access_property

    db, user = ctx.deps.db, ctx.deps.user
    prop = await assert_can_access_property(db, actor=_user_schema(user),
                                            property_id=property_id)
    prop.is_available = is_available
    await db.flush()
    await db.commit()
    status = "available" if is_available else "unavailable"
    return {"message": f"Property marked as {status}", "property_id": property_id}


# ============================================================================
# ADMIN TOOLS — Agent Property Management
# ============================================================================

async def agent_properties_list(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    page: int = 1,
    limit: int = 50,
    occupancy: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """List managed properties (agents see assigned owners; admins see all)."""
    from app.services.pm_properties import list_managed_properties

    db, user = ctx.deps.db, ctx.deps.user
    limit = min(max(1, limit), 100)
    actor = _user_schema(user)
    properties, _next, _total = await list_managed_properties(
        db, actor=actor, owner_id=owner_id, occupancy=occupancy, q=q,
        cursor_payload={}, limit=limit,
    )
    items = [serialize_property_basic(p) for p in properties]
    return {"items": items, "total": len(items), "page": page}


async def agent_properties_get(
    ctx: RunContext[AgentDeps],
    property_id: int,
) -> dict[str, Any]:
    """Get managed property details including owner, lease, and tenant info."""
    from app.services.pm_properties import get_managed_property_detail

    db, user = ctx.deps.db, ctx.deps.user
    result = await get_managed_property_detail(db, actor=_user_schema(user),
                                               property_id=property_id)
    prop = result["property"]
    lease = result.get("active_lease")
    return {
        "property": serialize_property_full(prop),
        "active_lease": serialize_lease(lease) if lease else None,
    }


async def agent_properties_create_for_owner(
    ctx: RunContext[AgentDeps],
    owner_id: int,
    title: str,
    property_type: str,
    purpose: str,
    full_address: str,
    city: str,
    locality: str,
    latitude: float,
    longitude: float,
    base_price: float,
    description: str | None = None,
    monthly_rent: float | None = None,
    area_sqft: float | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
) -> dict[str, Any]:
    """Create a property listing on behalf of an owner."""
    from app.models.enums import PropertyPurpose, PropertyType
    from app.schemas.property import PropertyCreate
    from app.services.pm_properties import create_managed_property

    db, user = ctx.deps.db, ctx.deps.user
    data = PropertyCreate(
        title=title, description=description,
        property_type=PropertyType(property_type.lower()),
        purpose=PropertyPurpose(purpose.lower()),
        full_address=full_address, city=city, locality=locality,
        latitude=latitude, longitude=longitude, base_price=base_price,
        monthly_rent=monthly_rent, area_sqft=area_sqft,
        bedrooms=bedrooms, bathrooms=bathrooms,
    )
    prop = await create_managed_property(db, actor=_user_schema(user), owner_id=owner_id,
                                         property_data=data)
    await db.commit()
    return {"message": "Property created for owner", "property": serialize_property_basic(prop)}


async def agent_properties_verify(
    ctx: RunContext[AgentDeps],
    property_id: int,
    is_verified: bool,
    verification_notes: str | None = None,
) -> dict[str, Any]:
    """Mark a property as verified or unverified."""
    from app.services.pm_authz import assert_can_access_property

    db, user = ctx.deps.db, ctx.deps.user
    prop = await assert_can_access_property(db, actor=_user_schema(user),
                                            property_id=property_id)
    preferences = dict(prop.listing_preferences or {})
    preferences["verification"] = {
        "is_verified": is_verified,
        "notes": verification_notes,
        "verified_by": user.id,
    }
    prop.listing_preferences = preferences
    await db.flush()
    await db.commit()
    return {"message": "Property verification updated", "property_id": property_id,
            "is_verified": is_verified}


# ============================================================================
# ADMIN TOOLS — Lease Management
# ============================================================================

async def agent_leases_list(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    property_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List leases, filterable by owner, property, and status."""
    from app.models.enums import LeaseStatus
    from app.models.pm_leases import Lease

    db = ctx.deps.db
    limit = min(max(1, limit), 100)
    stmt = select(Lease)
    if owner_id:
        stmt = stmt.where(Lease.owner_id == owner_id)
    if property_id:
        stmt = stmt.where(Lease.property_id == property_id)
    if status:
        stmt = stmt.where(Lease.status == LeaseStatus(status.lower()))
    stmt = stmt.order_by(Lease.created_at.desc()).offset((page - 1) * limit).limit(limit)
    leases = (await db.execute(stmt)).scalars().all()
    return {"items": [serialize_lease(lease) for lease in leases], "total": len(leases), "page": page}


async def agent_leases_create(
    ctx: RunContext[AgentDeps],
    property_id: int,
    tenant_user_id: int,
    start_date: str,
    end_date: str,
    monthly_rent: float,
    security_deposit: float = 0,
    payment_due_day: int = 1,
    grace_period_days: int = 5,
    terms: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new lease between an owner and a tenant."""
    from app.models.enums import LeaseStatus
    from app.models.pm_leases import Lease
    from app.models.properties import Property
    from app.services.user import get_user_by_id

    db, _user = ctx.deps.db, ctx.deps.user
    prop = (await db.execute(
        select(Property).where(Property.id == property_id)
    )).scalar_one_or_none()
    if not prop:
        return {"error": True, "message": f"Property {property_id} not found"}

    tenant = await get_user_by_id(db, tenant_user_id)
    if not tenant:
        return {"error": True, "message": f"Tenant user {tenant_user_id} not found"}

    lease = Lease(
        property_id=property_id, owner_id=prop.owner_id,
        tenant_user_id=tenant_user_id,
        start_date=datetime.fromisoformat(start_date).date(),
        end_date=datetime.fromisoformat(end_date).date(),
        monthly_rent=monthly_rent, security_deposit=security_deposit,
        payment_due_day=payment_due_day, grace_period_days=grace_period_days,
        terms=terms, notes=notes, status=LeaseStatus.active,
    )
    db.add(lease)
    await db.flush()
    await db.refresh(lease)
    await db.commit()
    return {"message": "Lease created", "lease": serialize_lease(lease)}


async def agent_leases_terminate(
    ctx: RunContext[AgentDeps],
    lease_id: int,
    reason: str,
    termination_date: str | None = None,
) -> dict[str, Any]:
    """Terminate an active lease."""
    from app.models.enums import LeaseStatus
    from app.models.pm_leases import Lease

    db = ctx.deps.db
    lease = (await db.execute(
        select(Lease).where(Lease.id == lease_id)
    )).scalar_one_or_none()
    if not lease:
        return {"error": True, "message": f"Lease {lease_id} not found"}

    lease.status = LeaseStatus.terminated
    existing_notes = lease.notes or ""  # type: ignore[attr-defined]
    lease.notes = f"{existing_notes}\n[Terminated] {reason}".strip()  # type: ignore[attr-defined]
    await db.flush()
    await db.commit()
    return {"message": "Lease terminated", "lease_id": lease_id}


# ============================================================================
# ADMIN TOOLS — Rent Collection
# ============================================================================

async def agent_rent_list_due(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    property_id: int | None = None,
    overdue_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List rent charges, optionally filtering for overdue ones."""
    from app.models.enums import LeaseStatus
    from app.models.pm_leases import Lease

    db = ctx.deps.db
    limit = min(max(1, limit), 100)
    stmt = select(Lease).where(Lease.status == LeaseStatus.active)
    if owner_id:
        stmt = stmt.where(Lease.owner_id == owner_id)
    if property_id:
        stmt = stmt.where(Lease.property_id == property_id)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    leases = (await db.execute(stmt)).scalars().all()

    items = []
    now = datetime.now(timezone.utc)
    for lease in leases:
        due_day = getattr(lease, "payment_due_day", 1) or 1
        grace = getattr(lease, "grace_period_days", 0) or 0
        due_date = now.replace(day=min(due_day, 28))
        deadline = due_date.replace(day=min(due_day + grace, 28))
        is_overdue = now > deadline
        if overdue_only and not is_overdue:
            continue
        items.append({
            "lease_id": lease.id, "property_id": lease.property_id,
            "tenant_user_id": lease.tenant_user_id,
            "monthly_rent": float(lease.monthly_rent or 0),
            "payment_due_day": due_day,
            "is_overdue": is_overdue,
            "days_overdue": max(0, (now - deadline).days) if is_overdue else 0,
        })
    return {"items": items, "total": len(items), "page": page}


async def agent_rent_record_payment(
    ctx: RunContext[AgentDeps],
    lease_id: int,
    amount: float,
    payment_date: str,
    payment_method: str = "bank_transfer",
    transaction_reference: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a rent payment for a lease."""
    from app.models.pm_finance import RentPayment
    from app.models.pm_leases import Lease

    db = ctx.deps.db
    valid_methods = ("cash", "bank_transfer", "upi", "cheque", "online", "other")
    if payment_method not in valid_methods:
        return {"error": True, "message": f"Invalid payment method. Valid: {valid_methods}"}

    lease = (await db.execute(select(Lease).where(Lease.id == lease_id))).scalar_one_or_none()
    if not lease:
        return {"error": True, "message": f"Lease {lease_id} not found"}

    payment = RentPayment(
        lease_id=lease_id,
        amount_paid=amount,
        paid_at=datetime.fromisoformat(payment_date),
        payment_method=payment_method,
        reference=transaction_reference,
    )
    db.add(payment)
    await db.flush()
    await db.commit()
    return {"message": "Payment recorded", "payment_id": payment.id, "amount": amount}


# ============================================================================
# ADMIN TOOLS — Maintenance Management
# ============================================================================

async def agent_maintenance_list(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    property_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List maintenance requests across managed properties."""
    from app.models.pm_maintenance import MaintenanceRequest
    from app.models.properties import Property

    db = ctx.deps.db
    limit = min(max(1, limit), 100)
    stmt = select(MaintenanceRequest)
    if owner_id:
        stmt = stmt.join(Property, Property.id == MaintenanceRequest.property_id).where(
            Property.owner_id == owner_id
        )
    if property_id:
        stmt = stmt.where(MaintenanceRequest.property_id == property_id)
    # status filtering is approximate — mirrors MCP admin logic
    stmt = stmt.order_by(MaintenanceRequest.created_at.desc()).offset((page - 1) * limit).limit(limit)
    items = [serialize_maintenance_request(r) for r in (await db.execute(stmt)).scalars().all()]
    return {"items": items, "total": len(items), "page": page}


async def agent_maintenance_update_status(
    ctx: RunContext[AgentDeps],
    request_id: int,
    status: str,
    notes: str | None = None,
    scheduled_date: str | None = None,
    vendor_name: str | None = None,
    vendor_contact: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
) -> dict[str, Any]:
    """Update the status of a maintenance request."""
    from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
    from app.models.pm_maintenance import MaintenanceRequest

    db = ctx.deps.db
    req = (await db.execute(
        select(MaintenanceRequest).where(MaintenanceRequest.id == request_id)
    )).scalar_one_or_none()
    if not req:
        return {"error": True, "message": f"Maintenance request {request_id} not found"}

    status_norm = status.lower().strip()
    if status_norm == "in_progress":
        req.work_order_status = WorkOrderStatus.in_progress
    elif status_norm == "scheduled":
        req.work_order_status = WorkOrderStatus.in_progress
        if scheduled_date:
            req.scheduled_for = datetime.fromisoformat(scheduled_date)
    elif status_norm == "completed":
        req.request_status = MaintenanceRequestStatus.resolved
        req.completed_at = datetime.now(timezone.utc)
    elif status_norm == "cancelled":
        req.work_order_status = WorkOrderStatus.cancelled

    if vendor_name:
        req.vendor_name = vendor_name  # type: ignore[attr-defined]
    if vendor_contact:
        req.vendor_contact = vendor_contact  # type: ignore[attr-defined]
    if estimated_cost is not None:
        req.estimated_cost = estimated_cost
    if actual_cost is not None:
        req.actual_cost = actual_cost
    if notes:
        req.completion_notes = notes

    await db.flush()
    await db.commit()
    return {"message": f"Maintenance request updated to {status_norm}", "request_id": request_id}


# ============================================================================
# ADMIN TOOLS — Dashboard
# ============================================================================

async def agent_dashboard_overview(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
) -> dict[str, Any]:
    """Get an overview dashboard: occupancy, rent, maintenance, bookings."""
    from app.models.enums import LeaseStatus, MaintenanceRequestStatus
    from app.models.pm_leases import Lease
    from app.models.pm_maintenance import MaintenanceRequest
    from app.models.properties import Property

    db = ctx.deps.db
    prop_filter = select(Property.id)
    if owner_id:
        prop_filter = prop_filter.where(Property.owner_id == owner_id)

    total_props = (await db.execute(
        select(func.count()).select_from(prop_filter.subquery())
    )).scalar() or 0

    active_leases_count = (await db.execute(
        select(func.count(Lease.id)).where(
            Lease.status == LeaseStatus.active,
            *([Lease.owner_id == owner_id] if owner_id else []),
        )
    )).scalar() or 0

    open_maintenance = (await db.execute(
        select(func.count(MaintenanceRequest.id)).where(
            MaintenanceRequest.request_status == MaintenanceRequestStatus.open,
            *([MaintenanceRequest.owner_id == owner_id] if owner_id else []),
        )
    )).scalar() or 0

    monthly_rent = (await db.execute(
        select(func.coalesce(func.sum(Lease.monthly_rent), 0)).where(
            Lease.status == LeaseStatus.active,
            *([Lease.owner_id == owner_id] if owner_id else []),
        )
    )).scalar() or 0

    occupancy = (active_leases_count / total_props * 100) if total_props else 0

    return {
        "total_properties": total_props,
        "active_leases": active_leases_count,
        "occupancy_rate": round(occupancy, 1),
        "open_maintenance_requests": open_maintenance,
        "monthly_rent_expected": float(monthly_rent),
    }


async def admin_system_status(
    ctx: RunContext[AgentDeps],
) -> dict[str, Any]:
    """Admin system status with role and feature info."""
    user = ctx.deps.user
    return {
        "status": "operational",
        "auth": {
            "status": "authenticated",
            "user": {
                "id": user.id,
                "role": getattr(user, "role", "user"),
                "full_name": getattr(user, "full_name", None),
            },
        },
        "access_level": "full" if getattr(user, "role", "") == "admin" else "agent_scope",
    }
