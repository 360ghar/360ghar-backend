from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.config import settings
from app.core.db_resilience import apply_statement_timeout, execute_with_transient_retry
from app.core.exceptions import (
    BadRequestException,
    BookingConflictError,
    PropertyNotFoundException,
)
from app.core.logging import get_logger
from app.models.bookings import Booking
from app.models.enums import BookingStatus, PaymentStatus, PropertyPurpose
from app.models.properties import Property
from app.models.users import User
from app.schemas.booking import BookingCreate, BookingPayment, BookingReview, BookingUpdate
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead

logger = get_logger(__name__)

NOT_PAYABLE_STATUSES = frozenset(
    {BookingStatus.cancelled, BookingStatus.completed, BookingStatus.checked_out}
)


def _money(value: float) -> float:
    """Round a computed amount to the 2 decimals bookings store (NUMERIC(12,2))."""
    return round(float(value), 2)


def _utc_date(value: datetime):
    """Calendar date of a datetime in UTC. Naive values are read as UTC.

    Night counts use this date, so a guest's UTC offset cannot change the nights
    quoted by pricing and the nights stored at booking time.
    """
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.date()


def _booking_load_options():
    """Eager-load what the guest and staff booking summaries read."""
    return (
        selectinload(Booking.property).selectinload(Property.images),
        selectinload(Booking.user),
    )


def _apply_pricing_fields(pricing: dict, target: dict | Booking) -> None:
    """Apply pricing fields to either a dictionary or a Booking object to avoid drift."""
    fields = ["base_amount", "taxes_amount", "service_charges", "total_amount"]
    if isinstance(target, dict):
        target["nights"] = pricing["nights"]
        for field in fields:
            target[field] = _money(pricing[field])
        target["discount_amount"] = _money(pricing.get("discount_amount", 0.0))
    else:
        target.nights = pricing["nights"]
        for field in fields:
            setattr(target, field, _money(pricing[field]))
        target.discount_amount = _money(pricing.get("discount_amount", 0.0))


async def _find_idempotent_booking(db: AsyncSession, created_by_id: int, key: str) -> Booking | None:
    stmt = (
        select(Booking)
        .options(*_booking_load_options())
        .where(Booking.created_by_user_id == created_by_id, Booking.idempotency_key == key)
    )
    return (await db.execute(stmt)).scalar_one_or_none()

async def create_booking(
    db: AsyncSession,
    user_id: int,
    booking: BookingCreate,
    *,
    created_by_id: int | None = None,
    idempotency_key: str | None = None,
) -> Booking:
    """Create a booking for ``user_id`` (the guest).

    ``created_by_id`` is the caller (defaults to ``user_id``). With an
    ``idempotency_key``, a repeated call from the same caller returns the booking the
    first call created.
    """
    creator_id = user_id if created_by_id is None else created_by_id
    if idempotency_key is not None:
        existing = await _find_idempotent_booking(db, creator_id, idempotency_key)
        if existing is not None:
            return existing

    booking_data = booking.model_dump(exclude={"user_id"})
    booking_data["user_id"] = user_id
    booking_data["created_by_user_id"] = creator_id
    booking_data["idempotency_key"] = idempotency_key
    booking_data["booking_reference"] = f"BK{uuid.uuid4().hex[:8].upper()}"

    # Calculate nights using UTC calendar dates (not raw timedelta seconds) so that
    # e.g. check-in at 14:00 and check-out at 11:00 next day correctly yields 1 night.
    check_in = booking_data["check_in_date"]
    check_out = booking_data["check_out_date"]
    nights = (_utc_date(check_out) - _utc_date(check_in)).days
    if nights <= 0:
        logger.warning(
            "Invalid date range in booking creation",
            extra={"user_id": user_id, "property_id": booking_data["property_id"],
                   "check_in": str(check_in), "check_out": str(check_out), "reason": "invalid_date_range"},
        )
        raise BadRequestException(detail="Invalid date range: check-out must be after check-in", error_code="INVALID_DATE_RANGE")

    # Check availability before creating the booking
    availability = await check_availability(
        db,
        booking_data["property_id"],
        booking_data["check_in_date"].isoformat() if hasattr(booking_data["check_in_date"], 'isoformat') else str(booking_data["check_in_date"]),
        booking_data["check_out_date"].isoformat() if hasattr(booking_data["check_out_date"], 'isoformat') else str(booking_data["check_out_date"]),
        booking_data["guests"],
    )
    if not availability.get("available", False):
        reason = availability.get("reason", "Property not available for these dates")
        if reason == "Property not found":
            raise PropertyNotFoundException()
        raise BookingConflictError(detail=reason)

    # Calculate pricing before creating the booking
    pricing = await calculate_pricing(
        db,
        booking_data["property_id"],
        booking_data["check_in_date"],
        booking_data["check_out_date"],
        booking_data["guests"],
    )
    if isinstance(pricing, dict) and pricing.get("error"):
        raise BadRequestException(
            detail=pricing["error"], error_code=pricing.get("error_code", "PRICING_UNAVAILABLE")
        )

    _apply_pricing_fields(pricing, booking_data)

    # Set initial statuses
    booking_data["booking_status"] = BookingStatus.pending
    booking_data["payment_status"] = PaymentStatus.pending

    db_booking = Booking(**booking_data)
    try:
        # Savepoint: a concurrent request with the same key fails the unique index.
        async with db.begin_nested():
            db.add(db_booking)
            await db.flush()
    except IntegrityError:
        if idempotency_key is None:
            raise
        existing = await _find_idempotent_booking(db, creator_id, idempotency_key)
        if existing is None:
            raise
        return existing
    await db.refresh(db_booking)
    logger.info(
        "Booking created",
        extra={
            "booking_id": db_booking.id,
            "booking_reference": db_booking.booking_reference,
            "user_id": user_id,
            "property_id": booking_data["property_id"],
            "check_in": str(booking_data["check_in_date"]),
            "check_out": str(booking_data["check_out_date"]),
            "nights": nights,
            "total_amount": float(booking_data["total_amount"]),
        },
    )
    return db_booking

async def get_booking(db: AsyncSession, booking_id: int):
    """Get a booking by ID"""
    stmt = select(Booking).options(*_booking_load_options()).where(Booking.id == booking_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_user_bookings(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    status: BookingStatus | None = None,
) -> tuple[list, dict | None, int | None]:
    """Get all bookings for a user (keyset-paginated), optionally by status."""
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    # Eager-load the property so serialize_booking can embed it without an
    # async lazy-load (MissingGreenlet) when rendering the visit/booking widgets.
    stmt = (
        select(Booking)
        .options(*_booking_load_options())
        .where(Booking.user_id == user_id)
    )
    if status is not None:
        stmt = stmt.where(Booking.booking_status == status)
    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(count_stmt),
            operation_name="booking_user_list_count",
        )
        count_total = count_result.scalar_one()
    predicate = keyset_filter(Booking.created_at, Booking.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Booking.created_at.desc(), Booking.id.desc()).limit(limit + 1)
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="booking_user_list_query",
    )
    rows = list(result.scalars().all())
    rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda booking: booking.created_at,
        item_id=lambda booking: booking.id,
    )
    return rows, next_payload, count_total

async def get_user_upcoming_bookings(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list, dict | None, int | None]:
    """Get upcoming bookings for a user (keyset-paginated)."""
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    now = datetime.now(timezone.utc)
    stmt = select(Booking).options(*_booking_load_options()).where(
        Booking.user_id == user_id,
        Booking.check_in_date > now,
        Booking.booking_status.in_([BookingStatus.confirmed, BookingStatus.pending])
    )
    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(count_stmt),
            operation_name="booking_upcoming_list_count",
        )
        count_total = count_result.scalar_one()
    predicate = keyset_filter(Booking.check_in_date, Booking.id, cursor_payload, descending=False)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Booking.check_in_date.asc(), Booking.id.asc()).limit(limit + 1)
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="booking_upcoming_list_query",
    )
    rows = list(result.scalars().all())
    rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda booking: booking.check_in_date,
        item_id=lambda booking: booking.id,
    )
    return rows, next_payload, count_total

async def get_user_past_bookings(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list, dict | None, int | None]:
    """Get past bookings for a user (keyset-paginated)."""
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    now = datetime.now(timezone.utc)
    stmt = select(Booking).options(*_booking_load_options()).where(
        Booking.user_id == user_id,
        Booking.check_out_date < now
    )
    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(count_stmt),
            operation_name="booking_past_list_count",
        )
        count_total = count_result.scalar_one()
    predicate = keyset_filter(Booking.check_out_date, Booking.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Booking.check_out_date.desc(), Booking.id.desc()).limit(limit + 1)
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="booking_past_list_query",
    )
    rows = list(result.scalars().all())
    rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda booking: booking.check_out_date,
        item_id=lambda booking: booking.id,
    )
    return rows, next_payload, count_total

async def update_booking(
    db: AsyncSession,
    booking_id: int,
    booking_update: BookingUpdate,
):
    """Update a booking. The route enforces that only staff set internal_notes.

    When dates or guests change, pricing and occupancy are re-validated and the
    booking reverts to ``pending`` payment/booking status if the total changes
    (prevents price manipulation via update).
    """
    stmt = select(Booking).where(Booking.id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
        update_data = booking_update.model_dump(exclude_unset=True)

        # Recalculate pricing and availability if dates or guests change
        new_check_in = update_data.get("check_in_date", booking.check_in_date)
        new_check_out = update_data.get("check_out_date", booking.check_out_date)
        new_guests = update_data.get("guests", booking.guests)

        if (
            "check_in_date" in update_data
            or "check_out_date" in update_data
            or "guests" in update_data
        ):
            if new_check_in is not None and new_check_out is not None:
                if new_check_in.tzinfo is None:
                    new_check_in = new_check_in.replace(tzinfo=timezone.utc)
                    update_data["check_in_date"] = new_check_in
                if new_check_out.tzinfo is None:
                    new_check_out = new_check_out.replace(tzinfo=timezone.utc)
                    update_data["check_out_date"] = new_check_out

                if new_check_out <= new_check_in:
                    raise BadRequestException(detail="Invalid date range: check-out must be after check-in")

                availability = await check_availability(
                    db,
                    booking.property_id,
                    new_check_in.isoformat(),
                    new_check_out.isoformat(),
                    new_guests,
                )
                if not availability.get("available", False):
                    reason = availability.get("reason", "Property not available for these dates")
                    raise BookingConflictError(detail=reason)

                pricing = await calculate_pricing(
                    db,
                    booking.property_id,
                    new_check_in,
                    new_check_out,
                    new_guests,
                )
                if isinstance(pricing, dict) and pricing.get("error"):
                    raise BadRequestException(detail=pricing["error"])

                # If the price changes, revoke paid/confirmed status so the
                # difference must be paid before the booking is confirmed again.
                if round(float(pricing["total_amount"]), 2) != round(float(booking.total_amount), 2):
                    booking.payment_status = PaymentStatus.pending
                    booking.booking_status = BookingStatus.pending

                _apply_pricing_fields(pricing, booking)

        for field, value in update_data.items():
            setattr(booking, field, value)

        await db.flush()
        await db.refresh(booking)

    return booking

async def cancel_booking(db: AsyncSession, booking_id: int, reason: str):
    """Cancel a booking.

    Guards:
    - Raises BadRequestException if the booking is already cancelled (idempotency).
    - Automatically marks payment as refunded and records refund_amount when the
      booking was already paid, so accounting is never left in an inconsistent state.
    """
    stmt = select(Booking).where(Booking.id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
        # Guard: prevent double-cancellation
        if booking.booking_status == BookingStatus.cancelled:
            raise BadRequestException(detail="Booking is already cancelled")

        booking.booking_status = BookingStatus.cancelled
        booking.cancellation_date = datetime.now(timezone.utc)
        booking.cancellation_reason = reason

        # If the booking was paid, mark it as refunded so accounting stays consistent.
        if booking.payment_status == PaymentStatus.paid:
            booking.payment_status = PaymentStatus.refunded
            booking.refund_amount = booking.total_amount
            logger.info(
                "Paid booking cancelled — refund recorded",
                extra={
                    "booking_id": booking_id,
                    "user_id": booking.user_id,
                    "refund_amount": float(booking.total_amount),
                },
            )

        await db.flush()
        logger.info(
            "Booking cancelled",
            extra={"booking_id": booking_id, "user_id": booking.user_id, "reason": reason},
        )
        return True

    return False

async def process_payment(db: AsyncSession, payment_data: BookingPayment):
    """Process payment for a booking.

    Validates that the supplied amount covers the booking total to prevent
    underpayment attacks where a user sends a tiny amount to mark a booking as paid.
    """
    stmt = select(Booking).where(Booking.id == payment_data.booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
        # A cancelled, completed or checked-out booking is not payable. Recording a
        # payment on it would revive a cancelled booking and skip its refund record.
        if booking.booking_status in NOT_PAYABLE_STATUSES:
            raise BadRequestException(
                detail="Booking cannot take a payment in its current status",
                error_code="BOOKING_NOT_PAYABLE",
            )

        # Prevent payment amount bypass
        if round(float(payment_data.amount), 2) < round(float(booking.total_amount), 2):
            logger.warning(
                "Payment amount mismatch",
                extra={
                    "booking_id": booking.id,
                    "expected": float(booking.total_amount),
                    "received": float(payment_data.amount),
                },
            )
            raise BadRequestException(detail="Payment amount is insufficient")

        booking.payment_status = PaymentStatus.paid
        booking.payment_method = payment_data.payment_method
        booking.transaction_id = payment_data.transaction_id
        booking.payment_date = datetime.now(timezone.utc)
        booking.booking_status = BookingStatus.confirmed
        await db.flush()
        logger.info(
            "Booking payment processed",
            extra={
                "booking_id": payment_data.booking_id,
                "payment_method": payment_data.payment_method,
                "transaction_id": payment_data.transaction_id,
            },
        )
        return True

    return False

async def add_review(db: AsyncSession, review_data: BookingReview, actor_id: int):
    """Add a guest review to a completed booking.

    Guards:
    - Only the guest who made the booking (booking.user_id) may submit a guest review.
    - The booking must be in ``completed`` or ``checked_out`` status (stay must have occurred).
    """
    stmt = select(Booking).where(Booking.id == review_data.booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
        if booking.user_id != actor_id:
            raise BadRequestException(
                detail="Only the booking guest may submit a review",
                error_code="REVIEW_NOT_ALLOWED",
            )

        if booking.booking_status not in (BookingStatus.completed, BookingStatus.checked_out):
            raise BadRequestException(detail="Booking must be completed before a review can be submitted")

        booking.guest_rating = review_data.guest_rating
        booking.guest_review = review_data.guest_review
        await db.flush()
        return True

    return False

async def check_occupancy(db: AsyncSession, property_id: int, guests: int) -> dict:
    """Check that the property exists and the guest count fits max_occupancy.

    Business rule: overlapping bookings are allowed, so no dates are checked.
    Returns ``{"available": bool, "reason"?: str, "max_occupancy"?: int}``. An unknown
    property also carries ``error_code="PROPERTY_NOT_FOUND"``.
    """
    # Get property max occupancy
    prop_stmt = select(Property).where(Property.id == property_id)
    prop_result = await db.execute(prop_stmt)
    property_obj = prop_result.scalar_one_or_none()

    if not property_obj:
        return {
            "available": False,
            "reason": "Property not found",
            "error_code": "PROPERTY_NOT_FOUND",
        }

    if property_obj.max_occupancy and guests > property_obj.max_occupancy:
        logger.info(
            "Occupancy check: guests exceed max occupancy",
            extra={
                "property_id": property_id, "guests": guests,
                "max_occupancy": property_obj.max_occupancy,
            },
        )
        return {"available": False, "reason": f"Property can accommodate maximum {property_obj.max_occupancy} guests"}

    logger.info(
        "Occupancy check passed",
        extra={
            "property_id": property_id, "guests": guests,
            "max_occupancy": property_obj.max_occupancy,
        },
    )
    return {"available": True, "max_occupancy": property_obj.max_occupancy}


async def check_availability(db: AsyncSession, property_id: int, check_in_date: str, check_out_date: str, guests: int):
    """Dict contract for MCP tools and booking create/update.

    The dates do not change the answer (overlapping bookings are allowed). See check_occupancy.
    """
    return await check_occupancy(db, property_id, guests)

async def calculate_pricing(db: AsyncSession, property_id: int, check_in_date: datetime, check_out_date: datetime, guests: int):
    """Calculate pricing for a booking.

    Nightly rate, in order:
    - ``daily_rate`` when set (the nightly rate for short stays).
    - Otherwise, for a short-stay property, an error: base_price is not a nightly rate.
    - Otherwise ``monthly_rent / 30``, then ``base_price / 30`` (base_price is the rent anchor).

    Nights are counted on UTC calendar dates. Taxes and service charges are added to
    the subtotal. Money is rounded to 2 decimals.

    Errors return ``{"error": message, "error_code": code}``. The HTTP route turns
    them into 4xx responses. Internal callers check the ``error`` key.
    """
    stmt = select(Property).where(Property.id == property_id)
    result = await db.execute(stmt)
    property_obj = result.scalar_one_or_none()

    if not property_obj:
        return {"error": "Property not found", "error_code": "PROPERTY_NOT_FOUND"}

    nights = (_utc_date(check_out_date) - _utc_date(check_in_date)).days
    if nights <= 0:
        return {"error": "Invalid date range", "error_code": "INVALID_DATE_RANGE"}

    if property_obj.daily_rate is not None:
        per_night_rate = float(property_obj.daily_rate)
    elif property_obj.purpose == PropertyPurpose.short_stay:
        return {
            "error": "Property has no nightly rate configured",
            "error_code": "PRICING_UNAVAILABLE",
        }
    elif property_obj.monthly_rent is not None:
        per_night_rate = float(property_obj.monthly_rent) / 30
    else:
        per_night_rate = float(property_obj.base_price or 0.0) / 30

    if per_night_rate <= 0:
        return {
            "error": "Property has no valid rate configured",
            "error_code": "PRICING_UNAVAILABLE",
        }

    base_amount = _money(per_night_rate * nights)

    # Placeholder discount logic
    discount_amount = 0.0

    # Calculate taxes and service charges on the discounted subtotal
    taxable_subtotal = max(base_amount - discount_amount, 0.0)
    taxes_amount = _money(taxable_subtotal * settings.GST_RATE)
    service_charges = _money(taxable_subtotal * settings.SERVICE_CHARGE_RATE)

    total_amount = _money(taxable_subtotal + taxes_amount + service_charges)

    return {
        "property_id": property_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "guests": guests,
        "nights": nights,
        "base_amount": base_amount,
        "taxes_amount": taxes_amount,
        "service_charges": service_charges,
        "discount_amount": discount_amount,
        "total_amount": total_amount,
        "breakdown": {
            "base_rate_per_night": per_night_rate,
            "total_nights": nights,
            "subtotal": base_amount,
            "discount": discount_amount,
            "taxes_18_percent": taxes_amount,
            "service_charge_5_percent": service_charges,
            "final_total": total_amount,
        },
    }


async def get_all_bookings(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    status: str | None = None,
    payment_status: str | None = None,
    filter_agent_id: int | None = None,
    property_id: int | None = None,
    user_id: int | None = None,
    q: str | None = None,
) -> tuple[list, dict | None, int | None]:
    """Global bookings listing with optional filters and keyset pagination.

    ``q`` matches the booking reference, the primary guest's name or email, or the property title.
    """
    await apply_statement_timeout(db, settings.DB_READ_STATEMENT_TIMEOUT_MS)
    Owner = aliased(User)

    stmt = select(Booking).options(*_booking_load_options())
    filters = []
    if status is not None:
        filters.append(Booking.booking_status == status)
    if payment_status is not None:
        filters.append(Booking.payment_status == payment_status)
    if property_id is not None:
        filters.append(Booking.property_id == property_id)
    if user_id is not None:
        filters.append(Booking.user_id == user_id)

    needs_guest = filter_agent_id is not None
    if needs_guest:
        stmt = stmt.outerjoin(User, Booking.user_id == User.id).outerjoin(Property, Booking.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        filters.append(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))
    if q:
        pattern = f"%{q.strip()}%"
        if not needs_guest:
            stmt = stmt.outerjoin(Property, Booking.property_id == Property.id)
        filters.append(or_(
            Booking.booking_reference.ilike(pattern),
            Booking.primary_guest_name.ilike(pattern),
            Booking.primary_guest_email.ilike(pattern),
            Property.title.ilike(pattern),
        ))

    if filters:
        stmt = stmt.where(and_(*filters))

    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(count_stmt),
            operation_name="booking_all_list_count",
        )
        count_total = count_result.scalar_one()

    predicate = keyset_filter(Booking.created_at, Booking.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Booking.created_at.desc(), Booking.id.desc()).limit(limit + 1)
    result = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="booking_all_list_query",
    )
    rows = list(result.scalars().all())
    rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda booking: booking.created_at,
        item_id=lambda booking: booking.id,
    )
    return rows, next_payload, count_total
