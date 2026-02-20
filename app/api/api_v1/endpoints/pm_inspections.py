from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import UserRole
from app.schemas.pm_inspection import (
    InspectionChecklist as InspectionChecklistSchema,
    InspectionChecklistCreate,
    InspectionSign,
)
from app.schemas.user import User as UserSchema
from app.services.pm_inspections import create_inspection_checklist, get_inspection, list_inspections, sign_inspection

router = APIRouter()


@router.post("", response_model=InspectionChecklistSchema)
async def create_inspection(
    payload: InspectionChecklistCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    target_owner_id = current_user.id
    if payload.owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = payload.owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    checklist = await create_inspection_checklist(
        db,
        actor=current_user,
        owner_id=target_owner_id,
        lease_id=payload.lease_id,
        inspection_type=payload.inspection_type,
        rooms_data=payload.rooms_data,
        overall_notes=payload.overall_notes,
        conducted_at=payload.conducted_at,
    )
    return InspectionChecklistSchema.model_validate(checklist)


@router.get("", response_model=list[InspectionChecklistSchema])
async def list_inspection_checklists(
    owner_id: Optional[int] = Query(None, description="Owner id (agent/admin only)"),
    lease_id: Optional[int] = Query(None),
    property_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_inspections(
        db,
        actor=current_user,
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        limit=limit,
        offset=offset,
    )
    return [InspectionChecklistSchema.model_validate(r) for r in rows]


@router.get("/{inspection_id}", response_model=InspectionChecklistSchema)
async def get_inspection_checklist(
    inspection_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    checklist = await get_inspection(db, actor=current_user, inspection_id=inspection_id)
    return InspectionChecklistSchema.model_validate(checklist)


@router.post("/{inspection_id}/sign", response_model=InspectionChecklistSchema)
async def sign(
    inspection_id: int,
    payload: InspectionSign,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    checklist = await sign_inspection(
        db,
        actor=current_user,
        inspection_id=inspection_id,
        tenant_signature_document_id=payload.tenant_signature_document_id,
        owner_signature_document_id=payload.owner_signature_document_id,
    )
    return InspectionChecklistSchema.model_validate(checklist)

