from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc, asc
from datetime import datetime, timedelta
from app.models.booking import Booking, BookingStatus, PaymentStatus
from app.models.property import Property
from app.schemas.booking import BookingCreate, BookingUpdate, BookingPayment, BookingReview
import uuid

def generate_booking_reference():
    return f"BK{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"

def create_booking(db: Session, user_id: int, booking: BookingCreate):
    # Calculate nights
    nights = (booking.check_out_date - booking.check_in_date).days
    
    # Get property for pricing
    property_obj = db.query(Property).filter(Property.id == booking.property_id).first()
    if not property_obj:
        return None
    
    # Calculate pricing
    base_amount = property_obj.daily_rate * nights if property_obj.daily_rate else 0
    taxes_amount = base_amount * 0.12  # 12% GST
    service_charges = base_amount * 0.05  # 5% service charge
    total_amount = base_amount + taxes_amount + service_charges
    
    db_booking = Booking(
        user_id=user_id,
        property_id=booking.property_id,
        booking_reference=generate_booking_reference(),
        check_in_date=booking.check_in_date,
        check_out_date=booking.check_out_date,
        nights=nights,
        guests=booking.guests,
        primary_guest_name=booking.primary_guest_name,
        primary_guest_phone=booking.primary_guest_phone,
        primary_guest_email=booking.primary_guest_email,
        guest_details=booking.guest_details,
        special_requests=booking.special_requests,
        base_amount=base_amount,
        taxes_amount=taxes_amount,
        service_charges=service_charges,
        total_amount=total_amount,
        booking_status=BookingStatus.PENDING,
        payment_status=PaymentStatus.PENDING
    )
    
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)
    return db_booking

def get_booking(db: Session, booking_id: int):
    return db.query(Booking).filter(Booking.id == booking_id).first()

def get_user_bookings(db: Session, user_id: int):
    bookings = db.query(Booking).filter(Booking.user_id == user_id).order_by(
        desc(Booking.check_in_date)
    ).all()
    
    upcoming = [b for b in bookings if b.check_in_date > datetime.now() and b.booking_status not in [BookingStatus.CANCELLED]]
    completed = [b for b in bookings if b.booking_status == BookingStatus.COMPLETED]
    cancelled = [b for b in bookings if b.booking_status == BookingStatus.CANCELLED]
    
    return {
        "bookings": bookings,
        "total": len(bookings),
        "upcoming": len(upcoming),
        "completed": len(completed),
        "cancelled": len(cancelled)
    }

def get_user_upcoming_bookings(db: Session, user_id: int):
    return db.query(Booking).filter(
        and_(
            Booking.user_id == user_id,
            Booking.check_in_date > datetime.now(),
            Booking.booking_status != BookingStatus.CANCELLED
        )
    ).order_by(asc(Booking.check_in_date)).all()

def get_user_past_bookings(db: Session, user_id: int):
    return db.query(Booking).filter(
        and_(
            Booking.user_id == user_id,
            Booking.booking_status.in_([BookingStatus.COMPLETED, BookingStatus.CANCELLED])
        )
    ).order_by(desc(Booking.check_out_date)).all()

def update_booking(db: Session, booking_id: int, booking_update: BookingUpdate):
    db_booking = get_booking(db, booking_id)
    if not db_booking:
        return None
    
    update_data = booking_update.dict(exclude_unset=True)
    
    # Recalculate if dates or guests changed
    recalculate = False
    if 'check_in_date' in update_data or 'check_out_date' in update_data or 'guests' in update_data:
        recalculate = True
    
    for field, value in update_data.items():
        setattr(db_booking, field, value)
    
    if recalculate:
        nights = (db_booking.check_out_date - db_booking.check_in_date).days
        property_obj = db.query(Property).filter(Property.id == db_booking.property_id).first()
        
        if property_obj and property_obj.daily_rate:
            base_amount = property_obj.daily_rate * nights
            taxes_amount = base_amount * 0.12
            service_charges = base_amount * 0.05
            total_amount = base_amount + taxes_amount + service_charges
            
            db_booking.nights = nights
            db_booking.base_amount = base_amount
            db_booking.taxes_amount = taxes_amount
            db_booking.service_charges = service_charges
            db_booking.total_amount = total_amount
    
    db.commit()
    db.refresh(db_booking)
    return db_booking

def cancel_booking(db: Session, booking_id: int, reason: str):
    db_booking = get_booking(db, booking_id)
    if not db_booking:
        return False
    
    db_booking.booking_status = BookingStatus.CANCELLED
    db_booking.cancellation_date = datetime.now()
    db_booking.cancellation_reason = reason
    
    # Calculate refund based on cancellation policy
    days_until_checkin = (db_booking.check_in_date - datetime.now()).days
    if days_until_checkin >= 7:
        refund_percentage = 0.8  # 80% refund
    elif days_until_checkin >= 3:
        refund_percentage = 0.5  # 50% refund
    else:
        refund_percentage = 0.2  # 20% refund
    
    db_booking.refund_amount = db_booking.total_amount * refund_percentage
    db_booking.payment_status = PaymentStatus.REFUNDED
    
    db.commit()
    return True

def process_payment(db: Session, payment_data: BookingPayment):
    db_booking = get_booking(db, payment_data.booking_id)
    if not db_booking:
        return False
    
    db_booking.payment_method = payment_data.payment_method
    db_booking.transaction_id = payment_data.transaction_id
    db_booking.payment_date = datetime.now()
    db_booking.payment_status = PaymentStatus.PAID
    db_booking.booking_status = BookingStatus.CONFIRMED
    
    db.commit()
    return True

def add_review(db: Session, review_data: BookingReview):
    db_booking = get_booking(db, review_data.booking_id)
    if not db_booking:
        return False
    
    db_booking.guest_rating = review_data.guest_rating
    db_booking.guest_review = review_data.guest_review
    
    db.commit()
    return True

def check_availability(db: Session, property_id: int, check_in_date: str, check_out_date: str, guests: int):
    # Convert string dates to datetime
    check_in = datetime.strptime(check_in_date, '%Y-%m-%d')
    check_out = datetime.strptime(check_out_date, '%Y-%m-%d')
    
    # Check for overlapping bookings
    from sqlalchemy import or_
    overlapping_bookings = db.query(Booking).filter(
        and_(
            Booking.property_id == property_id,
            Booking.booking_status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
            or_(
                and_(Booking.check_in_date <= check_in, Booking.check_out_date > check_in),
                and_(Booking.check_in_date < check_out, Booking.check_out_date >= check_out),
                and_(Booking.check_in_date >= check_in, Booking.check_out_date <= check_out)
            )
        )
    ).all()
    
    # Check property capacity
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        return {"available": False, "reason": "Property not found"}
    
    if property_obj.max_occupancy and guests > property_obj.max_occupancy:
        return {"available": False, "reason": f"Property can accommodate maximum {property_obj.max_occupancy} guests"}
    
    if overlapping_bookings:
        return {"available": False, "reason": "Property is not available for selected dates"}
    
    return {"available": True, "message": "Property is available"}

def calculate_pricing(db: Session, property_id: int, check_in_date: datetime, check_out_date: datetime, guests: int):
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        return None
    
    nights = (check_out_date - check_in_date).days
    base_amount = property_obj.daily_rate * nights if property_obj.daily_rate else 0
    taxes_amount = base_amount * 0.12  # 12% GST
    service_charges = base_amount * 0.05  # 5% service charge
    total_amount = base_amount + taxes_amount + service_charges
    
    return {
        "property_id": property_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "guests": guests,
        "nights": nights,
        "base_amount": base_amount,
        "taxes_amount": taxes_amount,
        "service_charges": service_charges,
        "discount_amount": 0,
        "total_amount": total_amount
    }