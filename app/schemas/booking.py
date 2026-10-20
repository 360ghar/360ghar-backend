from __future__ import annotations

from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.enums import BookingStatus, PaymentStatus
from app.schemas.base import Money, NotNullable, PatchModel, PublicUserRef, UtcDateTime, WriteModel


class BookingBase(BaseModel):
    property_id: int = Field(
        ...,
        description="ID of the property to book",
        examples=[1],
    )
    check_in_date: UtcDateTime = Field(
        ...,
        description="Check-in date and time (ISO 8601)",
        examples=["2026-07-01T12:00:00Z"],
    )
    check_out_date: UtcDateTime = Field(
        ...,
        description="Check-out date and time (must be after check-in)",
        examples=["2026-07-05T11:00:00Z"],
    )
    guests: int = Field(
        ...,
        gt=0,
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


class BookingCreate(WriteModel, BookingBase):
    guest_details: dict[str, Any] | None = None
    user_id: int | None = Field(
        default=None,
        description="Guest (owner) of the booking. Admins and agents may set it. Other callers always own the booking.",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> BookingCreate:
        if self.check_out_date <= self.check_in_date:
            raise ValueError("Check-out date must be after check-in date")
        return self


class BookingUpdate(PatchModel):
    """Booking edit. Guests edit their own fields. Only admins and agents may set internal_notes."""

    check_in_date: Annotated[UtcDateTime | None, NotNullable] = None
    check_out_date: Annotated[UtcDateTime | None, NotNullable] = None
    guests: Annotated[int | None, NotNullable] = None
    primary_guest_name: Annotated[str | None, NotNullable] = None
    primary_guest_phone: Annotated[str | None, NotNullable] = None
    primary_guest_email: Annotated[EmailStr | None, NotNullable] = None
    special_requests: str | None = None
    guest_details: dict[str, Any] | None = None
    internal_notes: str | None = Field(
        default=None,
        description="Staff only. Sending it as a guest returns 403.",
    )

    @field_validator("guests")
    @classmethod
    def guests_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Input should be greater than 0")
        return value


class BookingCancel(WriteModel):
    booking_id: int
    # Whitespace is stripped before the length check, so "   " is rejected.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class BookingPayment(WriteModel):
    booking_id: int
    payment_method: str
    transaction_id: str
    amount: Money


class BookingReview(WriteModel):
    booking_id: int
    guest_rating: int  # 1-5 stars
    guest_review: str | None = None

    @field_validator("guest_rating")
    @classmethod
    def validate_rating(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Rating must be between 1 and 5")
        return v


class BookingPropertySummary(BaseModel):
    """The property a booking is for: enough to show a booking card."""

    id: int
    title: str
    city: str | None = None
    country: str | None = None
    cover_image_url: str | None = None


class Booking(BaseModel):
    """Booking as the guest sees it. Staff-only fields are in BookingStaff."""

    id: int
    user_id: int
    property_id: int
    booking_reference: str
    check_in_date: UtcDateTime
    check_out_date: UtcDateTime
    nights: int
    guests: int
    base_amount: Money
    taxes_amount: Money
    service_charges: Money
    discount_amount: Money
    total_amount: Money
    booking_status: BookingStatus
    payment_status: PaymentStatus
    primary_guest_name: str
    primary_guest_phone: str
    primary_guest_email: str
    special_requests: str | None = None
    guest_details: dict[str, Any] | None = None
    actual_check_in: UtcDateTime | None = None
    actual_check_out: UtcDateTime | None = None
    early_check_in: bool
    late_check_out: bool
    cancellation_date: UtcDateTime | None = None
    cancellation_reason: str | None = None
    refund_amount: Money | None = None
    payment_method: str | None = None
    transaction_id: str | None = None
    payment_date: UtcDateTime | None = None
    guest_rating: int | None = None
    guest_review: str | None = None
    property: BookingPropertySummary | None = None
    guest: PublicUserRef | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)


class BookingStaff(Booking):
    """Booking as admins and agents see it. Adds internal notes."""

    internal_notes: str | None = None


class BookingAvailability(WriteModel):
    property_id: int = Field(..., gt=0)
    check_in_date: UtcDateTime
    check_out_date: UtcDateTime
    guests: int = Field(..., gt=0)

    @model_validator(mode="after")
    def validate_dates(self) -> BookingAvailability:
        if self.check_out_date <= self.check_in_date:
            raise ValueError("Check-out date must be after check-in date")
        return self


class BookingOccupancyCheck(WriteModel):
    """No dates: overlapping bookings are allowed, so only the guest count is checked."""

    property_id: int = Field(..., gt=0)
    guests: int = Field(..., gt=0)


class BookingOccupancyResult(BaseModel):
    occupancy_ok: bool
    reason: str | None = None
    max_occupancy: int | None = None


class BookingPricing(BaseModel):
    property_id: int
    check_in_date: UtcDateTime
    check_out_date: UtcDateTime
    guests: int
    nights: int
    base_amount: Money
    taxes_amount: Money
    service_charges: Money
    discount_amount: Money
    total_amount: Money
