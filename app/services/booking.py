import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import (
    BadRequestException,
    BookingConflictError,
    PropertyNotFoundException,
)
from app.core.logging import get_logger
from app.core.utils import make_tz_aware
from app.models.bookings import Booking
from app.models.enums import BookingStatus, PaymentStatus
from app.models.properties import Property
from app.schemas.booking import BookingCreate, BookingPayment, BookingReview, BookingUpdate

logger = get_logger(__name__)

async def create_booking(db: AsyncSession, user_id: int, booking: BookingCreate):
    """Create a new booking"""
    booking_data = booking.model_dump()
    booking_data["user_id"] = user_id
    booking_data["booking_reference"] = f"BK{uuid.uuid4().hex[:8].upper()}"

    # Calculate nights
    check_in = booking_data["check_in_date"]
    check_out = booking_data["check_out_date"]
    nights = (check_out - check_in).days
    if nights <= 0:
        logger.warning(
            "Invalid date range in booking creation",
            extra={"user_id": user_id, "property_id": booking_data["property_id"],
                   "check_in": str(check_in), "check_out": str(check_out), "reason": "invalid_date_range"},
        )
        raise BadRequestException(detail="Invalid date range: check-out must be after check-in")

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
        raise BadRequestException(detail=pricing["error"])

    booking_data["nights"] = pricing["nights"]
    booking_data["base_amount"] = pricing["base_amount"]
    booking_data["taxes_amount"] = pricing["taxes_amount"]
    booking_data["service_charges"] = pricing["service_charges"]
    booking_data["discount_amount"] = pricing.get("discount_amount", 0.0)
    booking_data["total_amount"] = pricing["total_amount"]

    # Set initial statuses
    booking_data["booking_status"] = BookingStatus.pending
    booking_data["payment_status"] = PaymentStatus.pending

    db_booking = Booking(**booking_data)
    db.add(db_booking)
    await db.flush()
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
    stmt = select(Booking).where(Booking.id == booking_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_user_bookings(db: AsyncSession, user_id: int):
    """Get all bookings for a user"""
    stmt = select(Booking).where(Booking.user_id == user_id).order_by(Booking.check_in_date.desc())
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    total = len(bookings)

    now = datetime.now(timezone.utc)

    # Calculate counts for different statuses (handle tz-naive dates from DB)
    upcoming = sum(1 for b in bookings if b.check_in_date is not None and (ci := make_tz_aware(b.check_in_date)) is not None and ci > now and b.booking_status in [BookingStatus.confirmed, BookingStatus.pending])
    completed = sum(1 for b in bookings if b.check_out_date is not None and (co := make_tz_aware(b.check_out_date)) is not None and co < now and b.booking_status in [BookingStatus.confirmed, BookingStatus.completed])
    cancelled = sum(1 for b in bookings if b.booking_status == BookingStatus.cancelled)

    return {
        "bookings": bookings,
        "total": total,
        "upcoming": upcoming,
        "completed": completed,
        "cancelled": cancelled,
    }

async def get_user_upcoming_bookings(db: AsyncSession, user_id: int):
    """Get upcoming bookings for a user"""
    now = datetime.now(timezone.utc)
    stmt = select(Booking).where(
        Booking.user_id == user_id,
        Booking.check_in_date > now,
            Booking.booking_status.in_([BookingStatus.confirmed, BookingStatus.pending])
    ).order_by(Booking.check_in_date)
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    return {"bookings": bookings, "total": len(bookings)}

async def get_user_past_bookings(db: AsyncSession, user_id: int):
    """Get past bookings for a user"""
    now = datetime.now(timezone.utc)
    stmt = select(Booking).where(
        Booking.user_id == user_id,
        Booking.check_out_date < now
    ).order_by(Booking.check_out_date.desc())
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    return {"bookings": bookings, "total": len(bookings)}

async def update_booking(db: AsyncSession, booking_id: int, booking_update: BookingUpdate):
    """Update a booking"""
    stmt = select(Booking).where(Booking.id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
        update_data = booking_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(booking, field, value)

        await db.flush()
        await db.refresh(booking)

    return booking

async def cancel_booking(db: AsyncSession, booking_id: int, reason: str):
    """Cancel a booking"""
    stmt = select(Booking).where(Booking.id == booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
        booking.booking_status = BookingStatus.cancelled
        booking.cancellation_date = datetime.now(timezone.utc)
        booking.cancellation_reason = reason
        await db.flush()
        logger.info(
            "Booking cancelled",
            extra={"booking_id": booking_id, "user_id": booking.user_id, "reason": reason},
        )
        return True

    return False

async def process_payment(db: AsyncSession, payment_data: BookingPayment):
    """Process payment for a booking"""
    stmt = select(Booking).where(Booking.id == payment_data.booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
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

async def add_review(db: AsyncSession, review_data: BookingReview):
    """Add a review to a booking"""
    stmt = select(Booking).where(Booking.id == review_data.booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if booking:
        booking.guest_rating = review_data.guest_rating
        booking.guest_review = review_data.guest_review
        await db.flush()
        return True

    return False

async def check_availability(db: AsyncSession, property_id: int, check_in_date: str, check_out_date: str, guests: int):
    """Check if property is available for booking"""
    check_in = datetime.fromisoformat(check_in_date)
    check_out = datetime.fromisoformat(check_out_date)

    # Check for overlapping bookings (include pending to prevent double-booking)
    stmt = select(Booking).where(
        and_(
            Booking.property_id == property_id,
            Booking.booking_status.in_([BookingStatus.pending, BookingStatus.confirmed, BookingStatus.checked_in]),
            # Check for date overlap
            Booking.check_in_date < check_out,
            Booking.check_out_date > check_in
        )
    )
    result = await db.execute(stmt)
    overlapping_bookings = result.scalars().all()

    # Get property max occupancy
    prop_stmt = select(Property).where(Property.id == property_id)
    prop_result = await db.execute(prop_stmt)
    property_obj = prop_result.scalar_one_or_none()

    if not property_obj:
        return {"available": False, "reason": "Property not found"}

    if overlapping_bookings:
        return {"available": False, "reason": "Property already booked for these dates"}

    if property_obj.max_occupancy and guests > property_obj.max_occupancy:
        logger.info(
            "Availability check: guests exceed max occupancy",
            extra={
                "property_id": property_id, "guests": guests,
                "max_occupancy": property_obj.max_occupancy,
                "check_in": check_in_date, "check_out": check_out_date,
            },
        )
        return {"available": False, "reason": f"Property can accommodate maximum {property_obj.max_occupancy} guests"}

    logger.info(
        "Availability check passed",
        extra={
            "property_id": property_id, "guests": guests,
            "max_occupancy": property_obj.max_occupancy,
            "check_in": check_in_date, "check_out": check_out_date,
            "overlapping_bookings": len(overlapping_bookings),
        },
    )
    return {"available": True, "max_occupancy": property_obj.max_occupancy}

async def calculate_pricing(db: AsyncSession, property_id: int, check_in_date: datetime, check_out_date: datetime, guests: int):
    """Calculate pricing for a booking.

    - Uses `daily_rate` if available, otherwise falls back to `base_price`.
    - Computes taxes (18%) and service charges (5%).
    - Applies `discount_amount` (currently 0.0 by default).
    """
    stmt = select(Property).where(Property.id == property_id)
    result = await db.execute(stmt)
    property_obj = result.scalar_one_or_none()

    if not property_obj:
        return {"error": "Property not found"}

    nights = (check_out_date - check_in_date).days
    if nights <= 0:
        return {"error": "Invalid date range"}

    # Choose a per-night rate: prefer daily_rate, else fall back to base_price
    per_night_rate = property_obj.daily_rate if property_obj.daily_rate is not None else property_obj.base_price
    per_night_rate = float(per_night_rate or 0.0)

    if per_night_rate <= 0:
        return {"error": "Property has no valid rate configured"}

    base_amount = per_night_rate * nights

    # Placeholder discount logic
    discount_amount = 0.0

    # Calculate taxes and service charges on the discounted subtotal
    taxable_subtotal = max(base_amount - discount_amount, 0.0)
    taxes_amount = taxable_subtotal * 0.18
    service_charges = taxable_subtotal * 0.05

    total_amount = taxable_subtotal + taxes_amount + service_charges

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
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    filter_agent_id: int | None = None,
    property_id: int | None = None,
    user_id: int | None = None,
):
    """Global bookings listing with optional filters and pagination.

    When filter_agent_id is provided, returns bookings for users/properties assigned to that agent.
    """
    offset = (page - 1) * limit
    from app.models.users import User
    Owner = aliased(User)
    now = datetime.now(timezone.utc)

    base = select(Booking)
    filters = []
    if status:
        filters.append(Booking.booking_status == status)
    if property_id:
        filters.append(Booking.property_id == property_id)
    if user_id:
        filters.append(Booking.user_id == user_id)

    if filter_agent_id is not None:
        # Bookings where the booking user is assigned to agent OR the property's owner is assigned to agent
        from app.models.properties import Property
        from app.models.users import User
        base = base.outerjoin(User, Booking.user_id == User.id).outerjoin(Property, Booking.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        filters.append(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))

    query = base
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(Booking.check_in_date.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    bookings = result.scalars().all()

    # Count total with same filters
    count_query = select(func.count(Booking.id.distinct()))
    if filter_agent_id is not None:
        from app.models.properties import Property
        from app.models.users import User
        count_query = count_query.outerjoin(User, Booking.user_id == User.id).outerjoin(Property, Booking.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        count_query = count_query.where(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))
    if status:
        count_query = count_query.where(Booking.booking_status == status)
    if property_id:
        count_query = count_query.where(Booking.property_id == property_id)
    if user_id:
        count_query = count_query.where(Booking.user_id == user_id)
    total = (await db.execute(count_query)).scalar() or 0

    # Calculate counts for different statuses
    # Upcoming: check_in_date > now and status is confirmed/pending
    upcoming_query = select(func.count(Booking.id.distinct()))
    if filter_agent_id is not None:
        from app.models.properties import Property
        from app.models.users import User
        upcoming_query = upcoming_query.outerjoin(User, Booking.user_id == User.id).outerjoin(Property, Booking.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        upcoming_query = upcoming_query.where(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))
    if property_id:
        upcoming_query = upcoming_query.where(Booking.property_id == property_id)
    if user_id:
        upcoming_query = upcoming_query.where(Booking.user_id == user_id)
    upcoming_query = upcoming_query.where(
        and_(
            Booking.check_in_date > now,
        Booking.booking_status.in_([BookingStatus.confirmed, BookingStatus.pending])
        )
    )
    upcoming = (await db.execute(upcoming_query)).scalar() or 0

    # Completed: check_out_date < now and status is confirmed/completed
    completed_query = select(func.count(Booking.id.distinct()))
    if filter_agent_id is not None:
        from app.models.properties import Property
        from app.models.users import User
        completed_query = completed_query.outerjoin(User, Booking.user_id == User.id).outerjoin(Property, Booking.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        completed_query = completed_query.where(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))
    if property_id:
        completed_query = completed_query.where(Booking.property_id == property_id)
    if user_id:
        completed_query = completed_query.where(Booking.user_id == user_id)
    completed_query = completed_query.where(
        and_(
            Booking.check_out_date < now,
            Booking.booking_status.in_([BookingStatus.confirmed, BookingStatus.completed])
        )
    )
    completed = (await db.execute(completed_query)).scalar() or 0

    # Cancelled: status is cancelled
    cancelled_query = select(func.count(Booking.id.distinct()))
    if filter_agent_id is not None:
        from app.models.properties import Property
        from app.models.users import User
        cancelled_query = cancelled_query.outerjoin(User, Booking.user_id == User.id).outerjoin(Property, Booking.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        cancelled_query = cancelled_query.where(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))
    if property_id:
        cancelled_query = cancelled_query.where(Booking.property_id == property_id)
    if user_id:
        cancelled_query = cancelled_query.where(Booking.user_id == user_id)
    cancelled_query = cancelled_query.where(Booking.booking_status == BookingStatus.cancelled)
    cancelled = (await db.execute(cancelled_query)).scalar() or 0

    return {
        "bookings": bookings,
        "total": total,
        "upcoming": upcoming,
        "completed": completed,
        "cancelled": cancelled,
    }
