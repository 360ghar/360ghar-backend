"""Owner maintenance tools for ChatGPT App."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.mcp.apps_sdk import MCP_SECURITY_SCHEMES_MIXED, AuthRequiredError, build_widget_tool_meta
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.pm_shared import _get_optional_user
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp

logger = get_logger(__name__)

# ChatGPT tool metadata for widget linkage
MAINTENANCE_META = build_widget_tool_meta(
    widget_uri="ui://widget/maintenancewidget.html",
    invoking="Loading maintenance requests...",
    invoked="Maintenance data loaded",
)


@user_mcp.tool(
    "owner_maintenance_list",
    annotations={
        "title": "List Maintenance Requests",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_META,
)
async def owner_maintenance_list(
    property_id: int | None = None,
    status: str | None = None,
    priority: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """List maintenance requests for the authenticated owner's properties."""
    try:
        from sqlalchemy import select

        from app.mcp.utils import serialize_maintenance_request
        from app.models.enums import MaintenanceRequestStatus, MaintenanceUrgency, WorkOrderStatus
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property

        limit = min(max(1, limit), 50)
        page = max(1, page)

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="list_maintenance",
                    message="To view maintenance requests, please log in to your 360Ghar account.",
                )

            # Get property IDs owned by user
            props_stmt = select(Property.id).where(Property.owner_id == user.id)
            props_result = await db.execute(props_stmt)
            owner_property_ids = [row[0] for row in props_result.fetchall()]

            if not owner_property_ids:
                return format_chatgpt_response(
                    data={"items": [], "total": 0, "stats": {}},
                    content_summary="You don't have any properties to show maintenance requests for.",
                    widget_uri=get_widget_for_tool("owner_maintenance_list"),
                )

            # Build maintenance query
            stmt = select(MaintenanceRequest).where(
                MaintenanceRequest.property_id.in_(owner_property_ids)
            )

            if property_id:
                stmt = stmt.where(MaintenanceRequest.property_id == property_id)

            if status:
                status_norm = status.lower().strip()
                if status_norm == "open":
                    stmt = stmt.where(
                        MaintenanceRequest.request_status == MaintenanceRequestStatus.open
                    )
                elif status_norm == "in_progress":
                    stmt = stmt.where(
                        MaintenanceRequest.work_order_status == WorkOrderStatus.in_progress
                    )
                elif status_norm == "scheduled":
                    stmt = stmt.where(MaintenanceRequest.scheduled_for.is_not(None))
                elif status_norm == "completed":
                    stmt = stmt.where(MaintenanceRequest.completed_at.is_not(None))
                elif status_norm == "cancelled":
                    stmt = stmt.where(
                        MaintenanceRequest.work_order_status == WorkOrderStatus.cancelled
                    )

            if priority:
                priority_norm = priority.lower().strip()
                urgency_map = {
                    "low": MaintenanceUrgency.low,
                    "medium": MaintenanceUrgency.medium,
                    "high": MaintenanceUrgency.high,
                    "urgent": MaintenanceUrgency.emergency,
                    "emergency": MaintenanceUrgency.emergency,
                }
                urgency = urgency_map.get(priority_norm)
                if urgency is not None:
                    stmt = stmt.where(MaintenanceRequest.urgency == urgency)

            stmt = stmt.order_by(MaintenanceRequest.created_at.desc())
            stmt = stmt.offset((page - 1) * limit).limit(limit)

            result = await db.execute(stmt)
            requests = result.scalars().all()

            serialized = [serialize_maintenance_request(r) for r in requests]

            # Stats
            open_count = sum(1 for r in serialized if r["status"] in ("open", "in_progress"))
            urgent_count = sum(1 for r in serialized if r["priority"] == "urgent")

            return format_chatgpt_response(
                data={
                    "items": serialized,
                    "total": len(serialized),
                    "page": page,
                    "limit": limit,
                    "total_pages": (len(serialized) + limit - 1) // limit if serialized else 0,
                    "stats": {
                        "open": open_count,
                        "urgent": urgent_count,
                    },
                },
                content_summary=f"Found {len(serialized)} maintenance requests. {open_count} open, {urgent_count} urgent.",
                widget_uri=get_widget_for_tool("owner_maintenance_list"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.maintenance.list: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error loading maintenance requests: {str(e)}",
            widget_uri=get_widget_for_tool("owner_maintenance_list"),
        )


@user_mcp.tool(
    "owner_maintenance_update",
    annotations={
        "title": "Update Maintenance Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
    meta=MAINTENANCE_META,
)
async def owner_maintenance_update(
    request_id: int,
    status: str,
    scheduled_date: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
    resolution_notes: str | None = None,
) -> dict[str, Any]:
    """Update maintenance status, schedule, vendor, costs, or resolution notes."""
    try:
        from sqlalchemy import select

        from app.mcp.utils import serialize_maintenance_request
        from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property

        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="update_maintenance",
                    message="To update maintenance requests, please log in to your 360Ghar account.",
                )

            # Get the maintenance request
            stmt = select(MaintenanceRequest).where(MaintenanceRequest.id == request_id)
            result = await db.execute(stmt)
            request = result.scalar_one_or_none()

            if not request:
                return format_chatgpt_response(
                    data={"error": True, "code": "NOT_FOUND"},
                    content_summary=f"Maintenance request with ID {request_id} was not found.",
                    widget_uri=get_widget_for_tool("owner_maintenance_update"),
                )

            # Verify ownership
            prop_stmt = select(Property).where(Property.id == request.property_id)
            prop_result = await db.execute(prop_stmt)
            prop = prop_result.scalar_one_or_none()

            if not prop or prop.owner_id != user.id:
                return format_chatgpt_response(
                    data={"error": True, "code": "FORBIDDEN"},
                    content_summary="You don't have permission to update this maintenance request.",
                    widget_uri=get_widget_for_tool("owner_maintenance_update"),
                )

            valid_statuses = ["open", "in_progress", "scheduled", "completed", "cancelled"]
            status_norm = status.lower().strip()
            if status_norm not in valid_statuses:
                return format_chatgpt_response(
                    data={
                        "error": True,
                        "code": "INVALID_STATUS",
                        "valid_statuses": valid_statuses,
                    },
                    content_summary=f"Invalid status. Please use one of: {', '.join(valid_statuses)}.",
                    widget_uri=get_widget_for_tool("owner_maintenance_update"),
                )

            # Update optional fields
            if scheduled_date:
                try:
                    request.scheduled_for = datetime.fromisoformat(
                        scheduled_date.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass
            if estimated_cost is not None:
                request.estimated_cost = estimated_cost
            if actual_cost is not None:
                request.actual_cost = actual_cost

            if resolution_notes is not None:
                request.completion_notes = resolution_notes

            if status_norm == "open":
                request.request_status = MaintenanceRequestStatus.open
                request.work_order_status = None
                request.scheduled_for = None
                request.completed_at = None
            elif status_norm == "scheduled":
                request.request_status = MaintenanceRequestStatus.work_order_created
                request.work_order_status = WorkOrderStatus.assigned
            elif status_norm == "in_progress":
                request.request_status = MaintenanceRequestStatus.work_order_created
                request.work_order_status = WorkOrderStatus.in_progress
            elif status_norm == "completed":
                request.request_status = MaintenanceRequestStatus.resolved
                request.work_order_status = WorkOrderStatus.completed
                if request.completed_at is None:
                    request.completed_at = datetime.now(timezone.utc)
            elif status_norm == "cancelled":
                request.request_status = MaintenanceRequestStatus.closed
                request.work_order_status = WorkOrderStatus.cancelled

            await db.commit()

            return format_chatgpt_response(
                data={
                    "success": True,
                    "request": serialize_maintenance_request(request),
                },
                content_summary=f"Maintenance request updated to '{status_norm}'.",
                widget_uri=get_widget_for_tool("owner_maintenance_update"),
            )

    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in owner.maintenance.update: %s", e, exc_info=True)
        return format_chatgpt_response(
            data={"error": True, "message": str(e)},
            content_summary=f"Sorry, there was an error updating the maintenance request: {str(e)}",
            widget_uri=get_widget_for_tool("owner_maintenance_update"),
        )
