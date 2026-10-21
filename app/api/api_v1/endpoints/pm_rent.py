from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import RentChargeStatus, RentPaymentStatus
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_rent import (
    RentCharge as RentChargeSchema,
)
from app.schemas.pm_rent import (
    RentChargeGenerateRequest,
    RentChargeGenerateResult,
    RentChargeWithTotals,
    RentPaymentCreate,
)
from app.schemas.pm_rent import (
    RentPayment as RentPaymentSchema,
)
from app.schemas.user import User as UserSchema
from app.services.pm_rent import (
    delete_pending_rent_payment,
    generate_rent_charges,
    list_rent_charges,
    list_rent_payments,
    record_rent_payment,
    settle_rent_payment,
)

router = APIRouter()


@router.post(
    "/charges/generate", response_model=RentChargeGenerateResult, summary="Generate rent charges"
)
async def generate_charges(
    payload: RentChargeGenerateRequest | None = None,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate rent charges. The body is optional. start_month is the first day of the first month."""
    body = payload or RentChargeGenerateRequest()
    result = await generate_rent_charges(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=body.owner_id,
        lease_id=body.lease_id,
        start_month=body.start_month,
        months=body.months,
    )
    return RentChargeGenerateResult(**result)


@router.get(
    "/charges", response_model=CursorPage[RentChargeWithTotals], summary="List rent charges"
)
async def get_charges(
    as_tenant: bool = Query(
        False, description="If true, return charges for the current tenant user"
    ),
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    lease_id: int | None = Query(None),
    property_id: int | None = Query(None),
    status_filter: RentChargeStatus | None = Query(None, alias="status"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List rent charges. status=overdue includes open charges past their grace period."""
    filters = {
        "as_tenant": as_tenant,
        "owner_id": owner_id,
        "lease_id": lease_id,
        "property_id": property_id,
        "status": status_filter,
    }
    items, next_payload, total = await list_rent_charges(
        db,
        actor=current_user,  # type: ignore[arg-type]
        as_tenant=as_tenant,
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        status=status_filter,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    rows = [
        RentChargeWithTotals(
            charge=RentChargeSchema.model_validate(it["charge"]).model_copy(
                update={"status": it["status"]}
            ),
            amount_paid_total=it["amount_paid_total"],
            amount_due_total=it["amount_due_total"],
            outstanding=it["outstanding"],
        )
        for it in items
    ]
    return build_cursor_page(
        rows, limit=page.limit, next_payload=next_payload, total=total, filters=filters
    )


@router.post(
    "/payments",
    response_model=RentPaymentSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record rent payment",
)
async def create_payment(
    payload: RentPaymentCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a rent payment. A tenant request creates a pending record; an owner, agent or admin settles it."""
    payment = await record_rent_payment(
        db,
        actor=current_user,  # type: ignore[arg-type]
        charge_id=payload.charge_id,
        amount_paid=payload.amount_paid,
        paid_at=payload.paid_at,
        payment_method=payload.payment_method.value if payload.payment_method else None,
        reference=payload.reference,
        notes=payload.notes,
        receipt_document_id=payload.receipt_document_id,
    )
    return RentPaymentSchema.model_validate(payment)


@router.post(
    "/payments/{payment_id}/settle",
    response_model=RentPaymentSchema,
    summary="Settle a pending rent payment",
)
async def settle_payment(
    payment_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm a pending tenant claim. Owner, agent or admin only. The claim then counts toward the charge."""
    payment = await settle_rent_payment(
        db,
        actor=current_user,  # type: ignore[arg-type]
        payment_id=payment_id,
    )
    return RentPaymentSchema.model_validate(payment)


@router.delete(
    "/payments/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw or reject a pending rent payment",
)
async def delete_payment(
    payment_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a pending tenant claim. The tenant withdraws its own claim; owner, agent or admin rejects it."""
    await delete_pending_rent_payment(
        db,
        actor=current_user,  # type: ignore[arg-type]
        payment_id=payment_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/payments", response_model=CursorPage[RentPaymentSchema], summary="List rent payments")
async def list_payments(
    as_tenant: bool = Query(False),
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    lease_id: int | None = Query(None),
    property_id: int | None = Query(None),
    status_filter: RentPaymentStatus | None = Query(None, alias="status"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List rent payments."""
    filters = {
        "as_tenant": as_tenant,
        "owner_id": owner_id,
        "lease_id": lease_id,
        "property_id": property_id,
        "status": status_filter,
    }
    payments, next_payload, total = await list_rent_payments(
        db,
        actor=current_user,  # type: ignore[arg-type]
        as_tenant=as_tenant,
        owner_id=owner_id,
        lease_id=lease_id,
        property_id=property_id,
        status=status_filter,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [RentPaymentSchema.model_validate(p) for p in payments],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )
