"""Shared maintenance tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.mcp.utils import serialize_maintenance_request
from app.models.enums import (
    PRIORITY_TO_URGENCY,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    WorkOrderStatus,
)
from app.models.pm_maintenance import MaintenanceRequest
from app.models.users import User
from app.schemas.pagination import encode_cursor, read_offset, trim_offset_lookahead
from app.schemas.pm_maintenance import MaintenanceRequestUpdate
from app.schemas.user import User as UserSchema
from app.services.pm_maintenance import create_maintenance_request as create_pm_maintenance_request
from app.services.pm_maintenance import update_maintenance_request as update_pm_maintenance_request

logger = get_logger(__name__)

TOOL_OPS_NOT_FOUND = "NOT_FOUND"
TOOL_OPS_FORBIDDEN = "FORBIDDEN"
TOOL_OPS_OPERATION_FAILED = "OPERATION_FAILED"
TOOL_OPS_INVALID_INPUT = "INVALID_INPUT"


# Status keyword → SQLAlchemy filter expression (used by list operations)
# Returns (filter_expression, normalized_status) or (None, error_message)
StatusFilterResult = tuple[Any, str | None]


MAINTENANCE_STATUS_VALUES = ("open", "in_progress", "scheduled", "completed", "cancelled")
# Type of a status label argument. The JSON schema lists the valid values.
MaintenanceStatusLabel = Literal["open", "in_progress", "scheduled", "completed", "cancelled"]
# Priority label of a maintenance request. Maps to MaintenanceUrgency (PRIORITY_TO_URGENCY).
MaintenancePriorityLabel = Literal["low", "medium", "high", "urgent", "emergency"]


def maintenance_status_clause(status: str, model=None):
    """SQL clause for one MCP status label. Mirrors the label in serialize_maintenance_request.

    Precedence is the label's: cancelled, then completed, then scheduled, then in_progress,
    then open. A row carries exactly one label, so a filter returns the rows the label shows.
    Returns None for a value that is not a status label.
    """
    M = model or MaintenanceRequest
    not_cancelled = M.work_order_status.is_distinct_from(WorkOrderStatus.cancelled)
    completed = or_(
        M.completed_at.is_not(None),
        M.request_status.in_([MaintenanceRequestStatus.resolved, MaintenanceRequestStatus.closed]),
    )
    live = and_(not_cancelled, not_(completed))
    not_scheduled = M.scheduled_for.is_(None)
    if status == "cancelled":
        return M.work_order_status == WorkOrderStatus.cancelled
    if status == "completed":
        return and_(not_cancelled, completed)
    if status == "scheduled":
        return and_(live, M.scheduled_for.is_not(None))
    if status == "in_progress":
        return and_(live, not_scheduled, M.work_order_status == WorkOrderStatus.in_progress)
    if status == "open":
        return and_(
            live,
            not_scheduled,
            M.work_order_status.is_distinct_from(WorkOrderStatus.in_progress),
        )
    return None


def build_maintenance_status_filter(
    stmt,
    status: str | None,
    model=None,
) -> StatusFilterResult:
    """Apply a status filter to a MaintenanceRequest query.

    Args:
        stmt: The base SQLAlchemy select statement.
        status: One of 'open', 'in_progress', 'scheduled', 'completed', 'cancelled'.
        model: The model class (defaults to MaintenanceRequest).

    Returns:
        (filtered_stmt, normalized_status_or_error) tuple.
        If status is None, returns (stmt, None).
        If status is invalid, returns (None, error_message).
    """
    if status is None:
        return stmt, None

    status_norm = status.lower().strip()
    expr = maintenance_status_clause(status_norm, model)
    if expr is None:
        return None, f"Invalid status: {status}. Valid: {', '.join(MAINTENANCE_STATUS_VALUES)}"

    return stmt.where(expr), status_norm


# Status label -> (request_status, work_order_status). One table for every MCP and agent caller.
_STATUS_LABEL_STATES: dict[str, tuple[MaintenanceRequestStatus, WorkOrderStatus | None]] = {
    "open": (MaintenanceRequestStatus.open, None),
    "scheduled": (MaintenanceRequestStatus.work_order_created, WorkOrderStatus.assigned),
    "in_progress": (MaintenanceRequestStatus.work_order_created, WorkOrderStatus.in_progress),
    "completed": (MaintenanceRequestStatus.resolved, WorkOrderStatus.completed),
    "cancelled": (MaintenanceRequestStatus.closed, WorkOrderStatus.cancelled),
}


def _parse_scheduled(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid scheduled_date: {value}") from None


async def update_maintenance_status(
    db: AsyncSession,
    *,
    actor: User | UserSchema,
    request_id: int,
    status: str,
    notes: str | None = None,
    scheduled_date: str | datetime | None = None,
    vendor_name: str | None = None,
    vendor_contact: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
) -> MaintenanceRequest:
    """Move a maintenance request to a status label, through the PM service.

    Every MCP and agent caller shares this function. It builds the same PATCH body as
    ``PATCH /pm/maintenance/requests/{id}`` and calls
    ``services.pm_maintenance.update_maintenance_request``, so the caller's rights and the
    request and work order transition rules are the REST rules. ``open`` clears the
    schedule and the completion time. ``completed`` sets the completion time once. Notes
    are appended. Flushes only; the caller commits.

    Raises ValueError for an unknown label or a bad ``scheduled_date``, NotFoundException
    for an unknown request, InsufficientPermissionsError when the caller may not update it,
    and BadRequestException for a refused transition or a bad cost.
    """
    status_norm = status.lower().strip()
    states = _STATUS_LABEL_STATES.get(status_norm)
    if states is None:
        raise ValueError(f"Invalid status: {status}")
    request = await db.get(MaintenanceRequest, request_id)
    if request is None:
        raise NotFoundException(detail="Maintenance request not found")

    fields: dict[str, Any] = {"request_status": states[0], "work_order_status": states[1]}
    if status_norm == "open":
        fields.update(scheduled_for=None, completed_at=None)
    elif status_norm == "completed" and request.completed_at is None:
        fields["completed_at"] = utc_now()
    scheduled_for = _parse_scheduled(scheduled_date)
    if scheduled_for is not None:
        fields["scheduled_for"] = scheduled_for
    if notes:
        existing = request.completion_notes or ""
        fields["completion_notes"] = f"{existing}\n{notes}".strip() if existing else notes
    if vendor_name:
        fields["vendor_name"] = vendor_name
    if vendor_contact:
        fields["vendor_contact"] = vendor_contact
    if estimated_cost is not None:
        fields["estimated_cost"] = estimated_cost
    if actual_cost is not None:
        fields["actual_cost"] = actual_cost

    try:
        body = MaintenanceRequestUpdate(**fields)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise BadRequestException(detail=f"{first['loc'][0]}: {first['msg']}") from None
    return await update_pm_maintenance_request(db, actor=actor, request_id=request_id, body=body)  # type: ignore[arg-type]


async def create_maintenance_request(
    db: AsyncSession,
    *,
    tenant_user_id: int,
    property_id: int,
    title: str,
    description: str,
    category: MaintenanceCategory,
    priority: MaintenancePriorityLabel,
) -> dict:
    """Create a maintenance request for a tenant.

    Verifies the tenant has an active lease on the property.
    """
    # Validate category
    try:
        cat = MaintenanceCategory(category.lower())
    except ValueError:
        valid = [c.value for c in MaintenanceCategory]
        return {
            "error": True,
            "code": TOOL_OPS_INVALID_INPUT,
            "message": f"Invalid category. Valid: {', '.join(valid)}",
        }

    # Map priority to urgency
    priority_norm = priority.lower().strip()
    urgency = PRIORITY_TO_URGENCY.get(priority_norm)
    if urgency is None:
        valid = list(PRIORITY_TO_URGENCY.keys())
        return {
            "error": True,
            "code": TOOL_OPS_INVALID_INPUT,
            "message": f"Invalid priority. Valid: {', '.join(valid)}",
        }

    # The PM service owns the lease check and the row. MCP and the agent share it.
    actor = await db.get(User, tenant_user_id)
    if actor is None:
        return {"error": True, "code": TOOL_OPS_FORBIDDEN, "message": "User not found"}
    try:
        request = await create_pm_maintenance_request(
            db,
            actor=actor,
            property_id=property_id,
            category=cat,
            urgency=urgency,
            title=title,
            description=description,
        )
    except InsufficientPermissionsError:
        return {
            "error": True,
            "code": TOOL_OPS_FORBIDDEN,
            "message": "No active lease found for this property. Only tenants can submit maintenance requests.",
        }

    return {
        "message": "Maintenance request created successfully",
        "request": serialize_maintenance_request(request),
    }


async def list_maintenance_requests(
    db: AsyncSession,
    *,
    tenant_user_id: int | None = None,
    owner_id: int | None = None,
    property_id: int | None = None,
    status: str | None = None,
    cursor_payload: dict | None = None,
    limit: int = 20,
    accessible_owner_ids: list[int] | None = None,
    filters: dict | None = None,
    include_total: bool = False,
) -> dict:
    """One page of maintenance requests, newest first.

    ``accessible_owner_ids`` is the caller's scope (None = no owner scope). ``filters``
    binds the returned cursor. ``total`` is the count of matching rows when
    ``include_total`` is set, otherwise null.
    """
    limit = min(max(1, limit), 100)
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    stmt = select(MaintenanceRequest)

    if tenant_user_id:
        stmt = stmt.where(MaintenanceRequest.tenant_user_id == tenant_user_id)
    if owner_id:
        stmt = stmt.where(MaintenanceRequest.owner_id == owner_id)
    if accessible_owner_ids is not None:
        stmt = stmt.where(MaintenanceRequest.owner_id.in_(accessible_owner_ids))
    if property_id:
        stmt = stmt.where(MaintenanceRequest.property_id == property_id)

    # Apply status filter
    stmt, status_result = build_maintenance_status_filter(stmt, status)
    if stmt is None:
        # Invalid status — status_result is the error message
        return {"error": True, "message": status_result}

    page_stmt = (
        stmt.order_by(MaintenanceRequest.created_at.desc(), MaintenanceRequest.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    result = await db.execute(page_stmt)
    requests = list(result.scalars().all())
    page, next_payload = trim_offset_lookahead(requests, limit=limit, offset=offset)

    total = None
    if include_total:
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = (await db.execute(count_stmt)).scalar_one()

    return {
        "items": [serialize_maintenance_request(r) for r in page],
        "total": total,
        "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
        "has_more": next_payload is not None,
        "limit": limit,
    }
