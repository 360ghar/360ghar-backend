"""Shared booking tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.mcp.utils import serialize_booking, serialize_property_basic
from app.models.properties import Property
from app.schemas.booking import BookingCreate
from app.services import booking as booking_svc

logger = get_logger(__name__)

TOOL_OPS_NOT_FOUND = "NOT_FOUND"
TOOL_OPS_FORBIDDEN = "FORBIDDEN"
TOOL_OPS_OPERATION_FAILED = "OPERATION_FAILED"
TOOL_OPS_INVALID_INPUT = "INVALID_INPUT"


async def check_availability(
    db: AsyncSession,
    *,
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> dict:
    """Check if a property is available for the given dates."""
    result = await booking_svc.check_availability(
        db, property_id, check_in_date, check_out_date, guests
    )
    return {
        "available": result.get("available", False),
        "reason": result.get("reason"),
        "max_occupancy": result.get("max_occupancy"),
    }


async def get_pricing(
    db: AsyncSession,
    *,
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> dict:
    """Get pricing for a short-stay booking."""
    try:
        check_in = datetime.fromisoformat(check_in_date)
        check_out = datetime.fromisoformat(check_out_date)
    except ValueError:
        return {"error": True, "message": "Dates must be in ISO-8601 format"}

    pricing = await booking_svc.calculate_pricing(
        db, property_id, check_in, check_out, guests
    )
    if isinstance(pricing, dict) and pricing.get("error"):
        return {"error": True, "message": pricing["error"]}
    return {"pricing": pricing}


async def create_booking(
    db: AsyncSession,
    *,
    user_id: int,
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
    special_requests: str | None = None,
) -> dict:
    """Create a short-stay booking."""
    try:
        check_in = datetime.fromisoformat(check_in_date)
        check_out = datetime.fromisoformat(check_out_date)
    except ValueError:
        return {"error": True, "message": "Dates must be in ISO-8601 format"}

    if check_out <= check_in:
        return {"error": True, "message": "Check-out date must be after check-in date"}

    # Check availability
    availability = await booking_svc.check_availability(
        db, property_id, check_in_date, check_out_date, guests
    )
    if not availability.get("available"):
        return {
            "error": True,
            "message": availability.get("reason", "Property not available for these dates"),
        }

    booking_data = BookingCreate(
        property_id=property_id,
        check_in_date=check_in,
        check_out_date=check_out,
        guests=guests,
        primary_guest_name="Guest",
        primary_guest_phone="N/A",
        primary_guest_email="guest@360ghar.com",
        special_requests=special_requests,
    )

    booking = await booking_svc.create_booking(db, user_id, booking_data)
    await db.commit()

    return {
        "message": "Booking created successfully",
        "booking": serialize_booking(booking),
    }


async def get_booking_detail(
    db: AsyncSession,
    *,
    booking_id: int,
    user_id: int,
) -> dict:
    """Get booking details, verifying ownership."""
    booking = await booking_svc.get_booking(db, booking_id)
    if not booking:
        return {"error": True, "code": TOOL_OPS_NOT_FOUND, "message": f"Booking {booking_id} not found."}
    if booking.user_id != user_id:
        return {"error": True, "code": TOOL_OPS_FORBIDDEN, "message": "You can only view your own bookings."}

    prop = (
        await db.execute(select(Property).where(Property.id == booking.property_id))
    ).scalar_one_or_none()

    return {
        "booking": serialize_booking(booking),
        "property": serialize_property_basic(prop) if prop else None,
    }


async def cancel_booking(
    db: AsyncSession,
    *,
    booking_id: int,
    user_id: int,
    reason: str,
) -> dict:
    """Cancel a booking, verifying ownership."""
    booking = await booking_svc.get_booking(db, booking_id)
    if not booking:
        return {"error": True, "code": TOOL_OPS_NOT_FOUND, "message": f"Booking {booking_id} not found."}
    if booking.user_id != user_id:
        return {"error": True, "code": TOOL_OPS_FORBIDDEN, "message": "You can only cancel your own bookings."}

    status = getattr(booking, "booking_status", "")
    if status in ("cancelled", "completed", "checked_out"):
        return {"error": True, "code": TOOL_OPS_OPERATION_FAILED, "message": f"Cannot cancel booking (status: {status})"}

    await booking_svc.cancel_booking(db, booking_id, reason)
    await db.commit()

    return {"message": f"Booking {booking_id} cancelled.", "booking_id": booking_id}


async def list_user_bookings(
    db: AsyncSession,
    *,
    user_id: int,
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
) -> dict:
    """List bookings for a user."""
    limit = min(max(1, limit), 100)

    data = await booking_svc.get_user_bookings(db, user_id)

    bookings = data.get("bookings", [])

    if status:
        status_norm = status.lower()
        bookings = [b for b in bookings if getattr(b, "booking_status", "") == status_norm]

    offset = (page - 1) * limit
    paginated = bookings[offset : offset + limit]

    items = [serialize_booking(b) for b in paginated]

    total = len(bookings)
    upcoming = sum(1 for b in bookings if getattr(b, "booking_status", "") == "confirmed")
    completed = sum(1 for b in bookings if getattr(b, "booking_status", "") == "completed")
    cancelled = sum(1 for b in bookings if getattr(b, "booking_status", "") == "cancelled")

    return {
        "total": total,
        "upcoming": upcoming,
        "completed": completed,
        "cancelled": cancelled,
        "page": page,
        "bookings": items,
    }
