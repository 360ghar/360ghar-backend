"""
Booking tools — creation, listing, cancellation, and availability checks.

Each tool is a thin wrapper over ``app.mcp.tool_ops``. The MCP and agent surfaces
share one implementation, so a rule changes in one place.

Includes both user-facing booking tools and admin booking management tools.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic_ai import RunContext

from app.core.logging import get_logger
from app.mcp.tool_ops import (
    booking_list_filters,
    cancel_booking,
    check_availability,
    create_booking,
    get_booking_detail,
    get_pricing,
    list_managed_bookings,
    list_user_bookings,
    update_booking_status,
)
from app.models.enums import BookingStatus
from app.schemas.pagination import decode_cursor
from app.services.ai_agent.tools.helpers import AgentDeps, owner_scope

logger = get_logger(__name__)


# ============================================================================
# USER TOOLS — Bookings
# ============================================================================


async def bookings_check_availability(
    ctx: RunContext[AgentDeps],
    property_id: int,
    check_in_date: date,
    check_out_date: date,
    guests: int = 1,
) -> dict[str, Any]:
    """Check if a property is available for booking."""
    db = ctx.deps.db
    assert db is not None
    return await check_availability(
        db,
        property_id=property_id,
        check_in_date=check_in_date.isoformat(),
        check_out_date=check_out_date.isoformat(),
        guests=guests,
    )


async def bookings_get_pricing(
    ctx: RunContext[AgentDeps],
    property_id: int,
    check_in_date: date,
    check_out_date: date,
    guests: int = 1,
) -> dict[str, Any]:
    """Get pricing details for a potential booking."""
    db = ctx.deps.db
    assert db is not None
    return await get_pricing(
        db,
        property_id=property_id,
        check_in_date=check_in_date.isoformat(),
        check_out_date=check_out_date.isoformat(),
        guests=guests,
    )


async def bookings_create(
    ctx: RunContext[AgentDeps],
    property_id: int,
    check_in_date: date,
    check_out_date: date,
    guests: int = 1,
    special_requests: str | None = None,
) -> dict[str, Any]:
    """Create a new booking for a short-stay property, under the signed-in user's name and contact."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await create_booking(
        db,
        user_id=user.id,
        property_id=property_id,
        check_in_date=check_in_date.isoformat(),
        check_out_date=check_out_date.isoformat(),
        guests=guests,
        special_requests=special_requests,
    )


async def bookings_list(
    ctx: RunContext[AgentDeps],
    cursor: str | None = None,
    limit: int = 20,
    status: BookingStatus | None = None,
    include_total: bool = False,
) -> dict[str, Any]:
    """List the current user's bookings, with per-status counts. ``total`` is set only with include_total."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    filters = booking_list_filters(status)
    cursor_payload = decode_cursor(cursor, filters) if cursor else None
    return await list_user_bookings(
        db,
        user_id=user.id,
        cursor_payload=cursor_payload,
        limit=limit,
        status=status,
        include_total=include_total,
    )


async def bookings_get(
    ctx: RunContext[AgentDeps],
    booking_id: int,
) -> dict[str, Any]:
    """Get details of a specific booking."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await get_booking_detail(db, booking_id=booking_id, user_id=user.id)


async def bookings_cancel(
    ctx: RunContext[AgentDeps],
    booking_id: int,
    reason: str,
) -> dict[str, Any]:
    """Cancel a booking."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await cancel_booking(db, booking_id=booking_id, user_id=user.id, reason=reason)


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
    status: BookingStatus | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List bookings on the properties in the caller's scope."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    filters = {
        "owner_id": owner_id,
        "property_id": property_id,
        "status": status.value if status else None,
    }
    return await list_managed_bookings(
        db,
        owner_ids=await owner_scope(db, user, owner_id),
        property_id=property_id,
        status=status,
        cursor_payload=decode_cursor(cursor, filters) if cursor else {},
        limit=limit,
        filters=filters,
        include_total=include_total,
    )


async def agent_bookings_update_status(
    ctx: RunContext[AgentDeps],
    booking_id: int,
    status: BookingStatus,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update the status of a booking on a property the caller can access."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await update_booking_status(
        db, actor=user, booking_id=booking_id, status=status, notes=notes
    )
