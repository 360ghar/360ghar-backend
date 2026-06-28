"""
Booking tools — creation, listing, cancellation, and availability checks.

Includes both user-facing booking tools and admin booking management tools.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic_ai import RunContext
from sqlalchemy import select

from app.core.logging import get_logger
from app.mcp.utils import serialize_booking, serialize_property_basic
from app.models.enums import BookingStatus
from app.services.ai_agent.tools.helpers import AgentDeps

logger = get_logger(__name__)


# ============================================================================
# USER TOOLS — Bookings
# ============================================================================

async def bookings_check_availability(
    ctx: RunContext[AgentDeps],
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> dict[str, Any]:
    """Check if a property is available for booking."""
    from app.services import booking as booking_svc

    db = ctx.deps.db
    result = await booking_svc.check_availability(db, property_id, check_in_date,
                                                   check_out_date, guests)
    return {
        "available": result.get("available", False),
        "reason": result.get("reason"),
        "max_occupancy": result.get("max_occupancy"),
    }


async def bookings_get_pricing(
    ctx: RunContext[AgentDeps],
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> dict[str, Any]:
    """Get pricing details for a potential booking."""
    from app.services import booking as booking_svc

    db = ctx.deps.db
    check_in = datetime.fromisoformat(check_in_date)
    check_out = datetime.fromisoformat(check_out_date)
    pricing = await booking_svc.calculate_pricing(db, property_id, check_in, check_out, guests)
    if isinstance(pricing, dict) and pricing.get("error"):
        return {"error": True, "message": pricing["error"]}
    return {"pricing": pricing}


async def bookings_create(
    ctx: RunContext[AgentDeps],
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
    special_requests: str | None = None,
) -> dict[str, Any]:
    """Create a new booking for a short-stay property."""
    from app.schemas.booking import BookingCreate
    from app.services import booking as booking_svc

    db, user = ctx.deps.db, ctx.deps.user
    check_in = datetime.fromisoformat(check_in_date)
    check_out = datetime.fromisoformat(check_out_date)
    if check_out <= check_in:
        return {"error": True, "message": "Check-out must be after check-in."}

    availability = await booking_svc.check_availability(db, property_id, check_in_date,
                                                         check_out_date, guests)
    if not availability.get("available"):
        return {"error": True, "message": availability.get("reason", "Not available")}

    booking = await booking_svc.create_booking(
        db, user.id,
        BookingCreate(property_id=property_id, check_in_date=check_in,
                      check_out_date=check_out, guests=guests,
                      primary_guest_name="Guest",
                      primary_guest_phone="N/A",
                      primary_guest_email="guest@360ghar.com",
                      special_requests=special_requests),
    )
    await db.commit()
    return {"message": "Booking created successfully", "booking": serialize_booking(booking)}


async def bookings_list(
    ctx: RunContext[AgentDeps],
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    """List the current user's bookings."""
    from app.services import booking as booking_svc

    db, user = ctx.deps.db, ctx.deps.user
    limit = min(max(1, limit), 100)
    rows, _next, _total = await booking_svc.get_user_bookings(db, user.id, cursor_payload={}, limit=limit)
    bookings = rows
    if status:
        bookings = [b for b in bookings if b.booking_status == status]
    items = [serialize_booking(b) for b in bookings]
    return {
        "total": len(bookings), "upcoming": 0,
        "completed": 0, "cancelled": 0,
        "bookings": items, "page": page,
    }


async def bookings_get(
    ctx: RunContext[AgentDeps],
    booking_id: int,
) -> dict[str, Any]:
    """Get details of a specific booking."""
    from app.models.properties import Property
    from app.services import booking as booking_svc

    db, user = ctx.deps.db, ctx.deps.user
    booking = await booking_svc.get_booking(db, booking_id)
    if not booking:
        return {"error": True, "message": f"Booking {booking_id} not found."}
    if booking.user_id != user.id:
        return {"error": True, "message": "You can only view your own bookings."}

    prop = (await db.execute(
        select(Property).where(Property.id == booking.property_id)
    )).scalar_one_or_none()
    return {
        "booking": serialize_booking(booking),
        "property": serialize_property_basic(prop) if prop else None,
    }


async def bookings_cancel(
    ctx: RunContext[AgentDeps],
    booking_id: int,
    reason: str,
) -> dict[str, Any]:
    """Cancel a booking."""
    from app.services import booking as booking_svc

    db, user = ctx.deps.db, ctx.deps.user
    booking = await booking_svc.get_booking(db, booking_id)
    if not booking:
        return {"error": True, "message": f"Booking {booking_id} not found."}
    if booking.user_id != user.id:
        return {"error": True, "message": "You can only cancel your own bookings."}
    if booking.booking_status in ("cancelled", "completed", "checked_out"):
        return {"error": True, "message": f"Cannot cancel (status: {booking.booking_status})"}

    await booking_svc.cancel_booking(db, booking_id, reason)
    await db.commit()
    return {"message": "Booking cancelled successfully", "booking_id": booking_id}


async def user_system_status(
    ctx: RunContext[AgentDeps],
) -> dict[str, Any]:
    """Get system status and available user features."""
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
    }


# ============================================================================
# ADMIN TOOLS — Booking Management
# ============================================================================

async def agent_bookings_list_all(
    ctx: RunContext[AgentDeps],
    owner_id: int | None = None,
    property_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List all bookings across managed properties."""
    from app.models.bookings import Booking
    from app.models.properties import Property

    db = ctx.deps.db
    limit = min(max(1, limit), 100)
    stmt = select(Booking)
    if owner_id:
        stmt = stmt.join(Property, Property.id == Booking.property_id).where(
            Property.owner_id == owner_id
        )
    if property_id:
        stmt = stmt.where(Booking.property_id == property_id)
    if status:
        stmt = stmt.where(Booking.booking_status == status)
    stmt = stmt.order_by(Booking.created_at.desc()).offset((page - 1) * limit).limit(limit)
    items = [serialize_booking(b) for b in (await db.execute(stmt)).scalars().all()]
    return {"items": items, "total": len(items), "page": page}


async def agent_bookings_update_status(
    ctx: RunContext[AgentDeps],
    booking_id: int,
    status: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update the status of a booking."""
    from app.models.bookings import Booking

    db = ctx.deps.db
    valid = ("confirmed", "checked_in", "checked_out", "cancelled", "completed")
    if status not in valid:
        return {"error": True, "message": f"Invalid status. Valid: {valid}"}

    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )).scalar_one_or_none()
    if not booking:
        return {"error": True, "message": f"Booking {booking_id} not found"}

    booking.booking_status = BookingStatus(status)
    if notes:
        booking.internal_notes = notes
    if status == "cancelled":
        booking.cancellation_date = datetime.now(timezone.utc)
        booking.cancellation_reason = notes
    await db.flush()
    await db.commit()
    return {"message": f"Booking updated to {status}", "booking_id": booking_id}
