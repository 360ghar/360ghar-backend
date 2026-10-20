"""
Booking tools for User MCP Server.

Tools for short-stay property bookings:
- Create booking
- List bookings
- Get booking details
- Cancel booking
- Check availability
- Get pricing
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AuthRequiredError,
    build_widget_tool_meta,
)
from app.mcp.errors import (
    MCPErrorCode,
    MCPResponse,
    internal_error_response,
    mcp_exception_response,
    not_found_response,
)
from app.mcp.tool_ops import (
    TOOL_OPS_FORBIDDEN,
    TOOL_OPS_NOT_FOUND,
    TOOL_OPS_OPERATION_FAILED,
    booking_list_filters,
    cancel_booking,
    check_availability,
    create_booking,
    get_booking_detail,
    get_pricing,
    list_user_bookings,
)

# Import the user MCP server instance to register tools
from app.mcp.user.server import _get_user, _require_auth, user_mcp
from app.mcp.utils import get_db
from app.models.enums import BookingStatus
from app.schemas.pagination import decode_cursor

logger = get_logger(__name__)


BOOKING_LIST_META = build_widget_tool_meta(
    widget_uri="ui://widget/visitlistwidget.html",
    invoking="Loading bookings...",
    invoked="Bookings loaded",
)

BOOKING_DETAILS_META = build_widget_tool_meta(
    widget_uri="ui://widget/visitschedulerwidget.html",
    invoking="Loading booking details...",
    invoked="Booking details loaded",
)


# ============================================================================
# Booking Tools (for short-stay properties)
# ============================================================================


@user_mcp.tool(
    "bookings_create",
    annotations={
        "title": "Create Booking",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def bookings_create(
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
    special_requests: str | None = None,
) -> dict[str, Any]:
    """Create a new booking for a short-stay property.

    Args:
        property_id: ID of the property to book
        check_in_date: Check-in date (ISO-8601 format)
        check_out_date: Check-out date (ISO-8601 format)
        guests: Number of guests (default 1)
        special_requests: Any special requests
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_create",
                    message="Please log in to create a booking.",
                    scope="mcp:write",
                )

            result = await create_booking(
                db,
                user_id=user.id,
                property_id=property_id,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guests=guests,
                special_requests=special_requests,
            )

            if result.get("error"):
                return MCPResponse.failure(
                    MCPErrorCode.BOOKING_CONFLICT,
                    result.get("message", "Booking creation failed"),
                ).model_dump()

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        return mcp_exception_response(
            e,
            logger=logger,
            tool_name="bookings_create",
            fallback_message="Failed to create booking.",
        )
    return {}


@user_mcp.tool(
    "bookings_list",
    annotations={
        "title": "List My Bookings",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=BOOKING_LIST_META,
)
async def bookings_list(
    cursor: str | None = None,
    limit: int = 20,
    status: BookingStatus | None = None,
    include_total: bool = False,
) -> dict[str, Any]:
    """List the current user's bookings.

    Args:
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Items per page
        status: Filter by status (pending, confirmed, checked_in, checked_out, cancelled, completed)
        include_total: Set true to get the count of bookings matching status
    """
    try:
        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_list",
                    message="Please log in to view your bookings.",
                    scope="mcp:read",
                )

            cursor_payload = decode_cursor(cursor, booking_list_filters(status)) if cursor else None
            result = await list_user_bookings(
                db,
                user_id=user.id,
                cursor_payload=cursor_payload,
                limit=limit,
                status=status,
                include_total=include_total,
            )

            if result.get("error"):
                return internal_error_response(result.get("message", "Failed to list bookings"))

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        return mcp_exception_response(
            e,
            logger=logger,
            tool_name="bookings_list",
            fallback_message="Failed to list bookings.",
        )
    return {}


@user_mcp.tool(
    "bookings_get",
    annotations={
        "title": "Get Booking Details",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=BOOKING_DETAILS_META,
)
async def bookings_get(
    booking_id: int,
) -> dict[str, Any]:
    """Get details of a specific booking.

    Args:
        booking_id: ID of the booking
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_get",
                    message="Please log in to view this booking.",
                    scope="mcp:read",
                )

            result = await get_booking_detail(
                db,
                booking_id=booking_id,
                user_id=user.id,
            )

            if result.get("error"):
                code = result.get("code", "")
                msg = result.get("message", "")
                if code == TOOL_OPS_NOT_FOUND:
                    return not_found_response("Booking", booking_id)
                if code == TOOL_OPS_FORBIDDEN:
                    return MCPResponse.failure(
                        MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                        msg,
                    ).model_dump()
                return internal_error_response(msg)

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        return mcp_exception_response(
            e,
            logger=logger,
            tool_name="bookings_get",
            fallback_message="Failed to get booking.",
        )
    return {}


@user_mcp.tool(
    "bookings_cancel",
    annotations={
        "title": "Cancel Booking",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def bookings_cancel(
    booking_id: int,
    reason: str,
) -> dict[str, Any]:
    """Cancel a booking.

    Args:
        booking_id: ID of the booking to cancel
        reason: Reason for cancellation
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="bookings_cancel",
                    message="Please log in to cancel a booking.",
                    scope="mcp:write",
                )

            result = await cancel_booking(
                db,
                booking_id=booking_id,
                user_id=user.id,
                reason=reason,
            )

            if result.get("error"):
                code = result.get("code", "")
                msg = result.get("message", "")
                if code == TOOL_OPS_NOT_FOUND:
                    return not_found_response("Booking", booking_id)
                if code == TOOL_OPS_FORBIDDEN:
                    return MCPResponse.failure(
                        MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                        msg,
                    ).model_dump()
                if code == TOOL_OPS_OPERATION_FAILED:
                    return MCPResponse.failure(
                        MCPErrorCode.OPERATION_FAILED,
                        msg,
                    ).model_dump()
                return internal_error_response(msg)

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        return mcp_exception_response(
            e,
            logger=logger,
            tool_name="bookings_cancel",
            fallback_message="Failed to cancel booking.",
        )
    return {}


@user_mcp.tool(
    "bookings_check_availability",
    annotations={
        "title": "Check Booking Availability",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_check_availability(
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> dict[str, Any]:
    """Check if a property is available for booking.

    Args:
        property_id: ID of the property
        check_in_date: Check-in date (ISO-8601)
        check_out_date: Check-out date (ISO-8601)
        guests: Number of guests
    """
    try:
        async for db in get_db():
            result = await check_availability(
                db,
                property_id=property_id,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guests=guests,
            )

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        return mcp_exception_response(
            e,
            logger=logger,
            tool_name="bookings_check_availability",
            fallback_message="Failed to check availability.",
        )
    return {}


@user_mcp.tool(
    "bookings_get_pricing",
    annotations={
        "title": "Get Booking Pricing",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_get_pricing(
    property_id: int,
    check_in_date: str,
    check_out_date: str,
    guests: int = 1,
) -> dict[str, Any]:
    """Get pricing details for a potential booking.

    Args:
        property_id: ID of the property
        check_in_date: Check-in date (ISO-8601)
        check_out_date: Check-out date (ISO-8601)
        guests: Number of guests
    """
    try:
        async for db in get_db():
            result = await get_pricing(
                db,
                property_id=property_id,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guests=guests,
            )

            if result.get("error"):
                return MCPResponse.failure(
                    MCPErrorCode.INVALID_INPUT,
                    result.get("message", "Invalid pricing request"),
                ).model_dump()

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        return mcp_exception_response(
            e,
            logger=logger,
            tool_name="bookings_get_pricing",
            fallback_message="Failed to get pricing.",
        )
    return {}
