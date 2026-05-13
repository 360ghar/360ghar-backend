"""Shared maintenance tool operations for MCP servers and tool bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import utc_now
from app.mcp.utils import serialize_maintenance_request
from app.models.enums import (
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    WorkOrderStatus,
)
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest

logger = get_logger(__name__)

TOOL_OPS_NOT_FOUND = "NOT_FOUND"
TOOL_OPS_FORBIDDEN = "FORBIDDEN"
TOOL_OPS_OPERATION_FAILED = "OPERATION_FAILED"
TOOL_OPS_INVALID_INPUT = "INVALID_INPUT"


# Priority keyword → urgency enum mapping (used by create and update operations)
_PRIORITY_TO_URGENCY: dict[str, MaintenanceUrgency] = {
    "low": MaintenanceUrgency.low,
    "medium": MaintenanceUrgency.medium,
    "high": MaintenanceUrgency.high,
    "urgent": MaintenanceUrgency.emergency,
    "emergency": MaintenanceUrgency.emergency,
}

# Status keyword → SQLAlchemy filter expression (used by list operations)
# Returns (filter_expression, normalized_status) or (None, error_message)
StatusFilterResult = tuple[Any, str | None]


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

    M = model or MaintenanceRequest
    status_norm = status.lower().strip()

    filter_map = {
        "open": M.request_status == MaintenanceRequestStatus.open,
        "in_progress": M.work_order_status == WorkOrderStatus.in_progress,
        "scheduled": M.scheduled_for.is_not(None),
        "completed": M.completed_at.is_not(None),
        "cancelled": M.work_order_status == WorkOrderStatus.cancelled,
    }

    expr = filter_map.get(status_norm)
    if expr is None:
        return None, f"Invalid status: {status}. Valid: {', '.join(filter_map)}"

    return stmt.where(expr), status_norm


def apply_maintenance_status_update(
    request: MaintenanceRequest,
    *,
    status: str,
    notes: str | None = None,
    scheduled_date: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
) -> None:
    """Apply a status update to a MaintenanceRequest.

    Maps high-level status keywords to the correct combination of
    ``request_status`` and ``work_order_status`` enum values.

    This is the single source of truth for status transitions.
    """
    status_norm = status.lower().strip()

    if status_norm == "open":
        request.request_status = MaintenanceRequestStatus.open
        request.work_order_status = None
    elif status_norm == "scheduled":
        request.request_status = MaintenanceRequestStatus.work_order_created
        request.work_order_status = WorkOrderStatus.assigned
        if scheduled_date:
            request.scheduled_for = datetime.fromisoformat(scheduled_date)
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
    else:
        raise ValueError(f"Invalid status: {status}")

    # Optional field updates
    if notes:
        existing = getattr(request, "completion_notes", "") or ""
        request.completion_notes = f"{existing}\n{notes}".strip() if existing else notes
    if estimated_cost is not None:
        request.estimated_cost = estimated_cost
    if actual_cost is not None:
        request.actual_cost = actual_cost


async def create_maintenance_request(
    db: AsyncSession,
    *,
    tenant_user_id: int,
    property_id: int,
    title: str,
    description: str,
    category: str,
    priority: str,
) -> dict:
    """Create a maintenance request for a tenant.

    Verifies the tenant has an active lease on the property.
    """
    # Validate category
    try:
        cat = MaintenanceCategory(category.lower())
    except ValueError:
        valid = [c.value for c in MaintenanceCategory]
        return {"error": True, "code": TOOL_OPS_INVALID_INPUT, "message": f"Invalid category. Valid: {', '.join(valid)}"}

    # Map priority to urgency
    priority_norm = priority.lower().strip()
    urgency = _PRIORITY_TO_URGENCY.get(priority_norm)
    if urgency is None:
        valid = list(_PRIORITY_TO_URGENCY.keys())
        return {"error": True, "code": TOOL_OPS_INVALID_INPUT, "message": f"Invalid priority. Valid: {', '.join(valid)}"}

    # Verify tenant has active lease on this property
    lease = (
        await db.execute(
            select(Lease).where(
                Lease.property_id == property_id,
                Lease.tenant_user_id == tenant_user_id,
                Lease.status == LeaseStatus.active,
            )
        )
    ).scalar_one_or_none()

    if not lease:
        return {
            "error": True,
            "code": TOOL_OPS_FORBIDDEN,
            "message": "No active lease found for this property. Only tenants can submit maintenance requests.",
        }

    request = MaintenanceRequest(
        property_id=property_id,
        lease_id=lease.id,
        owner_id=lease.owner_id,
        tenant_user_id=tenant_user_id,
        title=title,
        description=description,
        category=cat,
        urgency=urgency,
        request_status=MaintenanceRequestStatus.open,
    )
    db.add(request)
    await db.flush()
    await db.refresh(request)
    await db.commit()

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
    page: int = 1,
    limit: int = 20,
) -> dict:
    """List maintenance requests with optional filters."""
    limit = min(max(1, limit), 100)

    stmt = select(MaintenanceRequest)

    if tenant_user_id:
        stmt = stmt.where(MaintenanceRequest.tenant_user_id == tenant_user_id)
    if owner_id:
        stmt = stmt.where(MaintenanceRequest.owner_id == owner_id)
    if property_id:
        stmt = stmt.where(MaintenanceRequest.property_id == property_id)

    # Apply status filter
    stmt, err = build_maintenance_status_filter(stmt, status)
    if err is not None:
        return {"error": True, "message": err}

    offset = (page - 1) * limit
    stmt = stmt.order_by(MaintenanceRequest.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    requests = result.scalars().all()

    items = [serialize_maintenance_request(r) for r in requests]

    total = len(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit if total else 0,
    }
