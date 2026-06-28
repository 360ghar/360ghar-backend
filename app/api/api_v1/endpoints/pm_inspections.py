from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import UserRole
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_inspection import (
    InspectionChecklist as InspectionChecklistSchema,
)
from app.schemas.pm_inspection import (
    InspectionChecklistCreate,
    InspectionSign,
)
from app.schemas.user import User as UserSchema
from app.services.pm_inspections import (
    create_inspection_checklist,
    get_inspection,
    list_inspections,
    sign_inspection,
)

router = APIRouter()


@router.post("", response_model=InspectionChecklistSchema, summary="Create inspection checklist")
async def create_inspection(
    payload: InspectionChecklistCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create inspection checklist."""
    target_owner_id = current_user.id
    if payload.owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = payload.owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    checklist = await create_inspection_checklist(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=target_owner_id,
        lease_id=payload.lease_id,
        inspection_type=payload.inspection_type,
        rooms_data=payload.rooms_data,
        overall_notes=payload.overall_notes,
        conducted_at=payload.conducted_at,
    )
    return InspectionChecklistSchema.model_validate(checklist)


@router.get("", response_model=CursorPage[InspectionChecklistSchema], summary="List inspection checklists")
async def list_inspection_checklists(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    lease_id: int | None = Query(None),
    property_id: int | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List inspection checklists."""
    rows, next_payload, total = await list_inspections(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [InspectionChecklistSchema.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.get("/{inspection_id}", response_model=InspectionChecklistSchema, summary="Get inspection checklist")
async def get_inspection_checklist(
    inspection_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get inspection checklist."""
    checklist = await get_inspection(db, actor=current_user, inspection_id=inspection_id)  # type: ignore[arg-type]
    return InspectionChecklistSchema.model_validate(checklist)


@router.post("/{inspection_id}/sign", response_model=InspectionChecklistSchema, summary="Sign inspection checklist")
async def sign(
    inspection_id: int,
    payload: InspectionSign,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Sign inspection checklist."""
    checklist = await sign_inspection(
        db,
        actor=current_user,  # type: ignore[arg-type]
        inspection_id=inspection_id,
        tenant_signature_document_id=payload.tenant_signature_document_id,
        owner_signature_document_id=payload.owner_signature_document_id,
    )
    return InspectionChecklistSchema.model_validate(checklist)

