from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.schemas.common import MessageResponse
from app.schemas.payment import (
    PaymentMethodCreate,
    PaymentMethodOut,
    PaymentMethodUpdate,
    RazorpayOrderRequest,
    RazorpayOrderResponse,
    RazorpayVerifyRequest,
)
from app.schemas.user import User as UserSchema
from app.services.payments import (
    add_payment_method,
    create_razorpay_order,
    delete_payment_method,
    list_payment_methods,
    update_payment_method,
    verify_razorpay_payment,
)

router = APIRouter()


@router.post(
    "/razorpay/order",
    response_model=RazorpayOrderResponse,
    summary="Create a Razorpay order for a booking",
)
async def create_order(
    payload: RazorpayOrderRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_razorpay_order(db, payload.booking_id, current_user.id)


@router.post(
    "/razorpay/verify",
    response_model=MessageResponse,
    summary="Verify a Razorpay payment and mark booking paid",
)
async def verify_payment(
    payload: RazorpayVerifyRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await verify_razorpay_payment(
        db,
        booking_id=payload.booking_id,
        user_id=current_user.id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Payment verification failed")
    return MessageResponse(message="Payment verified successfully")


@router.get(
    "/methods",
    response_model=list[PaymentMethodOut],
    summary="List the current user's saved payment methods",
)
async def list_methods(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_payment_methods(db, current_user.id)


@router.post(
    "/methods",
    response_model=PaymentMethodOut,
    summary="Save a new payment method for the current user",
)
async def add_method(
    payload: PaymentMethodCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await add_payment_method(db, current_user.id, payload)


@router.put(
    "/methods/{method_id}",
    response_model=PaymentMethodOut,
    summary="Update a saved payment method",
)
async def update_method(
    method_id: int,
    payload: PaymentMethodUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    method = await update_payment_method(db, current_user.id, method_id, payload)
    if method is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    return method


@router.delete(
    "/methods/{method_id}",
    response_model=MessageResponse,
    summary="Delete a saved payment method",
)
async def remove_method(
    method_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_payment_method(db, current_user.id, method_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Payment method not found")
    return MessageResponse(message="Payment method removed")
