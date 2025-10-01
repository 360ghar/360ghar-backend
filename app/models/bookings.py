
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, Float, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum
from typing import Optional
from datetime import datetime
from app.core.database import Base
from app.models.enums import BookingStatus, PaymentStatus

class Booking(Base):
    __tablename__ = "bookings"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    booking_reference: Mapped[str] = mapped_column(String, unique=True, index=True)
    check_in_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    check_out_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    nights: Mapped[int] = mapped_column(Integer, nullable=False)
    guests: Mapped[int] = mapped_column(Integer, nullable=False)
    base_amount: Mapped[float] = mapped_column(Float, nullable=False)
    taxes_amount: Mapped[float] = mapped_column(Float, nullable=False)
    service_charges: Mapped[float] = mapped_column(Float, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    booking_status: Mapped[BookingStatus] = mapped_column(SQLEnum(BookingStatus, name='booking_status'), nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus, name='payment_status'), nullable=False)
    primary_guest_name: Mapped[str] = mapped_column(String, nullable=False)
    primary_guest_phone: Mapped[str] = mapped_column(String, nullable=False)
    primary_guest_email: Mapped[str] = mapped_column(String, nullable=False)
    guest_details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    special_requests: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actual_check_in: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    actual_check_out: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    early_check_in: Mapped[bool] = mapped_column(Boolean, default=False)
    late_check_out: Mapped[bool] = mapped_column(Boolean, default=False)
    cancellation_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refund_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payment_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    guest_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guest_review: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    host_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    host_review: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)
    
    user: Mapped["User"] = relationship(back_populates="bookings")
    property: Mapped["Property"] = relationship(back_populates="bookings")
