from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import BookingStatus, PaymentStatus


class BookingBase(BaseModel):
    property_id: int = Field(
        ...,
        description="ID of the property to book",
        examples=[1],
    )
    check_in_date: datetime = Field(
        ...,
        description="Check-in date and time (ISO 8601)",
        examples=["2026-07-01T12:00:00Z"],
    )
    check_out_date: datetime = Field(
        ...,
        description="Check-out date and time (must be after check-in)",
        examples=["2026-07-05T11:00:00Z"],
    )
    guests: int = Field(
        ...,
        description="Number of guests for the booking",
        examples=[2],
    )
    primary_guest_name: str = Field(
        ...,
        description="Full name of the primary guest",
        examples=["Rahul Sharma"],
    )
    primary_guest_phone: str = Field(
        ...,
        description="Phone number of the primary guest (E.164)",
        examples=["+919876543210"],
    )
    primary_guest_email: EmailStr = Field(
        ...,
        description="Email of the primary guest",
        examples=["rahul@example.com"],
    )
    special_requests: str | None = None

class BookingCreate(BookingBase):
    guest_details: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.check_out_date <= self.check_in_date:
            raise ValueError('Check-out date must be after check-in date')
        return self

class BookingUpdate(BaseModel):
    booking_status: str | None = None
    check_in_date: datetime | None = None
    check_out_date: datetime | None = None
    guests: int | None = None
    primary_guest_name: str | None = None
    primary_guest_phone: str | None = None
    primary_guest_email: EmailStr | None = None
    special_requests: str | None = None
    guest_details: dict[str, Any] | None = None
    notes: str | None = None

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
    guest_review: str | None = None

    @field_validator("guest_rating")
    @classmethod
    def validate_rating(cls, v: int) -> int:
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
    guest_details: dict[str, Any] | None = None
    internal_notes: str | None = None
    actual_check_in: datetime | None = None
    actual_check_out: datetime | None = None
    early_check_in: bool
    late_check_out: bool
    cancellation_date: datetime | None = None
    cancellation_reason: str | None = None
    refund_amount: float | None = None
    payment_method: str | None = None
    transaction_id: str | None = None
    payment_date: datetime | None = None
    guest_rating: int | None = None
    guest_review: str | None = None
    host_rating: int | None = None
    host_review: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

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
