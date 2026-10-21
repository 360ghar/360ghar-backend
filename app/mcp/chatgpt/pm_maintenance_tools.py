"""Owner maintenance tools for ChatGPT App."""

from __future__ import annotations

from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    AuthRequiredError,
    build_widget_tool_meta,
)
from app.mcp.chatgpt import get_widget_for_tool
from app.mcp.chatgpt.pm_shared import _get_optional_user
from app.mcp.chatgpt.response_formatter import (
    format_auth_required_response,
    format_chatgpt_response,
)
from app.mcp.tool_ops.maintenance import (
    MAINTENANCE_STATUS_VALUES,
    MaintenancePriorityLabel,
    MaintenanceStatusLabel,
    maintenance_status_clause,
    update_maintenance_status,
)

# Import the user MCP server to register tools
from app.mcp.user.server import user_mcp
from app.mcp.utils import serialize_maintenance_request
from app.models.enums import PRIORITY_TO_URGENCY
from app.schemas.pagination import (
    decode_cursor,
    encode_cursor,
    read_offset,
    trim_offset_lookahead,
)

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
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def owner_maintenance_list(
    property_id: int | None = None,
    status: MaintenanceStatusLabel | None = None,
    priority: MaintenancePriorityLabel | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """List maintenance requests for the authenticated owner's properties.

    ``stats`` counts every matching request, not only the page. ``total`` is the count
    of matching requests when ``include_total`` is set, otherwise null.
    """
    try:
        from sqlalchemy import func, or_, select

        from app.models.enums import MaintenanceUrgency
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property

        limit = min(max(1, limit), 50)
        status_norm = status.lower().strip() if status else None
        priority_norm = priority.lower().strip() if priority else None
        filters = {"property_id": property_id, "status": status_norm, "priority": priority_norm}
        cursor_payload = decode_cursor(cursor, filters) if cursor else {}
        offset = read_offset(cursor_payload)

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
                    data={
                        "items": [],
                        "total": 0 if include_total else None,
                        "stats": {},
                    },
                    content_summary="You don't have any properties to show maintenance requests for.",
                    widget_uri=get_widget_for_tool("owner_maintenance_list"),
                )

            scope: list[Any] = [MaintenanceRequest.property_id.in_(owner_property_ids)]
            if property_id:
                scope.append(MaintenanceRequest.property_id == property_id)
            if status_norm in MAINTENANCE_STATUS_VALUES:
                scope.append(maintenance_status_clause(status_norm))
            if priority_norm:
                urgency = PRIORITY_TO_URGENCY.get(priority_norm)
                if urgency is not None:
                    scope.append(MaintenanceRequest.urgency == urgency)

            page_stmt = (
                select(MaintenanceRequest)
                .where(*scope)
                .order_by(MaintenanceRequest.created_at.desc(), MaintenanceRequest.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
            rows = list((await db.execute(page_stmt)).scalars().all())
            page, next_payload = trim_offset_lookahead(rows, limit=limit, offset=offset)
            serialized = [serialize_maintenance_request(r) for r in page]

            total = None
            if include_total:
                total = (
                    await db.execute(select(func.count(MaintenanceRequest.id)).where(*scope))
                ).scalar_one()
            open_count = (
                await db.execute(
                    select(func.count(MaintenanceRequest.id)).where(
                        *scope,
                        or_(
                            maintenance_status_clause("open"),
                            maintenance_status_clause("in_progress"),
                        ),
                    )
                )
            ).scalar_one()
            urgent_count = (
                await db.execute(
                    select(func.count(MaintenanceRequest.id)).where(
                        *scope, MaintenanceRequest.urgency == MaintenanceUrgency.emergency
                    )
                )
            ).scalar_one()

            return format_chatgpt_response(
                data={
                    "items": serialized,
                    "total": total,
                    "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
                    "has_more": next_payload is not None,
                    "limit": limit,
                    "stats": {
                        "open": open_count,
                        "urgent": urgent_count,
                    },
                },
                content_summary=f"Showing {len(serialized)} maintenance requests. {open_count} open, {urgent_count} urgent.",
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
        "securitySchemes": MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    },
)
async def owner_maintenance_update(
    request_id: int,
    status: MaintenanceStatusLabel,
    scheduled_date: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
    resolution_notes: str | None = None,
) -> dict[str, Any]:
    """Update maintenance status, schedule, costs, or resolution notes.

    The update goes through the PM maintenance service, so the caller's rights and the
    status transition rules are the same as for the REST route.
    """
    try:
        async with AsyncSessionLocal() as db:
            user = await _get_optional_user(db)

            if not user:
                return format_auth_required_response(
                    action="update_maintenance",
                    message="To update maintenance requests, please log in to your 360Ghar account.",
                )

            widget = get_widget_for_tool("owner_maintenance_update")
            try:
                request = await update_maintenance_status(
                    db,
                    actor=user,
                    request_id=request_id,
                    status=status,
                    notes=resolution_notes,
                    scheduled_date=scheduled_date,
                    estimated_cost=estimated_cost,
                    actual_cost=actual_cost,
                )
                # Serialize before the commit. A failure here rolls the write back.
                saved = serialize_maintenance_request(request)
                await db.commit()
            except NotFoundException:
                return format_chatgpt_response(
                    data={"error": True, "code": "NOT_FOUND"},
                    content_summary=f"Maintenance request with ID {request_id} was not found.",
                    widget_uri=widget,
                )
            except ForbiddenException:
                return format_chatgpt_response(
                    data={"error": True, "code": "FORBIDDEN"},
                    content_summary="You don't have permission to update this maintenance request.",
                    widget_uri=widget,
                )
            except (BadRequestException, ValueError) as e:
                message = str(getattr(e, "detail", e))
                return format_chatgpt_response(
                    data={"error": True, "code": "INVALID_INPUT", "message": message},
                    content_summary=f"The maintenance request was not updated: {message}",
                    widget_uri=widget,
                )

            return format_chatgpt_response(
                data={"request": saved},
                content_summary=f"Maintenance request updated to '{status}'.",
                widget_uri=widget,
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
