
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import BookingStatus, PaymentStatus

if TYPE_CHECKING:
    from app.models.properties import Property
    from app.models.users import User


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("idx_bookings_property_id", "property_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    booking_reference: Mapped[str] = mapped_column(String, unique=True, index=True)
    check_in_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nights: Mapped[int] = mapped_column(Integer, nullable=False)
    guests: Mapped[int] = mapped_column(Integer, nullable=False)
    base_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    taxes_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    service_charges: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    booking_status: Mapped[BookingStatus] = mapped_column(SQLEnum(BookingStatus, name='booking_status'), nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus, name='payment_status'), nullable=False)
    primary_guest_name: Mapped[str] = mapped_column(String, nullable=False)
    primary_guest_phone: Mapped[str] = mapped_column(String, nullable=False)
    primary_guest_email: Mapped[str] = mapped_column(String, nullable=False)
    guest_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    early_check_in: Mapped[bool] = mapped_column(Boolean, default=False)
    late_check_out: Mapped[bool] = mapped_column(Boolean, default=False)
    cancellation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    guest_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guest_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    user: Mapped[User] = relationship(back_populates="bookings")
    property: Mapped[Property] = relationship(back_populates="bookings")
