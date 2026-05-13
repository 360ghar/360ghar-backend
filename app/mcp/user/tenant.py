"""
Tenant tools for User MCP Server.

Tools for tenants to manage their rental experience:
- View current lease
- View rent payment history
- Create maintenance request
- List maintenance requests
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    AuthRequiredError,
    build_widget_tool_meta,
)
from app.mcp.errors import (
    MCPErrorCode,
    MCPResponse,
    internal_error_response,
    invalid_input_response,
)
from app.mcp.tool_ops import (
    TOOL_OPS_FORBIDDEN,
    TOOL_OPS_INVALID_INPUT,
    create_maintenance_request,
    get_rent_history,
    get_tenant_current_lease,
    list_maintenance_requests,
)

# Import the user MCP server instance to register tools
from app.mcp.user.server import _get_user, _require_auth, user_mcp
from app.mcp.utils import get_db

logger = get_logger(__name__)

# ChatGPT widget linkage metadata
LEASE_DETAILS_META = build_widget_tool_meta(
    widget_uri="ui://widget/leasedetailswidget.html",
    invoking="Loading lease details...",
    invoked="Lease details loaded",
)

MAINTENANCE_WIDGET_META = build_widget_tool_meta(
    widget_uri="ui://widget/maintenancewidget.html",
    invoking="Loading maintenance requests...",
    invoked="Maintenance requests loaded",
)

TENANT_RENT_WIDGET_META = build_widget_tool_meta(
    widget_uri="ui://widget/tenantrentwidget.html",
    invoking="Loading your rent information...",
    invoked="Rent information loaded",
)


# ============================================================================
# Tenant Tools
# ============================================================================


@user_mcp.tool(
    "tenant_lease_current",
    annotations={
        "title": "View My Current Lease",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=LEASE_DETAILS_META,
)
async def tenant_lease_current() -> dict[str, Any]:
    """Get the current active lease for the tenant."""
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_lease_current",
                    message="Please log in to view your lease details.",
                    scope="mcp:read",
                )

            result = await get_tenant_current_lease(
                db,
                tenant_user_id=user.id,
            )

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in tenant.lease.current: %s", e, exc_info=True)
        return internal_error_response("Failed to get current lease.")
    return {}


@user_mcp.tool(
    "tenant_rent_history",
    annotations={
        "title": "View My Rent Payment History",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=TENANT_RENT_WIDGET_META,
)
async def tenant_rent_history(
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Get rent payment history for the tenant."""
    try:
        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_rent_history",
                    message="Please log in to view your rent payment history.",
                    scope="mcp:read",
                )

            result = await get_rent_history(
                db,
                tenant_user_id=user.id,
                page=page,
                limit=limit,
            )

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in tenant.rent.history: %s", e, exc_info=True)
        return internal_error_response("Failed to get rent history.")
    return {}


@user_mcp.tool(
    "tenant_maintenance_create",
    annotations={
        "title": "Create Maintenance Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_WIDGET_META,
)
async def tenant_maintenance_create(
    property_id: int,
    title: str,
    description: str,
    category: str,
    priority: str = "medium",
) -> dict[str, Any]:
    """Submit a maintenance request for a property you're renting.

    Args:
        property_id: ID of the property
        title: Short title for the issue
        description: Detailed description of the issue
        category: plumbing, electrical, hvac, appliance, structural, pest_control, cleaning, other
        priority: low, medium, high, urgent (default: medium)
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_maintenance_create",
                    message="Please log in to submit a maintenance request.",
                    scope="mcp:write",
                )

            result = await create_maintenance_request(
                db,
                tenant_user_id=user.id,
                property_id=property_id,
                title=title,
                description=description,
                category=category,
                priority=priority,
            )

            if result.get("error"):
                code = result.get("code", "")
                msg = result.get("message", "")
                if code == TOOL_OPS_FORBIDDEN:
                    return MCPResponse.failure(
                        MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                        "You do not have an active lease for this property.",
                    ).model_dump()
                if code == TOOL_OPS_INVALID_INPUT:
                    if "category" in msg.lower():
                        from app.models.enums import MaintenanceCategory
                        valid_categories = [c.value for c in MaintenanceCategory]
                        return invalid_input_response(
                            f"Invalid category: {category}.",
                            details={"valid_categories": valid_categories},
                        )
                    if "priority" in msg.lower():
                        return invalid_input_response(
                            f"Invalid priority: {priority}.",
                            details={"valid_priorities": ["low", "medium", "high", "urgent"]},
                        )
                return internal_error_response(msg)

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in tenant.maintenance.create: %s", e, exc_info=True)
        return internal_error_response("Failed to create maintenance request.")
    return {}


@user_mcp.tool(
    "tenant_maintenance_list",
    annotations={
        "title": "List My Maintenance Requests",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_WIDGET_META,
)
async def tenant_maintenance_list(
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    """List maintenance requests submitted by the tenant.

    Args:
        page: Page number (default 1)
        limit: Items per page (default 20)
        status: Filter by status (open, in_progress, scheduled, completed, cancelled)
    """
    try:
        limit = min(max(1, limit), 100)

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="tenant_maintenance_list",
                    message="Please log in to view your maintenance requests.",
                    scope="mcp:read",
                )

            result = await list_maintenance_requests(
                db,
                tenant_user_id=user.id,
                page=page,
                limit=limit,
                status=status,
            )

            if result.get("error"):
                return invalid_input_response(
                    result.get("message", "Invalid filter"),
                )

            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in tenant.maintenance.list: %s", e, exc_info=True)
        return internal_error_response("Failed to list maintenance requests.")
    return {}
