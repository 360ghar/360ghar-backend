"""Shared booking tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.mcp.utils import serialize_booking, serialize_property_basic
from app.models.bookings import Booking
from app.models.enums import BookingStatus
from app.models.properties import Property
from app.schemas.base import UtcDateTime
from app.schemas.booking import BookingCreate
from app.schemas.pagination import encode_cursor, read_offset, trim_offset_lookahead
from app.services import booking as booking_svc
from app.services.pm_authz import assert_can_access_property

_UTC_DATETIME = TypeAdapter(UtcDateTime)

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
        check_in = _UTC_DATETIME.validate_python(datetime.fromisoformat(check_in_date))
        check_out = _UTC_DATETIME.validate_python(datetime.fromisoformat(check_out_date))
    except ValueError:
        return {"error": True, "message": "Dates must be in ISO-8601 format"}

    pricing = await booking_svc.calculate_pricing(db, property_id, check_in, check_out, guests)
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
        check_in = _UTC_DATETIME.validate_python(datetime.fromisoformat(check_in_date))
        check_out = _UTC_DATETIME.validate_python(datetime.fromisoformat(check_out_date))
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

    # The guest is the signed-in user. Name, phone and email come from the profile.
    from app.models.users import User as UserModel

    user = await db.get(UserModel, user_id)
    if user is None:
        return {"error": True, "message": "User not found"}
    full_name, phone, email = user.full_name, user.phone, user.email
    if not (full_name and phone and email):
        missing = [
            label
            for label, value in (
                ("name", full_name),
                ("phone", phone),
                ("email", email),
            )
            if not value
        ]
        return {
            "error": True,
            "message": f"Add your {' and '.join(missing)} to your profile before booking.",
        }

    booking_data = BookingCreate(
        property_id=property_id,
        check_in_date=check_in,
        check_out_date=check_out,
        guests=guests,
        primary_guest_name=full_name,
        primary_guest_phone=phone,
        primary_guest_email=email,
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
        return {
            "error": True,
            "code": TOOL_OPS_NOT_FOUND,
            "message": f"Booking {booking_id} not found.",
        }
    if booking.user_id != user_id:
        return {
            "error": True,
            "code": TOOL_OPS_FORBIDDEN,
            "message": "You can only view your own bookings.",
        }

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
        return {
            "error": True,
            "code": TOOL_OPS_NOT_FOUND,
            "message": f"Booking {booking_id} not found.",
        }
    if booking.user_id != user_id:
        return {
            "error": True,
            "code": TOOL_OPS_FORBIDDEN,
            "message": "You can only cancel your own bookings.",
        }

    status = getattr(booking, "booking_status", "")
    if status in ("cancelled", "completed", "checked_out"):
        return {
            "error": True,
            "code": TOOL_OPS_OPERATION_FAILED,
            "message": f"Cannot cancel booking (status: {status})",
        }

    await booking_svc.cancel_booking(db, booking_id, reason)
    await db.commit()

    return {"message": f"Booking {booking_id} cancelled.", "booking_id": booking_id}


def booking_status_filter(status: str | BookingStatus | None) -> BookingStatus | None:
    """Case-insensitive status filter. An unknown value means no filter (MCP tools are lenient)."""
    if isinstance(status, BookingStatus):
        return status
    if not status:
        return None
    try:
        return BookingStatus(str(status).lower())
    except ValueError:
        return None


def booking_list_filters(status: str | BookingStatus | None) -> dict[str, Any]:
    """Cursor filter key for the booking list. Every caller binds its cursor with this."""
    resolved = booking_status_filter(status)
    return {"status": resolved.value if resolved else None}


async def list_user_bookings(
    db: AsyncSession,
    *,
    user_id: int,
    cursor_payload: dict | None = None,
    limit: int = 20,
    status: str | BookingStatus | None = None,
    include_total: bool = False,
) -> dict:
    """List bookings for a user, one page at a time.

    ``total`` is the count of rows matching ``status`` when ``include_total`` is set,
    else null. ``counts`` holds the
    per-status totals of all the user's bookings, from one grouped query. They do
    not depend on the page.
    """
    limit = min(max(1, limit), 100)
    if cursor_payload is None:
        cursor_payload = {}

    status_enum = booking_status_filter(status)
    filters = booking_list_filters(status)

    rows, next_payload, total_count = await booking_svc.get_user_bookings(
        db,
        user_id,
        cursor_payload=cursor_payload,
        limit=limit,
        with_total=include_total,
        status=status_enum,
    )
    items = [serialize_booking(b) for b in rows]

    return {
        "items": items,
        "total": total_count,
        "limit": limit,
        "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
        "has_more": next_payload is not None,
        "counts": await _booking_status_counts(db, user_id),
    }


async def _booking_status_counts(db: AsyncSession, user_id: int) -> dict[str, int]:
    """Per-status totals of all the user's bookings, from one grouped query.

    ``upcoming`` is confirmed bookings; ``completed`` and ``cancelled`` are the
    matching statuses. ``total`` is the sum over every status.
    """
    from sqlalchemy import func

    from app.models.bookings import Booking

    grouped = (
        await db.execute(
            select(Booking.booking_status, func.count())
            .where(Booking.user_id == user_id)
            .group_by(Booking.booking_status)
        )
    ).all()
    by_status = {str(getattr(status, "value", status)): int(count) for status, count in grouped}
    return {
        "total": sum(by_status.values()),
        "upcoming": by_status.get(BookingStatus.confirmed.value, 0),
        "completed": by_status.get(BookingStatus.completed.value, 0),
        "cancelled": by_status.get(BookingStatus.cancelled.value, 0),
    }


async def list_managed_bookings(
    db: AsyncSession,
    *,
    owner_ids: Sequence[int] | None = None,
    property_id: int | None = None,
    status: str | BookingStatus | None = None,
    cursor_payload: dict | None = None,
    limit: int = 20,
    filters: dict | None = None,
    include_total: bool = False,
) -> dict:
    """One page of bookings on the properties of ``owner_ids`` (None = every property).

    The caller passes its own scope. ``total`` is the count of matching bookings when
    ``include_total`` is set, otherwise null.
    """
    limit = min(max(1, limit), 100)
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    conditions: list[Any] = []
    if owner_ids is not None:
        conditions.append(
            Booking.property_id.in_(
                select(Property.id).where(Property.owner_id.in_(list(owner_ids)))
            )
        )
    if property_id:
        conditions.append(Booking.property_id == property_id)
    status_enum = booking_status_filter(status)
    if status_enum is not None:
        conditions.append(Booking.booking_status == status_enum)

    stmt = (
        select(Booking)
        .options(selectinload(Booking.property))
        .where(*conditions)
        .order_by(Booking.created_at.desc(), Booking.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    page, next_payload = trim_offset_lookahead(rows, limit=limit, offset=offset)

    total = None
    if include_total:
        total = (await db.execute(select(func.count(Booking.id)).where(*conditions))).scalar_one()

    return {
        "items": [serialize_booking(b) for b in page],
        "total": total,
        "limit": limit,
        "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
        "has_more": next_payload is not None,
    }


async def update_booking_status(
    db: AsyncSession,
    *,
    actor,
    booking_id: int,
    status: BookingStatus,
    notes: str | None = None,
) -> dict:
    """Set a booking's status for a caller who can access the booking's property.

    ``cancelled`` goes through the booking service, so the refund and the cancellation
    fields match a customer cancellation. Other statuses set the field directly.
    """
    booking = await db.get(Booking, booking_id)
    if booking is None:
        return {
            "error": True,
            "code": TOOL_OPS_NOT_FOUND,
            "message": f"Booking {booking_id} not found",
        }
    await assert_can_access_property(db, actor=_user_schema(actor), property_id=booking.property_id)

    if status == BookingStatus.cancelled:
        await booking_svc.cancel_booking(db, booking_id, notes or "Cancelled by the property team")
    else:
        booking.booking_status = status
    if notes and status != BookingStatus.cancelled:
        booking.internal_notes = notes
    await db.flush()
    await db.commit()
    return {"message": f"Booking updated to {status.value}", "booking_id": booking_id}


def _user_schema(user):
    from app.schemas.user import User as UserSchema

    return UserSchema.model_validate(user)
