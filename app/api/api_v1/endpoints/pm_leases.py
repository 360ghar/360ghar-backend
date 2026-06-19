from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import LeaseStatus, UserRole
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.pm_lease import LeaseCreate, LeaseRenew, LeaseUploadSigned
from app.schemas.user import User as UserSchema
from app.services.pm_leases import (
    create_lease,
    get_lease,
    list_leases,
    renew_lease,
    terminate_lease,
    upload_signed_lease,
)

router = APIRouter()


@router.post(
    "",
    response_model=LeaseSchema,
    summary="Create lease",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "value": {
                                "property_id": 1,
                                "tenant_name": "Rahul Sharma",
                                "tenant_phone": "+919876543210",
                                "tenant_email": "rahul@example.com",
                                "status": "active",
                                "start_date": "2026-07-01",
                                "end_date": "2027-06-30",
                                "monthly_rent": 25000,
                                "security_deposit": 50000,
                                "payment_due_day": 5,
                            }
                        },
                    }
                }
            }
        }
    },
)
async def create_pm_lease(
    payload: LeaseCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create lease."""
    target_owner_id = current_user.id
    if payload.owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = payload.owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    lease = await create_lease(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=target_owner_id,
        property_id=payload.property_id,
        tenant_user_id=payload.tenant_user_id,
        tenant_name=payload.tenant_name,
        tenant_phone=payload.tenant_phone,
        tenant_email=payload.tenant_email,
        status=payload.status,
        start_date=payload.start_date,
        end_date=payload.end_date,
        monthly_rent=payload.monthly_rent,
        security_deposit=payload.security_deposit,
        late_fee_amount=payload.late_fee_amount,
        late_fee_percentage=payload.late_fee_percentage,
        grace_period_days=payload.grace_period_days,
        payment_due_day=payload.payment_due_day,
        lease_terms=payload.lease_terms,
        special_clauses=payload.special_clauses,
        lease_document_id=payload.lease_document_id,
    )
    return LeaseSchema.model_validate(lease)


@router.get("", response_model=CursorPage[LeaseSchema], summary="List leases")
async def list_pm_leases(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    tenant_user_id: int | None = Query(None),
    status: LeaseStatus | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List leases."""
    rows, next_payload, total = await list_leases(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        property_id=property_id,
        tenant_user_id=tenant_user_id,
        status=status,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [LeaseSchema.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.get("/{lease_id}", response_model=LeaseSchema, summary="Get lease")
async def get_pm_lease(
    lease_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get lease."""
    lease = await get_lease(db, actor=current_user, lease_id=lease_id)  # type: ignore[arg-type]
    return LeaseSchema.model_validate(lease)


@router.post("/{lease_id}/upload-signed", response_model=LeaseSchema, summary="Upload signed lease")
async def upload_signed(
    lease_id: int,
    payload: LeaseUploadSigned,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload signed lease."""
    lease = await upload_signed_lease(
        db,
        actor=current_user,  # type: ignore[arg-type]
        lease_id=lease_id,
        lease_document_id=payload.lease_document_id,
        signed_by_owner=payload.signed_by_owner,
        signed_by_tenant=payload.signed_by_tenant,
    )
    return LeaseSchema.model_validate(lease)


@router.post("/{lease_id}/renew", response_model=LeaseSchema, summary="Renew lease")
async def renew(
    lease_id: int,
    payload: LeaseRenew,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Renew lease."""
    lease = await renew_lease(
        db,
        actor=current_user,  # type: ignore[arg-type]
        lease_id=lease_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        monthly_rent=payload.monthly_rent,
        security_deposit=payload.security_deposit,
        make_active=payload.make_active,
    )
    return LeaseSchema.model_validate(lease)


@router.post("/{lease_id}/terminate", response_model=LeaseSchema, summary="Terminate lease")
async def terminate(
    lease_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Terminate lease."""
    lease = await terminate_lease(db, actor=current_user, lease_id=lease_id)  # type: ignore[arg-type]
    return LeaseSchema.model_validate(lease)

