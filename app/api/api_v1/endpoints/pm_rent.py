from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import RentChargeStatus
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


@router.post("/charges/generate")
async def generate_charges(
    payload: RentChargeGenerateRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await generate_rent_charges(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=payload.owner_id,
        lease_id=payload.lease_id,
        start_month=payload.start_month,
        months=payload.months,
    )


@router.get("/charges", response_model=list[RentChargeWithTotals])
async def get_charges(
    as_tenant: bool = Query(False, description="If true, return charges for the current tenant user"),
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    lease_id: int | None = Query(None),
    property_id: int | None = Query(None),
    status: RentChargeStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    items = await list_rent_charges(
        db,
        actor=current_user,  # type: ignore[arg-type]
        as_tenant=as_tenant,
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    # items already shaped for RentChargeWithTotals
    return [
        {
            "charge": it["charge"],
            "amount_paid_total": it["amount_paid_total"],
            "amount_due_total": it["amount_due_total"],
            "outstanding": it["outstanding"],
        }
        for it in items
    ]


@router.post("/payments", response_model=RentPaymentSchema)
async def create_payment(
    payload: RentPaymentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
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


@router.post("/charges/{charge_id}/tenant-payment-intent", response_model=RentPaymentSchema)
async def tenant_payment_intent(
    charge_id: int,
    payload: RentPaymentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
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


@router.get("/payments", response_model=list[RentPaymentSchema])
async def list_payments(
    as_tenant: bool = Query(False),
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    lease_id: int | None = Query(None),
    property_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    payments = await list_rent_payments(
        db,
        actor=current_user,  # type: ignore[arg-type]
        as_tenant=as_tenant,
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        limit=limit,
        offset=offset,
    )
    return [RentPaymentSchema.model_validate(p) for p in payments]
