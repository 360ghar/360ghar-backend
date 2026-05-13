from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    InsufficientPermissionsError,
    PropertyNotFoundException,
    NotFoundException,
)
from app.models.enums import UserRole

from app.mcp.admin.agent_tools.common import (
    admin_mcp,
    get_db,
    get_user_role,
    internal_error_response,
    invalid_input_response,
    not_found_response,
    MCPErrorCode,
    MCPResponse,
    AuthRequiredError,
    MCP_SECURITY_SCHEMES_MIXED,
    serialize_property_basic,
    serialize_property_full,
    serialize_booking,
    serialize_lease,
    serialize_maintenance_request,
    serialize_user_basic,
    make_tz_aware,
    utc_now,
    utc_now_iso,
    _get_user,
    _require_auth,
    _require_agent_or_admin,
    logger,
)

@admin_mcp.tool(
    "agent_bookings_list_all",
    annotations={
        "title": "List All Bookings",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_bookings_list_all(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List all bookings for managed properties.

    Args:
        owner_id: Filter by property owner
        property_id: Filter by property
        status: Filter by booking status
        page: Page number
        limit: Items per page
    """
    try:
        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_bookings_list_all",
                    message="Please log in to view bookings.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).model_dump()

            from app.services import booking as booking_svc

            user_role = get_user_role(user)
            filter_agent_id = None

            # Agents can only see bookings for their assigned users/properties
            if user_role == UserRole.agent and user.agent_id:
                filter_agent_id = user.agent_id

            data = await booking_svc.get_all_bookings(
                db,
                page=page,
                limit=limit,
                status=status,
                filter_agent_id=filter_agent_id,
                property_id=property_id,
                user_id=None,
            )

            items = [serialize_booking(b) for b in data.get("bookings", [])]

            return MCPResponse.success({
                "total": data.get("total", 0),
                "upcoming": data.get("upcoming", 0),
                "completed": data.get("completed", 0),
                "cancelled": data.get("cancelled", 0),
                "page": page,
                "limit": limit,
                "bookings": items,
            }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in agent.bookings.list_all: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list bookings: {str(e)}")

@admin_mcp.tool(
    "agent_bookings_update_status",
    annotations={
        "title": "Update Booking Status",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_bookings_update_status(
    booking_id: int,
    status: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Update the status of a booking.

    Args:
        booking_id: ID of the booking
        status: New status (confirmed, checked_in, checked_out, cancelled, completed)
        notes: Status update notes
    """
    try:
        valid_statuses = ['confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed']
        if status.lower() not in valid_statuses:
            return invalid_input_response(f"status must be one of: {', '.join(valid_statuses)}")

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_bookings_update_status",
                    message="Please log in to update a booking status.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only"
                ).model_dump()

            from app.services import booking as booking_svc

            booking = await booking_svc.get_booking(db, booking_id)
            if not booking:
                return not_found_response("Booking", booking_id)

            # Update booking status
            from app.schemas.booking import BookingUpdate
            update_data = BookingUpdate(booking_status=status.lower())
            if notes:
                update_data.notes = notes

            updated = await booking_svc.update_booking(db, booking_id, update_data)
            await db.commit()

            return MCPResponse.success({
                "message": f"Booking status updated to {status}",
                "booking": serialize_booking(updated) if updated else None,
            }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in agent.bookings.update_status: %s", e, exc_info=True)
        return internal_error_response(f"Failed to update booking status: {str(e)}")
