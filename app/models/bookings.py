
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, db_enum
from app.models.enums import BookingStatus, PaymentStatus

if TYPE_CHECKING:
    from app.models.properties import Property
    from app.models.users import User


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("idx_bookings_property_id", "property_id"),
        Index(
            "uq_bookings_created_by_idempotency_key",
            "created_by_user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    property_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("properties.id", ondelete="CASCADE"))
    booking_reference: Mapped[str] = mapped_column(String, unique=True, index=True)
    check_in_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nights: Mapped[int] = mapped_column(Integer, nullable=False)
    guests: Mapped[int] = mapped_column(Integer, nullable=False)
    base_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    taxes_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    service_charges: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    booking_status: Mapped[BookingStatus] = mapped_column(db_enum(BookingStatus, 'booking_status'), nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(db_enum(PaymentStatus, 'payment_status'), nullable=False)
    primary_guest_name: Mapped[str] = mapped_column(String, nullable=False)
    primary_guest_phone: Mapped[str] = mapped_column(String, nullable=False)
    primary_guest_email: Mapped[str] = mapped_column(String, nullable=False)
    guest_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    early_check_in: Mapped[bool] = mapped_column(Boolean, default=False)
    late_check_out: Mapped[bool] = mapped_column(Boolean, default=False)
    cancellation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # The caller who created the booking. Not a foreign key: a second FK to users would make
    # the Booking.user relationship ambiguous.
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    guest_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guest_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    user: Mapped[User] = relationship(back_populates="bookings")
    property: Mapped[Property] = relationship(back_populates="bookings")
