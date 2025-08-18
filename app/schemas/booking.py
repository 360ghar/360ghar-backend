from pydantic import BaseModel, EmailStr, validator
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.enums import BookingStatus, PaymentStatus

class BookingBase(BaseModel):
    property_id: int
    check_in_date: datetime
    check_out_date: datetime
    guests: int
    primary_guest_name: str
    primary_guest_phone: str
    primary_guest_email: EmailStr
    special_requests: Optional[str] = None

class BookingCreate(BookingBase):
    guest_details: Optional[Dict[str, Any]] = None
    
    @validator('check_out_date')
    def validate_dates(cls, v, values):
        if 'check_in_date' in values and v <= values['check_in_date']:
            raise ValueError('Check-out date must be after check-in date')
        return v

class BookingUpdate(BaseModel):
    check_in_date: Optional[datetime] = None
    check_out_date: Optional[datetime] = None
    guests: Optional[int] = None
    primary_guest_name: Optional[str] = None
    primary_guest_phone: Optional[str] = None
    primary_guest_email: Optional[EmailStr] = None
    special_requests: Optional[str] = None
    guest_details: Optional[Dict[str, Any]] = None

class BookingCancel(BaseModel):
    booking_id: int
    reason: str

class BookingPayment(BaseModel):
    booking_id: int
    payment_method: str
    transaction_id: str
    amount: float

class BookingReview(BaseModel):
    booking_id: int
    guest_rating: int  # 1-5 stars
    guest_review: Optional[str] = None
    
    @validator('guest_rating')
    def validate_rating(cls, v):
        if v < 1 or v > 5:
            raise ValueError('Rating must be between 1 and 5')
        return v

class Booking(BookingBase):
    id: int
    user_id: int
    booking_reference: str
    nights: int
    base_amount: float
    taxes_amount: float
    service_charges: float
    discount_amount: float
    total_amount: float
    booking_status: BookingStatus
    payment_status: PaymentStatus
    guest_details: Optional[Dict[str, Any]] = None
    internal_notes: Optional[str] = None
    actual_check_in: Optional[datetime] = None
    actual_check_out: Optional[datetime] = None
    early_check_in: bool
    late_check_out: bool
    cancellation_date: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    refund_amount: Optional[float] = None
    payment_method: Optional[str] = None
    transaction_id: Optional[str] = None
    payment_date: Optional[datetime] = None
    guest_rating: Optional[int] = None
    guest_review: Optional[str] = None
    host_rating: Optional[int] = None
    host_review: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class BookingList(BaseModel):
    bookings: list[Booking]
    total: int
    upcoming: int
    completed: int
    cancelled: int

class BookingAvailability(BaseModel):
    property_id: int
    check_in_date: datetime
    check_out_date: datetime
    guests: int

class BookingPricing(BaseModel):
    property_id: int
    check_in_date: datetime
    check_out_date: datetime
    guests: int
    nights: int
    base_amount: float
    taxes_amount: float
    service_charges: float
    discount_amount: float
    total_amount: float