from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.models.enums import (
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    UserRole,
    WorkOrderStatus,
)
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.users import User
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.services.pm_authz import assert_can_access_property, assert_can_manage_owner_portfolio


async def create_maintenance_request(
    db: AsyncSession,
    *,
    actor: User,
    property_id: int,
    category: MaintenanceCategory,
    urgency: MaintenanceUrgency,
    title: str,
    description: str | None = None,
    preferred_contact_method: str | None = None,
    availability_notes: str | None = None,
) -> MaintenanceRequest:
    prop = await assert_can_access_property(db, actor=actor, property_id=property_id, allow_tenant=True)

    owner_id = prop.owner_id
    lease_id: int | None = None
    tenant_user_id: int | None = None

    # Determine whether caller is owner/RM/admin vs tenant
    if actor.role == UserRole.admin.value:
        pass
    elif actor.role == UserRole.agent.value:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
    else:
        if owner_id == actor.id:
            # Owner creating a request
            pass
        else:
            # Tenant creating a request: must have active lease
            stmt = select(Lease).where(
                Lease.property_id == property_id,
                Lease.tenant_user_id == actor.id,
                Lease.status == LeaseStatus.active,
            )
            res = await db.execute(stmt)
            lease = res.scalar_one_or_none()
            if not lease:
                raise InsufficientPermissionsError("Tenant does not have an active lease for this property")
            lease_id = lease.id
            tenant_user_id = actor.id

    req = MaintenanceRequest(
        property_id=property_id,
        lease_id=lease_id,
        owner_id=owner_id,
        tenant_user_id=tenant_user_id,
        category=category,
        urgency=urgency,
        title=title,
        description=description,
        preferred_contact_method=preferred_contact_method,
        availability_notes=availability_notes,
        request_status=MaintenanceRequestStatus.open,
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)
    return req


async def list_maintenance_requests(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    property_id: int | None = None,
    lease_id: int | None = None,
    request_status: MaintenanceRequestStatus | None = None,
    work_order_status: WorkOrderStatus | None = None,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[MaintenanceRequest], dict | None, int | None]:
    stmt = select(MaintenanceRequest)

    if actor.role == UserRole.admin.value:
        if owner_id is not None:
            stmt = stmt.where(MaintenanceRequest.owner_id == owner_id)
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
        stmt = stmt.where(MaintenanceRequest.owner_id == owner_id)
    else:
        # Could be owner or tenant; show both views:
        # - owner: requests for their portfolio
        # - tenant: requests they created
        stmt = stmt.where(
            (MaintenanceRequest.owner_id == actor.id) | (MaintenanceRequest.tenant_user_id == actor.id)
        )

    if property_id is not None:
        stmt = stmt.where(MaintenanceRequest.property_id == property_id)
    if lease_id is not None:
        stmt = stmt.where(MaintenanceRequest.lease_id == lease_id)
    if request_status is not None:
        stmt = stmt.where(MaintenanceRequest.request_status == request_status)
    if work_order_status is not None:
        stmt = stmt.where(MaintenanceRequest.work_order_status == work_order_status)

    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    predicate = keyset_filter(MaintenanceRequest.created_at, MaintenanceRequest.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(MaintenanceRequest.created_at.desc(), MaintenanceRequest.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_payload = keyset_payload(keyset_sort_value(last.created_at), last.id)
    return rows, next_payload, count_total


async def update_maintenance_request(
    db: AsyncSession,
    *,
    actor: User,
    request_id: int,
    request_status: MaintenanceRequestStatus | None = None,
    assigned_agent_id: int | None = None,
    work_order_status: WorkOrderStatus | None = None,
    priority: str | None = None,
    estimated_cost: float | None = None,
    actual_cost: float | None = None,
    scheduled_for: datetime | None = None,
    completed_at: datetime | None = None,
    closed_at: datetime | None = None,
    completion_notes: str | None = None,
) -> MaintenanceRequest:
    req = await db.get(MaintenanceRequest, request_id)
    if not req:
        raise NotFoundException(detail="Maintenance request not found")

    # Only owner/RM/admin can update; tenant can only view
    if actor.role == UserRole.admin.value:
        pass
    elif actor.role == UserRole.agent.value:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=req.owner_id)
    else:
        if req.owner_id != actor.id:
            raise InsufficientPermissionsError("Only the owner can update this request")

    if request_status is not None:
        # Validate status transition
        ALLOWED_TRANSITIONS: dict[str, set[str]] = {
            "open": {"in_review", "work_order_created", "resolved", "closed"},
            "in_review": {"work_order_created", "resolved", "closed", "open"},
            "work_order_created": {"resolved", "closed"},
            "resolved": {"closed", "open"},
            "closed": set(),
        }
        current = req.request_status.value if hasattr(req.request_status, "value") else str(req.request_status)
        target = request_status.value if hasattr(request_status, "value") else str(request_status)
        # Allow idempotent updates (same status) — clients may re-submit.
        if target != current:
            allowed = ALLOWED_TRANSITIONS.get(current, set())
            if target not in allowed:
                raise BadRequestException(
                    detail=f"Cannot transition from '{current}' to '{target}'. Allowed: {allowed or 'none (terminal state)'}"
                )
        req.request_status = request_status
    if assigned_agent_id is not None:
        req.assigned_agent_id = assigned_agent_id
    if work_order_status is not None:
        # Validate work order status transition
        WO_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
            "created": {"assigned", "cancelled"},
            "assigned": {"in_progress", "cancelled"},
            "in_progress": {"completed", "cancelled"},
            "completed": {"closed"},
            "closed": set(),
            "cancelled": set(),
        }
        wo_current = req.work_order_status.value if req.work_order_status and hasattr(req.work_order_status, "value") else None
        if wo_current is not None:
            wo_target = work_order_status.value if hasattr(work_order_status, "value") else str(work_order_status)
            # Allow idempotent updates (same status) — clients may re-submit.
            if wo_target != wo_current:
                wo_allowed = WO_ALLOWED_TRANSITIONS.get(wo_current, set())
                if wo_target not in wo_allowed:
                    raise BadRequestException(
                        detail=f"Cannot transition work order from '{wo_current}' to '{wo_target}'. Allowed: {wo_allowed or 'none (terminal state)'}"
                    )
        req.work_order_status = work_order_status
    if priority is not None:
        req.priority = priority
    if estimated_cost is not None:
        if estimated_cost < 0:
            raise BadRequestException(detail="estimated_cost must be >= 0")
        req.estimated_cost = estimated_cost
    if actual_cost is not None:
        if actual_cost < 0:
            raise BadRequestException(detail="actual_cost must be >= 0")
        req.actual_cost = actual_cost
    if scheduled_for is not None:
        req.scheduled_for = scheduled_for
    if completed_at is not None:
        req.completed_at = completed_at
    if closed_at is not None:
        req.closed_at = closed_at
    if completion_notes is not None:
        req.completion_notes = completion_notes

    await db.flush()
    await db.refresh(req)
    return req

