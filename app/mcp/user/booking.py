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
    AuthRequiredError,
)
from app.mcp.errors import (
    MCPErrorCode,
    MCPResponse,
    internal_error_response,
    not_found_response,
)
from app.mcp.tool_ops import (
    TOOL_OPS_FORBIDDEN,
    TOOL_OPS_NOT_FOUND,
    TOOL_OPS_OPERATION_FAILED,
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

logger = get_logger(__name__)


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
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
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
        logger.error("Error in bookings.create: %s", e, exc_info=True)
        return internal_error_response(f"Failed to create booking: {str(e)}")
    return {}


@user_mcp.tool(
    "bookings_list",
    annotations={
        "title": "List My Bookings",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def bookings_list(
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    """List the current user's bookings.

    Args:
        page: Page number
        limit: Items per page
        status: Filter by status (pending, confirmed, checked_in, checked_out, cancelled, completed)
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

            result = await list_user_bookings(
                db,
                user_id=user.id,
                page=page,
                limit=limit,
                status=status,
            )

            if result.get("error"):
                return internal_error_response(result.get("message", "Failed to list bookings"))

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in bookings.list: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list bookings: {str(e)}")
    return {}


@user_mcp.tool(
    "bookings_get",
    annotations={
        "title": "Get Booking Details",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
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
        logger.error("Error in bookings.get: %s", e, exc_info=True)
        return internal_error_response(f"Failed to get booking: {str(e)}")
    return {}


@user_mcp.tool(
    "bookings_cancel",
    annotations={
        "title": "Cancel Booking",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
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
        logger.error("Error in bookings.cancel: %s", e, exc_info=True)
        return internal_error_response(f"Failed to cancel booking: {str(e)}")
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
        logger.error("Error in bookings.check_availability: %s", e, exc_info=True)
        return internal_error_response(f"Failed to check availability: {str(e)}")
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
        logger.error("Error in bookings.get_pricing: %s", e, exc_info=True)
        return internal_error_response(f"Failed to get pricing: {str(e)}")
    return {}
