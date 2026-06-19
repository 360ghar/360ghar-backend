from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import RentChargeStatus
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_rent import (
    RentChargeGenerateRequest,
    RentChargeWithTotals,
    RentPaymentCreate,
)
from app.schemas.pm_rent import (
    RentPayment as RentPaymentSchema,
)
from app.schemas.user import User as UserSchema
from app.services.pm_rent import (
    generate_rent_charges,
    list_rent_charges,
    list_rent_payments,
    record_rent_payment,
)

router = APIRouter()


@router.post("/charges/generate", summary="Generate rent charges")
async def generate_charges(
    payload: RentChargeGenerateRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate rent charges."""
    return await generate_rent_charges(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=payload.owner_id,
        lease_id=payload.lease_id,
        start_month=payload.start_month,
        months=payload.months,
    )


@router.get("/charges", response_model=CursorPage[RentChargeWithTotals], summary="List rent charges")
async def get_charges(
    as_tenant: bool = Query(False, description="If true, return charges for the current tenant user"),
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    lease_id: int | None = Query(None),
    property_id: int | None = Query(None),
    status: RentChargeStatus | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List rent charges."""
    items, next_payload, total = await list_rent_charges(
        db,
        actor=current_user,  # type: ignore[arg-type]
        as_tenant=as_tenant,
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        status=status,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [
            {
                "charge": it["charge"],
                "amount_paid_total": it["amount_paid_total"],
                "amount_due_total": it["amount_due_total"],
                "outstanding": it["outstanding"],
            }
            for it in items
        ],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.post("/payments", response_model=RentPaymentSchema, summary="Record rent payment")
async def create_payment(
    payload: RentPaymentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Record rent payment."""
    payment = await record_rent_payment(
        db,
        actor=current_user,  # type: ignore[arg-type]
        charge_id=payload.charge_id,
        amount_paid=payload.amount_paid,
        paid_at=payload.paid_at,
        payment_method=payload.payment_method,
        reference=payload.reference,
        notes=payload.notes,
        receipt_document_id=payload.receipt_document_id,
    )
    return RentPaymentSchema.model_validate(payment)


@router.post("/charges/{charge_id}/tenant-payment-intent", response_model=RentPaymentSchema, summary="Create tenant payment intent")
async def tenant_payment_intent(
    charge_id: int,
    payload: RentPaymentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create tenant payment intent."""
    payment = await record_rent_payment(
        db,
        actor=current_user,  # type: ignore[arg-type]
        charge_id=charge_id,
        amount_paid=payload.amount_paid,
        paid_at=payload.paid_at,
        payment_method=payload.payment_method,
        reference=payload.reference,
        notes=payload.notes,
        receipt_document_id=payload.receipt_document_id,
    )
    return RentPaymentSchema.model_validate(payment)


@router.get("/payments", response_model=CursorPage[RentPaymentSchema], summary="List rent payments")
async def list_payments(
    as_tenant: bool = Query(False),
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    lease_id: int | None = Query(None),
    property_id: int | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List rent payments."""
    payments, next_payload, total = await list_rent_payments(
        db,
        actor=current_user,  # type: ignore[arg-type]
        as_tenant=as_tenant,
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [RentPaymentSchema.model_validate(p) for p in payments],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )
