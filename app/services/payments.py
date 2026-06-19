from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BadRequestException, ServiceUnavailableException
from app.core.logging import get_logger
from app.models.bookings import Booking
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payments import PaymentMethod
from app.schemas.payment import (
    PaymentMethodCreate,
    PaymentMethodUpdate,
    RazorpayOrderResponse,
)

logger = get_logger(__name__)


def _get_razorpay_client() -> Any:
    """Return a configured Razorpay client, or raise if not configured."""
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_SECRET:
        raise ServiceUnavailableException(
            detail="Razorpay is not configured on the server.",
            error_code="RAZORPAY_NOT_CONFIGURED",
        )
    try:
        import razorpay  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover - dependency is required
        raise ServiceUnavailableException(
            detail="Razorpay SDK is not installed.",
            error_code="RAZORPAY_SDK_MISSING",
        ) from e
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_SECRET))


def _amount_to_paise(amount: float) -> int:
    """Razorpay expects amounts in the smallest currency unit (paise for INR)."""
    return int(round(amount * 100))


async def create_razorpay_order(
    db: AsyncSession, booking_id: int, user_id: int
) -> RazorpayOrderResponse:
    """Create a Razorpay order for a booking payment."""
    booking = await _get_user_booking(db, booking_id, user_id)

    if booking.payment_status == PaymentStatus.paid:
        raise BadRequestException(
            detail="Booking is already paid.",
            error_code="BOOKING_ALREADY_PAID",
        )
    if booking.booking_status == BookingStatus.cancelled:
        raise BadRequestException(
            detail="Cannot pay for a cancelled booking.",
            error_code="BOOKING_CANCELLED",
        )

    amount = float(booking.total_amount or 0.0)
    if amount <= 0:
        raise BadRequestException(
            detail="Booking total must be greater than zero.",
            error_code="INVALID_AMOUNT",
        )

    client = _get_razorpay_client()
    currency = settings.RAZORPAY_CURRENCY
    try:
        order = client.order.create(
            {
                "amount": _amount_to_paise(amount),
                "currency": currency,
                "receipt": f"bk_{booking.id}_{booking.booking_reference}",
                "notes": {
                    "booking_id": str(booking.id),
                    "user_id": str(user_id),
                    "booking_reference": booking.booking_reference,
                },
                "payment_capture": 1,
            }
        )
    except Exception as e:
        logger.error(
            "Razorpay order creation failed",
            extra={"booking_id": booking_id, "error": str(e)},
        )
        raise ServiceUnavailableException(
            detail="Failed to create payment order. Please try again.",
            error_code="RAZORPAY_ORDER_FAILED",
        ) from e

    # Persist the order id on the booking so verification can confirm the
    # order belongs to this booking (prevents cross-booking payment reuse).
    booking.razorpay_order_id = order["id"]
    await db.flush()

    logger.info(
        "Razorpay order created",
        extra={
            "booking_id": booking_id,
            "order_id": order.get("id"),
            "amount": amount,
        },
    )

    return RazorpayOrderResponse(
        order_id=order["id"],
        amount=amount,
        currency=currency,
        key_id=settings.RAZORPAY_KEY_ID,
        booking_id=booking.id,
        notes={
            "booking_id": str(booking.id),
            "booking_reference": booking.booking_reference,
        },
    )


async def verify_razorpay_payment(
    db: AsyncSession,
    booking_id: int,
    user_id: int,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify a Razorpay payment signature and mark the booking as paid."""
    booking = await _get_user_booking(db, booking_id, user_id)

    # Order-binding check: the order must have been created for this booking.
    # Prevents reusing an order/payment from a cheap booking to pay an
    # expensive one (the original P1 payment-confusion bug).
    if not booking.razorpay_order_id or booking.razorpay_order_id != razorpay_order_id:
        raise BadRequestException(
            detail="Razorpay order does not belong to this booking.",
            error_code="ORDER_BOOKING_MISMATCH",
        )

    secret = settings.RAZORPAY_SECRET
    if not secret:
        raise ServiceUnavailableException(
            detail="Razorpay is not configured on the server.",
            error_code="RAZORPAY_NOT_CONFIGURED",
        )

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, razorpay_signature):
        logger.warning(
            "Razorpay signature mismatch",
            extra={"booking_id": booking_id, "order_id": razorpay_order_id},
        )
        raise BadRequestException(
            detail="Payment signature verification failed.",
            error_code="RAZORPAY_SIGNATURE_INVALID",
        )

    # Fetch the payment from Razorpay to verify amount and capture status.
    # This guards against a client presenting a real (signed) payment that
    # was for a different amount or not yet captured.
    client = _get_razorpay_client()
    try:
        payment = client.payment.fetch(razorpay_payment_id)
    except Exception as e:
        logger.error(
            "Razorpay payment fetch failed",
            extra={"booking_id": booking_id, "payment_id": razorpay_payment_id, "error": str(e)},
        )
        raise ServiceUnavailableException(
            detail="Failed to verify payment with Razorpay. Please try again.",
            error_code="RAZORPAY_PAYMENT_FETCH_FAILED",
        ) from e

    if payment.get("order_id") != razorpay_order_id:
        raise BadRequestException(
            detail="Payment does not belong to the provided order.",
            error_code="PAYMENT_ORDER_MISMATCH",
        )
    expected_paise = _amount_to_paise(float(booking.total_amount or 0))
    if int(payment.get("amount", 0)) != expected_paise:
        logger.warning(
            "Razorpay amount mismatch",
            extra={
                "booking_id": booking_id,
                "expected_paise": expected_paise,
                "actual_paise": payment.get("amount"),
            },
        )
        raise BadRequestException(
            detail="Payment amount does not match booking total.",
            error_code="AMOUNT_MISMATCH",
        )
    if payment.get("status") != "captured":
        raise BadRequestException(
            detail="Payment has not been captured.",
            error_code="PAYMENT_NOT_CAPTURED",
        )

    # Mark booking paid (reuse the existing service-level helper).
    booking.payment_status = PaymentStatus.paid
    booking.payment_method = "razorpay"
    booking.transaction_id = razorpay_payment_id
    booking.payment_date = datetime.now(timezone.utc)
    booking.booking_status = BookingStatus.confirmed
    await db.flush()

    logger.info(
        "Razorpay payment verified and booking confirmed",
        extra={
            "booking_id": booking_id,
            "payment_id": razorpay_payment_id,
            "order_id": razorpay_order_id,
        },
    )
    return True


async def list_payment_methods(db: AsyncSession, user_id: int) -> list[PaymentMethod]:
    stmt = (
        select(PaymentMethod)
        .where(PaymentMethod.user_id == user_id)
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def add_payment_method(
    db: AsyncSession, user_id: int, data: PaymentMethodCreate
) -> PaymentMethod:
    if data.is_default:
        await _clear_default_methods(db, user_id)
    method = PaymentMethod(
        user_id=user_id,
        method_type=data.method_type,
        brand=data.brand,
        last4=data.last4,
        razorpay_token=data.razorpay_token,
        razorpay_payment_id=data.razorpay_payment_id,
        nickname=data.nickname,
        is_default=1 if data.is_default else 0,
    )
    db.add(method)
    await db.flush()
    await db.refresh(method)
    return method


async def update_payment_method(
    db: AsyncSession, user_id: int, method_id: int, data: PaymentMethodUpdate
) -> PaymentMethod | None:
    method = await _get_user_method(db, user_id, method_id)
    if method is None:
        return None
    if data.is_default is True:
        await _clear_default_methods(db, user_id)
    if data.nickname is not None:
        method.nickname = data.nickname
    if data.is_default is not None:
        method.is_default = 1 if data.is_default else 0
    await db.flush()
    await db.refresh(method)
    return method


async def delete_payment_method(
    db: AsyncSession, user_id: int, method_id: int
) -> bool:
    method = await _get_user_method(db, user_id, method_id)
    if method is None:
        return False
    await db.delete(method)
    await db.flush()
    return True


async def _get_user_booking(
    db: AsyncSession, booking_id: int, user_id: int
) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id)
    booking = (await db.execute(stmt)).scalar_one_or_none()
    if booking is None:
        raise BadRequestException(
            detail="Booking not found.",
            error_code="BOOKING_NOT_FOUND",
        )
    if booking.user_id != user_id:
        raise BadRequestException(
            detail="Booking does not belong to user.",
            error_code="BOOKING_FORBIDDEN",
        )
    return booking


async def _get_user_method(
    db: AsyncSession, user_id: int, method_id: int
) -> PaymentMethod | None:
    stmt = select(PaymentMethod).where(
        PaymentMethod.id == method_id, PaymentMethod.user_id == user_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _clear_default_methods(db: AsyncSession, user_id: int) -> None:
    stmt = select(PaymentMethod).where(
        PaymentMethod.user_id == user_id, PaymentMethod.is_default == 1
    )
    rows = (await db.execute(stmt)).scalars().all()
    for row in rows:
        row.is_default = 0
    if rows:
        await db.flush()
