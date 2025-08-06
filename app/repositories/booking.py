from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, asc, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
import uuid
from app.repositories.base import BaseRepository
from app.models.booking import Booking, BookingStatus, PaymentStatus
from app.models.property import Property
from app.schemas.booking import BookingCreate, BookingUpdate, BookingPayment, BookingReview

class BookingRepository(BaseRepository[Booking]):
    """Repository for booking-related database operations"""
    
    def __init__(self, session: AsyncSession):
        super().__init__(Booking, session)
    
    def generate_booking_reference(self) -> str:
        """Generate unique booking reference"""
        return f"BK{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"
    
    async def create_booking(self, user_id: int, booking: BookingCreate) -> Optional[Booking]:
        """Create a new booking with pricing calculations"""
        # Calculate nights
        nights = (booking.check_out_date - booking.check_in_date).days
        
        # Get property for pricing
        property_result = await self.session.execute(
            select(Property).where(Property.id == booking.property_id)
        )
        property_obj = property_result.scalar_one_or_none()
        if not property_obj:
            return None
        
        # Calculate pricing
        base_amount = property_obj.daily_rate * nights if property_obj.daily_rate else 0
        taxes_amount = base_amount * 0.12  # 12% GST
        service_charges = base_amount * 0.05  # 5% service charge
        total_amount = base_amount + taxes_amount + service_charges
        
        new_booking = Booking(
            user_id=user_id,
            property_id=booking.property_id,
            booking_reference=self.generate_booking_reference(),
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
        
        self.session.add(new_booking)
        await self.session.flush()
        await self.session.refresh(new_booking)
        return new_booking
    
    async def get_with_property(self, booking_id: int) -> Optional[Booking]:
        """Get booking with property details loaded"""
        return await self.get(
            booking_id,
            load_options=[selectinload(Booking.property)]
        )
    
    async def get_user_bookings(self, user_id: int) -> Dict[str, Any]:
        """Get all bookings for a user with statistics"""
        bookings_result = await self.session.execute(
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(desc(Booking.check_in_date))
        )
        bookings = bookings_result.scalars().all()
        
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
    
    async def get_user_upcoming_bookings(self, user_id: int) -> List[Booking]:
        """Get upcoming bookings for a user"""
        result = await self.session.execute(
            select(Booking).where(
                and_(
                    Booking.user_id == user_id,
                    Booking.check_in_date > datetime.now(),
                    Booking.booking_status != BookingStatus.CANCELLED
                )
            ).order_by(asc(Booking.check_in_date))
        )
        return result.scalars().all()
    
    async def get_user_past_bookings(self, user_id: int) -> List[Booking]:
        """Get past bookings for a user"""
        result = await self.session.execute(
            select(Booking).where(
                and_(
                    Booking.user_id == user_id,
                    Booking.booking_status.in_([BookingStatus.COMPLETED, BookingStatus.CANCELLED])
                )
            ).order_by(desc(Booking.check_out_date))
        )
        return result.scalars().all()
    
    async def update_booking(self, booking_id: int, booking_update: BookingUpdate) -> Optional[Booking]:
        """Update booking with automatic recalculation if needed"""
        booking = await self.get(booking_id)
        
        update_data = booking_update.model_dump(exclude_unset=True)
        
        # Recalculate if dates or guests changed
        recalculate = False
        if 'check_in_date' in update_data or 'check_out_date' in update_data or 'guests' in update_data:
            recalculate = True
        
        for field, value in update_data.items():
            if hasattr(booking, field):
                setattr(booking, field, value)
        
        if recalculate:
            nights = (booking.check_out_date - booking.check_in_date).days
            property_result = await self.session.execute(
                select(Property).where(Property.id == booking.property_id)
            )
            property_obj = property_result.scalar_one_or_none()
            
            if property_obj and property_obj.daily_rate:
                base_amount = property_obj.daily_rate * nights
                taxes_amount = base_amount * 0.12
                service_charges = base_amount * 0.05
                total_amount = base_amount + taxes_amount + service_charges
                
                booking.nights = nights
                booking.base_amount = base_amount
                booking.taxes_amount = taxes_amount
                booking.service_charges = service_charges
                booking.total_amount = total_amount
        
        await self.session.flush()
        await self.session.refresh(booking)
        return booking
    
    async def cancel_booking(self, booking_id: int, reason: str) -> bool:
        """Cancel booking with refund calculation"""
        booking = await self.get(booking_id)
        
        booking.booking_status = BookingStatus.CANCELLED
        booking.cancellation_date = datetime.now()
        booking.cancellation_reason = reason
        
        # Calculate refund based on cancellation policy
        days_until_checkin = (booking.check_in_date - datetime.now()).days
        if days_until_checkin >= 7:
            refund_percentage = 0.8  # 80% refund
        elif days_until_checkin >= 3:
            refund_percentage = 0.5  # 50% refund
        else:
            refund_percentage = 0.2  # 20% refund
        
        booking.refund_amount = booking.total_amount * refund_percentage
        booking.payment_status = PaymentStatus.REFUNDED
        
        await self.session.flush()
        return True
    
    async def process_payment(self, payment_data: BookingPayment) -> bool:
        """Process payment for booking"""
        booking = await self.get(payment_data.booking_id)
        
        booking.payment_method = payment_data.payment_method
        booking.transaction_id = payment_data.transaction_id
        booking.payment_date = datetime.now()
        booking.payment_status = PaymentStatus.PAID
        booking.booking_status = BookingStatus.CONFIRMED
        
        await self.session.flush()
        return True
    
    async def add_review(self, review_data: BookingReview) -> bool:
        """Add review to booking"""
        booking = await self.get(review_data.booking_id)
        
        booking.guest_rating = review_data.guest_rating
        booking.guest_review = review_data.guest_review
        
        await self.session.flush()
        return True
    
    async def check_availability(
        self,
        property_id: int,
        check_in_date: str,
        check_out_date: str,
        guests: int
    ) -> Dict[str, Any]:
        """Check if property is available for given dates and guest count"""
        # Convert string dates to datetime
        check_in = datetime.strptime(check_in_date, '%Y-%m-%d')
        check_out = datetime.strptime(check_out_date, '%Y-%m-%d')
        
        # Check for overlapping bookings
        overlapping_result = await self.session.execute(
            select(Booking).where(
                and_(
                    Booking.property_id == property_id,
                    Booking.booking_status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
                    or_(
                        and_(Booking.check_in_date <= check_in, Booking.check_out_date > check_in),
                        and_(Booking.check_in_date < check_out, Booking.check_out_date >= check_out),
                        and_(Booking.check_in_date >= check_in, Booking.check_out_date <= check_out)
                    )
                )
            )
        )
        overlapping_bookings = overlapping_result.scalars().all()
        
        # Check property capacity
        property_result = await self.session.execute(
            select(Property).where(Property.id == property_id)
        )
        property_obj = property_result.scalar_one_or_none()
        if not property_obj:
            return {"available": False, "reason": "Property not found"}
        
        if property_obj.max_occupancy and guests > property_obj.max_occupancy:
            return {
                "available": False,
                "reason": f"Property can accommodate maximum {property_obj.max_occupancy} guests"
            }
        
        if overlapping_bookings:
            return {"available": False, "reason": "Property is not available for selected dates"}
        
        return {"available": True, "message": "Property is available"}
    
    async def calculate_pricing(
        self,
        property_id: int,
        check_in_date: datetime,
        check_out_date: datetime,
        guests: int
    ) -> Optional[Dict[str, Any]]:
        """Calculate pricing for a booking"""
        property_result = await self.session.execute(
            select(Property).where(Property.id == property_id)
        )
        property_obj = property_result.scalar_one_or_none()
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
    
    async def get_property_bookings(
        self,
        property_id: int,
        status_filter: Optional[List[BookingStatus]] = None
    ) -> List[Booking]:
        """Get all bookings for a property"""
        query = select(Booking).where(Booking.property_id == property_id)
        
        if status_filter:
            query = query.where(Booking.booking_status.in_(status_filter))
        
        query = query.order_by(desc(Booking.check_in_date))
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def check_in_booking(self, booking_id: int) -> bool:
        """Mark booking as checked in"""
        booking = await self.get(booking_id)
        booking.booking_status = BookingStatus.CHECKED_IN
        booking.actual_check_in = datetime.now()
        await self.session.flush()
        return True
    
    async def check_out_booking(self, booking_id: int) -> bool:
        """Mark booking as checked out and completed"""
        booking = await self.get(booking_id)
        booking.booking_status = BookingStatus.COMPLETED
        booking.actual_check_out = datetime.now()
        await self.session.flush()
        return True