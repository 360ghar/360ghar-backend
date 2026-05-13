from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
from app.schemas.pm_maintenance import (
    MaintenanceRequest as MaintenanceRequestSchema,
)
from app.schemas.pm_maintenance import (
    MaintenanceRequestCreate,
    MaintenanceRequestUpdate,
)
from app.schemas.user import User as UserSchema
from app.services.pm_maintenance import (
    create_maintenance_request,
    list_maintenance_requests,
    update_maintenance_request,
)

router = APIRouter()


@router.post("/requests", response_model=MaintenanceRequestSchema)
async def submit_request(
    payload: MaintenanceRequestCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    req = await create_maintenance_request(
        db,
        actor=current_user,  # type: ignore[arg-type]
        property_id=payload.property_id,
        category=payload.category,
        urgency=payload.urgency,
        title=payload.title,
        description=payload.description,
        preferred_contact_method=payload.preferred_contact_method,
        availability_notes=payload.availability_notes,
    )
    return MaintenanceRequestSchema.model_validate(req)


@router.get("/requests", response_model=list[MaintenanceRequestSchema])
async def list_requests(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    lease_id: int | None = Query(None),
    request_status: MaintenanceRequestStatus | None = Query(None),
    work_order_status: WorkOrderStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_maintenance_requests(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        property_id=property_id,
        lease_id=lease_id,
        request_status=request_status,
        work_order_status=work_order_status,
        limit=limit,
        offset=offset,
    )
    return [MaintenanceRequestSchema.model_validate(r) for r in rows]


@router.patch("/requests/{request_id}", response_model=MaintenanceRequestSchema)
async def update_request(
    request_id: int,
    payload: MaintenanceRequestUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    req = await update_maintenance_request(
        db,
        actor=current_user,  # type: ignore[arg-type]
        request_id=request_id,
        request_status=payload.request_status,
        assigned_agent_id=payload.assigned_agent_id,
        work_order_status=payload.work_order_status,
        priority=payload.priority,
        estimated_cost=payload.estimated_cost,
        actual_cost=payload.actual_cost,
        scheduled_for=payload.scheduled_for,
        completed_at=payload.completed_at,
        closed_at=payload.closed_at,
        completion_notes=payload.completion_notes,
    )
    return MaintenanceRequestSchema.model_validate(req)

