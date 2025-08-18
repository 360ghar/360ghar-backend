from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta
from app.models.models import Booking, Property
from app.schemas.booking import BookingCreate, BookingUpdate, BookingPayment, BookingReview
from typing import Optional
import uuid

async def create_booking(db: AsyncSession, user_id: int, booking: BookingCreate):
    """Create a new booking"""
    booking_data = booking.model_dump()
    booking_data["user_id"] = user_id
    booking_data["booking_reference"] = f"BK{uuid.uuid4().hex[:8].upper()}"
    
    # Calculate nights
    check_in = booking_data["check_in_date"]
    check_out = booking_data["check_out_date"]
    nights = (check_out - check_in).days
    booking_data["nights"] = nights
    
    db_booking = Booking(**booking_data)
    db.add(db_booking)
    await db.flush()
    await db.refresh(db_booking)
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
    return {"bookings": bookings, "total": len(bookings)}

async def get_user_upcoming_bookings(db: AsyncSession, user_id: int):
    """Get upcoming bookings for a user"""
    now = datetime.utcnow()
    stmt = select(Booking).where(
        Booking.user_id == user_id,
        Booking.check_in_date > now,
        Booking.booking_status.in_(["confirmed", "pending"])
    ).order_by(Booking.check_in_date)
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    return {"bookings": bookings, "total": len(bookings)}

async def get_user_past_bookings(db: AsyncSession, user_id: int):
    """Get past bookings for a user"""
    now = datetime.utcnow()
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
        booking.booking_status = "cancelled"
        booking.cancellation_date = datetime.utcnow()
        booking.cancellation_reason = reason
        await db.flush()
        return True
    
    return False

async def process_payment(db: AsyncSession, payment_data: BookingPayment):
    """Process payment for a booking"""
    stmt = select(Booking).where(Booking.id == payment_data.booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    
    if booking:
        booking.payment_status = "paid"
        booking.payment_method = payment_data.payment_method
        booking.transaction_id = payment_data.transaction_id
        booking.payment_date = datetime.utcnow()
        booking.booking_status = "confirmed"
        await db.flush()
        return True
    
    return False

async def add_review(db: AsyncSession, review_data: BookingReview):
    """Add a review to a booking"""
    stmt = select(Booking).where(Booking.id == review_data.booking_id)
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    
    if booking:
        booking.guest_rating = review_data.rating
        booking.guest_review = review_data.review
        await db.flush()
        return True
    
    return False

async def check_availability(db: AsyncSession, property_id: int, check_in_date: str, check_out_date: str, guests: int):
    """Check if property is available for booking"""
    check_in = datetime.fromisoformat(check_in_date)
    check_out = datetime.fromisoformat(check_out_date)
    
    # Check for overlapping bookings
    stmt = select(Booking).where(
        and_(
            Booking.property_id == property_id,
            Booking.booking_status.in_(["confirmed", "checked_in"]),
            # Check for date overlap
            Booking.check_in_date < check_out,
            Booking.check_out_date > check_in
        )
    )
    result = await db.execute(stmt)
    overlapping_bookings = result.scalars().all()
    
    # Get property max occupancy
    stmt = select(Property).where(Property.id == property_id)
    result = await db.execute(stmt)
    property_obj = result.scalar_one_or_none()
    
    if not property_obj:
        return {"available": False, "reason": "Property not found"}
    
    if overlapping_bookings:
        return {"available": False, "reason": "Property already booked for these dates"}
    
    if property_obj.max_occupancy and guests > property_obj.max_occupancy:
        return {"available": False, "reason": f"Property can accommodate maximum {property_obj.max_occupancy} guests"}
    
    return {"available": True, "max_occupancy": property_obj.max_occupancy}

async def calculate_pricing(db: AsyncSession, property_id: int, check_in_date: datetime, check_out_date: datetime, guests: int):
    """Calculate pricing for a booking"""
    stmt = select(Property).where(Property.id == property_id)
    result = await db.execute(stmt)
    property_obj = result.scalar_one_or_none()
    
    if not property_obj:
        return {"error": "Property not found"}
    
    nights = (check_out_date - check_in_date).days
    if nights <= 0:
        return {"error": "Invalid date range"}
    
    base_price = float(property_obj.daily_rate) if property_obj.daily_rate else 0.0
    total_base = base_price * nights
    
    # Calculate taxes and fees (example: 18% GST + 5% service charge)
    taxes = total_base * 0.18
    service_charges = total_base * 0.05
    
    total_amount = total_base + taxes + service_charges
    
    return {
        "property_id": property_id,
        "nights": nights,
        "base_amount": total_base,
        "taxes_amount": taxes,
        "service_charges": service_charges,
        "total_amount": total_amount,
        "breakdown": {
            "base_rate_per_night": base_price,
            "total_nights": nights,
            "subtotal": total_base,
            "gst_18_percent": taxes,
            "service_charge_5_percent": service_charges,
            "final_total": total_amount
        }
    }