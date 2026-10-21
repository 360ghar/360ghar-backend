from __future__ import annotations

from typing import Any

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.mcp.admin.agent_tools.common import (
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AuthRequiredError,
    MCPErrorCode,
    MCPResponse,
    _get_user,
    _require_agent_or_admin,
    _require_auth,
    admin_mcp,
    get_db,
    internal_error_response,
    invalid_input_response,
    logger,
    not_found_response,
    serialize_booking,
)
from app.mcp.apps_sdk import build_widget_tool_meta
from app.models.enums import BookingStatus
from app.schemas.pagination import decode_cursor

BOOKING_STATUS_VALUES = ("confirmed", "checked_in", "checked_out", "cancelled", "completed")

AGENT_BOOKINGS_LIST_META = build_widget_tool_meta(
    widget_uri="ui://widget/visitlistwidget.html",
    invoking="Loading bookings...",
    invoked="Bookings loaded",
)


@admin_mcp.tool(
    "agent_bookings_list_all",
    annotations={
        "title": "List All Bookings",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=AGENT_BOOKINGS_LIST_META,
)
async def agent_bookings_list_all(
    property_id: int | None = None,
    status: BookingStatus | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List all bookings for managed properties.

    Args:
        property_id: Filter by property
        status: Filter by booking status
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Items per page (1-100)
        include_total: Set true to get the count of matching bookings
    """
    try:
        from app.mcp.tool_ops import list_managed_bookings
        from app.services.pm_authz import get_accessible_owner_ids

        limit = min(max(1, limit), 100)
        status_norm = status.lower().strip() if status else None
        if status_norm is not None and status_norm not in BOOKING_STATUS_VALUES:
            return invalid_input_response(
                f"status must be one of: {', '.join(BOOKING_STATUS_VALUES)}"
            )
        filters = {"property_id": property_id, "status": status_norm}
        cursor_payload = decode_cursor(cursor, filters) if cursor else {}

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
                    "This endpoint is for agents and admins only",
                ).model_dump()

            accessible = await get_accessible_owner_ids(db, actor=user)
            result = await list_managed_bookings(
                db,
                owner_ids=None if accessible is None else list(accessible),
                property_id=property_id,
                status=status_norm,
                cursor_payload=cursor_payload,
                limit=limit,
                filters=filters,
                include_total=include_total,
            )
            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.bookings.list_all: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list bookings: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_bookings_update_status",
    annotations={
        "title": "Update Booking Status",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def agent_bookings_update_status(
    booking_id: int,
    status: BookingStatus,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update the status of a booking on a property the caller can access.

    Args:
        booking_id: ID of the booking
        status: New status (confirmed, checked_in, checked_out, cancelled, completed)
        notes: Status update notes
    """
    try:
        status_norm = status.lower().strip()
        if status_norm not in BOOKING_STATUS_VALUES:
            return invalid_input_response(
                f"status must be one of: {', '.join(BOOKING_STATUS_VALUES)}"
            )

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
                    "This endpoint is for agents and admins only",
                ).model_dump()

            from app.mcp.tool_ops import update_booking_status
            from app.models.bookings import Booking

            result = await update_booking_status(
                db,
                actor=user,
                booking_id=booking_id,
                status=BookingStatus(status_norm),
                notes=notes,
            )
            if result.get("error"):
                return not_found_response("Booking", booking_id)
            booking = await db.get(Booking, booking_id)
            return MCPResponse.success(
                {
                    "message": f"Booking status updated to {status_norm}",
                    "booking": serialize_booking(booking),
                }
            ).model_dump()
    except AuthRequiredError:
        raise
    except NotFoundException:
        return not_found_response("Booking", booking_id)
    except ForbiddenException as e:
        return MCPResponse.failure(
            MCPErrorCode.INSUFFICIENT_PERMISSIONS, str(e.detail)
        ).model_dump()
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.bookings.update_status: %s", e, exc_info=True)
        return internal_error_response(f"Failed to update booking status: {str(e)}")
    return {}
