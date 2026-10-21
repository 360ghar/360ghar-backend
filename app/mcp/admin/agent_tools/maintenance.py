from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.exceptions import (
    BadRequestException,
    InsufficientPermissionsError,
    NotFoundException,
)
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
    make_tz_aware,
    not_found_response,
    serialize_maintenance_request,
)
from app.mcp.apps_sdk import build_widget_tool_meta
from app.mcp.tool_ops.maintenance import MaintenanceStatusLabel, update_maintenance_status
from app.schemas.pagination import decode_cursor

AGENT_MAINTENANCE_LIST_META = build_widget_tool_meta(
    widget_uri="ui://widget/maintenancewidget.html",
    invoking="Loading maintenance requests...",
    invoked="Maintenance requests loaded",
)


@admin_mcp.tool(
    "agent_maintenance_list",
    annotations={
        "title": "List Maintenance Requests",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
    meta=AGENT_MAINTENANCE_LIST_META,
)
async def agent_maintenance_list(
    owner_id: int | None = None,
    property_id: int | None = None,
    status: MaintenanceStatusLabel | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List maintenance requests for managed properties.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        status: Filter by status (open, in_progress, scheduled, completed, cancelled)
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Items per page (1-100)
        include_total: Set true to get the count of matching requests
    """
    try:
        from app.mcp.tool_ops import list_maintenance_requests
        from app.services.pm_authz import get_accessible_owner_ids

        limit = min(max(1, limit), 100)
        filters = {
            "owner_id": owner_id,
            "property_id": property_id,
            "status": status.lower().strip() if status else None,
        }
        cursor_payload = decode_cursor(cursor, filters) if cursor else {}

        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_maintenance_list",
                    message="Please log in to view maintenance requests.",
                    scope="mcp:read",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            accessible = await get_accessible_owner_ids(db, actor=user)
            if accessible is not None and owner_id and owner_id not in accessible:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this owner's maintenance requests",
                ).model_dump()

            result = await list_maintenance_requests(
                db,
                owner_id=owner_id,
                property_id=property_id,
                status=status,
                cursor_payload=cursor_payload,
                limit=limit,
                accessible_owner_ids=None if accessible is None else list(accessible),
                filters=filters,
                include_total=include_total,
            )
            if result.get("error"):
                return invalid_input_response(result.get("message", "Invalid filter"))
            return MCPResponse.success(result).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.maintenance.list: %s", e, exc_info=True)
        return internal_error_response(f"Failed to list maintenance requests: {str(e)}")
    return {}


@admin_mcp.tool(
    "agent_maintenance_update_status",
    annotations={
        "title": "Update Maintenance Status",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def agent_maintenance_update_status(
    request_id: int,
    status: MaintenanceStatusLabel,
    notes: str | None = None,
    scheduled_date: datetime | None = None,
    vendor_name: str | None = None,
    vendor_contact: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
) -> dict[str, Any]:
    """Update the status of a maintenance request.

    Args:
        request_id: ID of the maintenance request
        status: New status (open, in_progress, scheduled, completed, cancelled)
        notes: Status update notes
        scheduled_date: Date scheduled for work (ISO-8601)
        vendor_name: Name of assigned vendor
        vendor_contact: Vendor contact info
        estimated_cost: Estimated cost
        actual_cost: Actual cost (when completed)
    """
    try:
        async for db in get_db():
            user = await _get_user(db)
            if not user:
                _require_auth(
                    action="agent_maintenance_update_status",
                    message="Please log in to update maintenance status.",
                    scope="mcp:write",
                )

            if not _require_agent_or_admin(user):
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "This endpoint is for agents and admins only",
                ).model_dump()

            # The PM service checks the caller's scope and the status transition.
            try:
                request = await update_maintenance_status(
                    db,
                    actor=user,
                    request_id=request_id,
                    status=status,
                    notes=notes,
                    scheduled_date=make_tz_aware(scheduled_date),
                    vendor_name=vendor_name,
                    vendor_contact=vendor_contact,
                    estimated_cost=estimated_cost,
                    actual_cost=actual_cost,
                )
            except NotFoundException:
                return not_found_response("Maintenance request", request_id)
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property's maintenance requests",
                ).model_dump()

            # Serialize before commit (the service refreshed the row).
            result = MCPResponse.success(
                {
                    "message": "Maintenance request updated successfully",
                    "request": serialize_maintenance_request(request),
                }
            ).model_dump()
            await db.commit()
            return result
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except ValueError as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.maintenance.update_status: %s", e, exc_info=True)
        return internal_error_response(f"Failed to update maintenance request: {str(e)}")
    return {}
