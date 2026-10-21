from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, db_enum
from app.models.enums import ExpenseCategory, PaymentMethod, RentChargeStatus, RentPaymentStatus

if TYPE_CHECKING:
    from app.models.pm_documents import Document
    from app.models.pm_leases import Lease
    from app.models.properties import Property
    from app.models.users import User


class RentCharge(Base):
    __tablename__ = "rent_charges"
    __table_args__ = (
        UniqueConstraint("lease_id", "billing_month", name="uq_rent_charges_lease_month"),
        Index("idx_rent_charges_owner_id", "owner_id"),
        Index("idx_rent_charges_property_id", "property_id"),
        Index("idx_rent_charges_tenant_user_id", "tenant_user_id"),
        Index("idx_rent_charges_due_date", "due_date"),
        Index("idx_rent_charges_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    lease_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    billing_month: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    late_fee_assessed: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    status: Mapped[RentChargeStatus] = mapped_column(
        db_enum(RentChargeStatus, "rent_charge_status"),
        default=RentChargeStatus.pending,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    lease: Mapped[Lease] = relationship("Lease", back_populates="rent_charges")
    property: Mapped[Property] = relationship("Property", back_populates="rent_charges")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    tenant_user: Mapped[User | None] = relationship("User", foreign_keys=[tenant_user_id])

    payments: Mapped[list[RentPayment]] = relationship(
        "RentPayment", back_populates="charge", cascade="all, delete-orphan"
    )


class RentPayment(Base):
    __tablename__ = "rent_payments"
    __table_args__ = (
        Index("idx_rent_payments_charge_id", "charge_id"),
        Index("idx_rent_payments_owner_id", "owner_id"),
        Index("idx_rent_payments_property_id", "property_id"),
        Index("idx_rent_payments_lease_id", "lease_id"),
        Index("idx_rent_payments_paid_at", "paid_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    charge_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False
    )
    lease_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[PaymentMethod | None] = mapped_column(
        db_enum(PaymentMethod, "rent_payment_method"), nullable=True
    )
    status: Mapped[RentPaymentStatus] = mapped_column(
        db_enum(RentPaymentStatus, "rent_payment_status"),
        default=RentPaymentStatus.settled,
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    receipt_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    charge: Mapped[RentCharge] = relationship("RentCharge", back_populates="payments")
    lease: Mapped[Lease] = relationship("Lease")
    property: Mapped[Property] = relationship("Property")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    tenant_user: Mapped[User | None] = relationship("User", foreign_keys=[tenant_user_id])
    receipt_document: Mapped[Document | None] = relationship(
        "Document", foreign_keys=[receipt_document_id]
    )


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("idx_expenses_owner_id", "owner_id"),
        Index("idx_expenses_property_id", "property_id"),
        Index("idx_expenses_expense_date", "expense_date"),
        Index("idx_expenses_category", "category"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    property_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[ExpenseCategory] = mapped_column(
        db_enum(ExpenseCategory, "expense_category"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    receipt_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    property: Mapped[Property] = relationship("Property", back_populates="expenses")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    receipt_document: Mapped[Document | None] = relationship(
        "Document", foreign_keys=[receipt_document_id]
    )
