from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.exceptions import (
    BadRequestException,
    InsufficientPermissionsError,
)
from app.mcp.admin.agent_tools.common import (
    MCP_SECURITY_SCHEMES_MIXED,
    AuthRequiredError,
    MCPErrorCode,
    MCPResponse,
    _get_user,  # noqa: F401
    _require_agent_or_admin,
    _require_auth,
    admin_mcp,
    get_db,  # noqa: F401
    get_user_role,
    internal_error_response,
    invalid_input_response,
    logger,
    make_tz_aware,
    not_found_response,
    serialize_maintenance_request,
    utc_now,
    utc_now_iso,
)
from app.models.enums import UserRole
from app.schemas.pagination import decode_cursor, encode_cursor, offset_payload, read_offset


@admin_mcp.tool(
    "agent_maintenance_list",
    annotations={
        "title": "List Maintenance Requests",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_maintenance_list(
    owner_id: int | None = None,
    property_id: int | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List maintenance requests for managed properties.

    Args:
        owner_id: Filter by owner
        property_id: Filter by property
        status: Filter by status (open, in_progress, scheduled, completed, cancelled)
        cursor: Opaque pagination cursor from a prior response's next_cursor
        limit: Items per page
    """
    try:
        from sqlalchemy import select

        from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
        from app.models.pm_maintenance import MaintenanceRequest
        from app.models.properties import Property

        limit = min(max(1, limit), 100)
        cursor_payload = decode_cursor(cursor) if cursor else {}
        offset = read_offset(cursor_payload)

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
                    "This endpoint is for agents and admins only"
                ).model_dump()

            from app.services.pm_authz import get_accessible_owner_ids

            user_role = get_user_role(user)

            # Build query with property join for owner filtering
            stmt = select(MaintenanceRequest).join(
                Property, MaintenanceRequest.property_id == Property.id
            )

            if user_role != UserRole.admin:
                accessible_owners = await get_accessible_owner_ids(db, actor=user)
                if accessible_owners is not None:
                    stmt = stmt.where(Property.owner_id.in_(accessible_owners))

            if owner_id:
                stmt = stmt.where(Property.owner_id == owner_id)
            if property_id:
                stmt = stmt.where(MaintenanceRequest.property_id == property_id)
            if status:
                status_norm = status.lower().strip()
                if status_norm == "open":
                    stmt = stmt.where(MaintenanceRequest.request_status == MaintenanceRequestStatus.open)
                elif status_norm == "in_progress":
                    stmt = stmt.where(MaintenanceRequest.work_order_status == WorkOrderStatus.in_progress)
                elif status_norm == "scheduled":
                    stmt = stmt.where(MaintenanceRequest.scheduled_for.is_not(None))
                elif status_norm == "completed":
                    stmt = stmt.where(MaintenanceRequest.completed_at.is_not(None))
                elif status_norm == "cancelled":
                    stmt = stmt.where(MaintenanceRequest.work_order_status == WorkOrderStatus.cancelled)
                else:
                    return invalid_input_response(f"Invalid status: {status}")

            stmt = stmt.order_by(MaintenanceRequest.created_at.desc()).offset(offset).limit(limit + 1)

            result = await db.execute(stmt)
            requests = list(result.scalars().all())

            has_more = len(requests) > limit
            if has_more:
                requests = requests[:limit]

            items = [serialize_maintenance_request(r) for r in requests]
            next_payload = offset_payload(offset + len(items)) if has_more else None

            return MCPResponse.success({
                "total": len(items),
                "next_cursor": encode_cursor(next_payload) if next_payload else None,
                "has_more": next_payload is not None,
                "limit": limit,
                "requests": items,
            }).model_dump()
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
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def agent_maintenance_update_status(
    request_id: int,
    status: str,
    notes: str | None = None,
    scheduled_date: str | None = None,
    vendor_name: str | None = None,
    vendor_contact: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
) -> dict[str, Any]:
    """Update the status of a maintenance request.

    Args:
        request_id: ID of the maintenance request
        status: New status (in_progress, scheduled, completed, cancelled)
        notes: Status update notes
        scheduled_date: Date scheduled for work (ISO-8601)
        vendor_name: Name of assigned vendor
        vendor_contact: Vendor contact info
        estimated_cost: Estimated cost
        actual_cost: Actual cost (when completed)
    """
    try:
        from sqlalchemy import select

        from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
        from app.models.pm_maintenance import MaintenanceRequest

        valid_statuses = ['open', 'in_progress', 'scheduled', 'completed', 'cancelled']
        if status.lower() not in valid_statuses:
            return invalid_input_response(f"status must be one of: {', '.join(valid_statuses)}")

        status_norm = status.lower().strip()

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
                    "This endpoint is for agents and admins only"
                ).model_dump()

            # Get the request with property for auth check
            stmt = select(MaintenanceRequest).where(MaintenanceRequest.id == request_id)
            result = await db.execute(stmt)
            request = result.scalar_one_or_none()

            if not request:
                return not_found_response("Maintenance request", request_id)

            # Verify access to the property
            from app.schemas.user import User as UserSchema
            from app.services.pm_authz import assert_can_access_property

            user_schema = UserSchema.model_validate(user)

            try:
                await assert_can_access_property(
                    db, actor=user_schema, property_id=request.property_id
                )
            except InsufficientPermissionsError:
                return MCPResponse.failure(
                    MCPErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You do not have access to this property's maintenance requests"
                ).model_dump()

            # Update the request
            if notes:
                existing = getattr(request, "completion_notes", None) or ""
                stamp = utc_now_iso()
                request.completion_notes = f"{existing}\n[{stamp}] {notes}".strip()
            if scheduled_date:
                try:
                    request.scheduled_for = make_tz_aware(
                        datetime.fromisoformat(scheduled_date.replace("Z", "+00:00"))
                    )
                except ValueError:
                    return invalid_input_response("scheduled_date must be in ISO-8601 format")
            if estimated_cost is not None:
                request.estimated_cost = estimated_cost
            if actual_cost is not None:
                request.actual_cost = actual_cost

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
                    request.completed_at = utc_now()
            elif status_norm == "cancelled":
                request.request_status = MaintenanceRequestStatus.closed
                request.work_order_status = WorkOrderStatus.cancelled

            await db.flush()
            await db.commit()

            return MCPResponse.success({
                "message": "Maintenance request updated successfully",
                "request": serialize_maintenance_request(request),
            }).model_dump()
    except AuthRequiredError:
        raise
    except BadRequestException as e:
        return invalid_input_response(str(e))
    except Exception as e:
        logger.error("Error in agent.maintenance.update_status: %s", e, exc_info=True)
        return internal_error_response(f"Failed to update maintenance request: {str(e)}")
    return {}
