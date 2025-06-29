from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Boolean, Text, JSON, Enum
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
import enum

class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    REFUNDED = "refunded"
    FAILED = "failed"

class Booking(BaseModel):
    __tablename__ = "bookings"
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    
    # Booking details
    booking_reference = Column(String, unique=True, nullable=False)
    check_in_date = Column(DateTime, nullable=False)
    check_out_date = Column(DateTime, nullable=False)
    nights = Column(Integer, nullable=False)
    guests = Column(Integer, nullable=False)
    
    # Pricing
    base_amount = Column(Float, nullable=False)
    taxes_amount = Column(Float, default=0)
    service_charges = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    total_amount = Column(Float, nullable=False)
    
    # Status
    booking_status = Column(Enum(BookingStatus), default=BookingStatus.PENDING)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    
    # Guest information
    primary_guest_name = Column(String, nullable=False)
    primary_guest_phone = Column(String, nullable=False)
    primary_guest_email = Column(String, nullable=False)
    guest_details = Column(JSON)  # Additional guest information
    
    # Special requests and notes
    special_requests = Column(Text)
    internal_notes = Column(Text)  # Staff notes
    
    # Check-in/out details
    actual_check_in = Column(DateTime)
    actual_check_out = Column(DateTime)
    early_check_in = Column(Boolean, default=False)
    late_check_out = Column(Boolean, default=False)
    
    # Cancellation
    cancellation_date = Column(DateTime)
    cancellation_reason = Column(Text)
    refund_amount = Column(Float)
    
    # Payment details
    payment_method = Column(String)
    transaction_id = Column(String)
    payment_date = Column(DateTime)
    
    # Reviews and ratings
    guest_rating = Column(Integer)  # 1-5 stars
    guest_review = Column(Text)
    host_rating = Column(Integer)  # Host rating of guest
    host_review = Column(Text)
    
    # Relationships
    user = relationship("User", back_populates="bookings")
    property = relationship("Property", back_populates="bookings")