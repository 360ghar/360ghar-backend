"""
Owner and agent/owner property, lease, rent, and maintenance tools.

Includes both user-facing owner tools and admin/agent tools for managing
owner resources — properties, leases, rent collection, and maintenance.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Literal

from pydantic_ai import RunContext

from app.core.logging import get_logger
from app.mcp.tool_ops import (
    MaintenanceStatusLabel,
    compute_portfolio_stats,
    compute_rent_due_items,
    create_lease,
    enrich_properties_with_lease_info,
    list_leases,
    list_maintenance_requests,
    list_properties_enriched,
    list_properties_filters,
    record_lease_rent_payment,
    toggle_property_availability,
    update_maintenance_status,
    update_property_fields,
)
from app.mcp.utils import (
    serialize_lease,
    serialize_property_basic,
    serialize_property_full,
    serialize_rent_payment,
)
from app.models.enums import (
    LeaseStatus,
    PaymentMethod,
    PropertyPurpose,
    PropertyType,
)
from app.schemas.pagination import decode_cursor, encode_cursor
from app.services.ai_agent.tools.helpers import AgentDeps, _user_schema, owner_scope
from app.services.property import attach_owner_agents
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


# ============================================================================
# USER TOOLS — Owner Property Management
# ============================================================================


async def owner_properties_list(
    ctx: RunContext[AgentDeps],
    occupancy: Literal["occupied", "vacant"] | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List the current user's properties, with occupancy and portfolio stats."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    filters = list_properties_filters(owner_id=user.id, occupancy=occupancy, q=q)
    return await list_properties_enriched(
        db,
        actor=user,
        owner_id=user.id,
        occupancy=occupancy,
        q=q,
        cursor_payload=decode_cursor(cursor, filters) if cursor else {},
        limit=limit,
        include_total=include_total,
    )


async def owner_properties_create(
    ctx: RunContext[AgentDeps],
    title: str,
    property_type: PropertyType,
    purpose: PropertyPurpose,
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
    from app.schemas.property import PropertyCreate
    from app.services.pm_properties import create_managed_property

    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    prop_type = property_type
    prop_purpose = purpose

    if main_image_url is not None and not ValidationUtils.is_absolute_url(main_image_url):
        logger.warning(
            "Non-absolute main_image_url in AI agent owner_properties_create: %s", main_image_url
        )
    if virtual_tour_url is not None and not ValidationUtils.is_absolute_url(virtual_tour_url):
        logger.warning(
            "Non-absolute virtual_tour_url in AI agent owner_properties_create: %s",
            virtual_tour_url,
        )

    data = PropertyCreate(
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
        minimum_stay_days=minimum_stay_days if minimum_stay_days is not None else 1,
        main_image_url=main_image_url,
        virtual_tour_url=virtual_tour_url,
    )
    prop = await create_managed_property(
        db, actor=_user_schema(user), owner_id=user.id, property_data=data
    )
    await db.commit()
    return {"message": "Property created successfully", "property": serialize_property_basic(prop)}


async def owner_properties_get(
    ctx: RunContext[AgentDeps],
    property_id: int,
) -> dict[str, Any]:
    """Get detailed information about one of the user's properties."""
    from app.services.pm_properties import get_managed_property_detail

    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    result = await get_managed_property_detail(
        db, actor=_user_schema(user), property_id=property_id
    )
    prop = result["property"]
    active_lease = result.get("active_lease")
    await attach_owner_agents(db, [prop])
    return {
        "property": serialize_property_full(prop, viewer=user),
        "active_lease": serialize_lease(active_lease, user) if active_lease else None,
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
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None

    if main_image_url is not None and not ValidationUtils.is_absolute_url(main_image_url):
        logger.warning(
            "Non-absolute main_image_url in AI agent owner_properties_update: %s", main_image_url
        )

    return await update_property_fields(
        db,
        actor=user,
        property_id=property_id,
        updates={
            "title": title,
            "description": description,
            "base_price": base_price,
            "monthly_rent": monthly_rent,
            "daily_rate": daily_rate,
            "is_available": is_available,
            "max_occupancy": max_occupancy,
            "main_image_url": main_image_url,
        },
    )


async def owner_properties_toggle_availability(
    ctx: RunContext[AgentDeps],
    property_id: int,
    is_available: bool,
) -> dict[str, Any]:
    """Toggle a property's availability status."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await toggle_property_availability(
        db, actor=user, property_id=property_id, is_available=is_available
    )


# ============================================================================
# ADMIN TOOLS — Agent Property Management
# ============================================================================


async def agent_properties_list(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    occupancy: Literal["occupied", "vacant"] | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    include_total: bool = False,
) -> dict[str, Any]:
    """List managed properties (agents see assigned owners; admins see all)."""
    from app.services.pm_properties import list_managed_properties

    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    limit = min(max(1, limit), 100)
    actor = _user_schema(user)
    filters = {"owner_id": owner_id, "occupancy": occupancy, "q": q}
    cursor_payload = decode_cursor(cursor, filters) if cursor else {}
    properties, next_payload, total = await list_managed_properties(
        db,
        actor=actor,
        owner_id=owner_id,
        occupancy=occupancy,
        q=q,
        cursor_payload=cursor_payload,
        limit=limit,
        with_total=include_total,
    )
    # Same enrichment as the MCP admin list: has_active_lease and tenant_name.
    items, _page_stats = await enrich_properties_with_lease_info(db, properties)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "has_more": next_payload is not None,
        "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
        "stats": await compute_portfolio_stats(db, owner_ids=await owner_scope(db, user, owner_id)),
    }


async def agent_properties_get(
    ctx: RunContext[AgentDeps],
    property_id: int,
) -> dict[str, Any]:
    """Get managed property details including owner, lease, and tenant info."""
    from app.services.pm_properties import get_managed_property_detail

    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    result = await get_managed_property_detail(
        db, actor=_user_schema(user), property_id=property_id
    )
    prop = result["property"]
    lease = result.get("active_lease")
    await attach_owner_agents(db, [prop])
    return {
        "property": serialize_property_full(prop, viewer=user),
        "active_lease": serialize_lease(lease, user) if lease else None,
    }


async def agent_properties_create_for_owner(
    ctx: RunContext[AgentDeps],
    owner_id: int,
    title: str,
    property_type: PropertyType,
    purpose: PropertyPurpose,
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
    from app.schemas.property import PropertyCreate
    from app.services.pm_properties import create_managed_property

    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    data = PropertyCreate(
        title=title,
        description=description,
        property_type=property_type,
        purpose=purpose,
        full_address=full_address,
        city=city,
        locality=locality,
        latitude=latitude,
        longitude=longitude,
        base_price=base_price,
        monthly_rent=monthly_rent,
        area_sqft=area_sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
    )
    prop = await create_managed_property(
        db, actor=_user_schema(user), owner_id=owner_id, property_data=data
    )
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
    assert db is not None
    prop = await assert_can_access_property(db, actor=_user_schema(user), property_id=property_id)
    preferences = dict(prop.listing_preferences or {})
    preferences["verification"] = {
        "is_verified": is_verified,
        "notes": verification_notes,
        "verified_by": user.id,
    }
    prop.listing_preferences = preferences
    await db.flush()
    await db.commit()
    return {
        "message": "Property verification updated",
        "property_id": property_id,
        "is_verified": is_verified,
    }


# ============================================================================
# ADMIN TOOLS — Lease Management
# ============================================================================


async def agent_leases_list(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    property_id: int | None = None,
    status: LeaseStatus | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List leases in the caller's scope, filterable by owner, property, and status."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    filters = {
        "owner_id": owner_id,
        "property_id": property_id,
        "status": status.value if status else None,
    }
    return await list_leases(
        db,
        actor=user,
        owner_id=owner_id,
        property_id=property_id,
        status=status,
        cursor_payload=decode_cursor(cursor, filters) if cursor else {},
        limit=limit,
        accessible_owner_ids=await owner_scope(db, user, owner_id),
        filters=filters,
        include_total=include_total,
    )


async def agent_leases_create(
    ctx: RunContext[AgentDeps],
    property_id: int,
    tenant_user_id: int,
    start_date: date,
    end_date: date,
    monthly_rent: float,
    security_deposit: float = 0,
    payment_due_day: int | None = None,
    grace_period_days: int | None = None,
    terms: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new lease for a property the caller can manage. End date must be after start.

    Unset payment_due_day and grace_period_days take the managed property's values.
    """
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await create_lease(
        db,
        actor=user,
        property_id=property_id,
        tenant_user_id=tenant_user_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        monthly_rent=monthly_rent,
        security_deposit=security_deposit,
        payment_due_day=payment_due_day,
        grace_period_days=grace_period_days,
        terms=terms,
        notes=notes,
    )


async def agent_leases_terminate(
    ctx: RunContext[AgentDeps],
    lease_id: int,
    reason: str,
    termination_date: date | None = None,
) -> dict[str, Any]:
    """Terminate an active lease."""
    from app.core.exceptions import (
        BadRequestException,
        InsufficientPermissionsError,
        NotFoundException,
    )
    from app.core.utils import utc_now
    from app.services.pm_leases import terminate_lease

    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None

    term_date = termination_date or utc_now().date()

    try:
        await terminate_lease(
            db,
            actor=_user_schema(user),
            lease_id=lease_id,
            termination_date=term_date,
            reason=reason,
        )
        await db.commit()
    except NotFoundException:
        return {"error": True, "message": f"Lease {lease_id} not found"}
    except InsufficientPermissionsError:
        return {"error": True, "message": "You do not have access to this lease"}
    except BadRequestException as e:
        detail = e.detail if hasattr(e, "detail") else str(e)
        return {"error": True, "message": str(detail)}

    return {
        "message": "Lease terminated",
        "lease_id": lease_id,
        "termination_date": term_date.isoformat(),
    }


# ============================================================================
# ADMIN TOOLS — Rent Collection
# ============================================================================


async def agent_rent_list_due(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    property_id: int | None = None,
    overdue_only: bool = False,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List unpaid rent charges due now in the caller's scope, optionally only overdue ones.

    Same computation as the MCP ``agent_rent_list_due`` tool, read from RentCharge rows.
    ``overdue_only`` is applied before the page limit. ``totals`` covers the full matching set.
    """
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    limit = min(max(1, limit), 100)
    filters = {"owner_id": owner_id, "property_id": property_id, "overdue_only": overdue_only}
    cursor_payload = decode_cursor(cursor, filters) if cursor else {}
    return await compute_rent_due_items(
        db,
        owner_ids=await owner_scope(db, user, owner_id),
        property_id=property_id,
        overdue_only=overdue_only,
        cursor_payload=cursor_payload,
        limit=limit,
        filters=filters,
    )


async def agent_rent_record_payment(
    ctx: RunContext[AgentDeps],
    lease_id: int,
    amount: float,
    payment_date: date,
    payment_method: PaymentMethod = PaymentMethod.bank_transfer,
    transaction_reference: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a settled rent payment for a lease. It settles the oldest open charge.

    The caller must be able to access the lease. The shared tool operation settles
    the charge, so the charge status and the outstanding balance are updated.
    """
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    payment = await record_lease_rent_payment(
        db,
        actor=user,
        lease_id=lease_id,
        amount=amount,
        paid_at=datetime.combine(payment_date, time.min, tzinfo=UTC),
        payment_method=payment_method,
        reference=transaction_reference,
        notes=notes,
    )
    result = {"message": "Payment recorded", "payment": serialize_rent_payment(payment)}
    await db.commit()
    return result


# ============================================================================
# ADMIN TOOLS — Maintenance Management
# ============================================================================


async def agent_maintenance_list(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    property_id: int | None = None,
    status: Literal["open", "in_progress", "scheduled", "completed", "cancelled"] | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List maintenance requests in the caller's scope. Status uses the same labels as the card."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    filters = {"owner_id": owner_id, "property_id": property_id, "status": status}
    return await list_maintenance_requests(
        db,
        property_id=property_id,
        status=status,
        cursor_payload=decode_cursor(cursor, filters) if cursor else {},
        limit=limit,
        accessible_owner_ids=await owner_scope(db, user, owner_id),
        filters=filters,
        include_total=include_total,
    )


async def agent_maintenance_update_status(
    ctx: RunContext[AgentDeps],
    request_id: int,
    status: MaintenanceStatusLabel,
    notes: str | None = None,
    scheduled_date: date | None = None,
    vendor_name: str | None = None,
    vendor_contact: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
) -> dict[str, Any]:
    """Update the status of a maintenance request in the caller's scope.

    Goes through the PM maintenance service: the same access and status transition rules
    as the REST route.
    """
    from app.core.exceptions import NotFoundException

    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    try:
        await update_maintenance_status(
            db,
            actor=user,
            request_id=request_id,
            status=status,
            notes=notes,
            scheduled_date=(
                datetime.combine(scheduled_date, time.min, tzinfo=UTC) if scheduled_date else None
            ),
            vendor_name=vendor_name,
            vendor_contact=vendor_contact,
            estimated_cost=estimated_cost,
            actual_cost=actual_cost,
        )
    except NotFoundException:
        return {"error": True, "message": f"Maintenance request {request_id} not found"}
    await db.commit()
    return {"message": f"Maintenance request updated to {status}", "request_id": request_id}


# ============================================================================
# ADMIN TOOLS — Dashboard
# ============================================================================


async def agent_dashboard_overview(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
) -> dict[str, Any]:
    """Overview dashboard for the caller's scope: stats use the same keys as the owner list."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    stats = await compute_portfolio_stats(db, owner_ids=await owner_scope(db, user, owner_id))
    return {"stats": stats}


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
