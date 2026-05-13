from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import ExpenseCategory, RentChargeStatus

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

    id: Mapped[int] = mapped_column(primary_key=True)

    lease_id: Mapped[int] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    billing_month: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    amount_due: Mapped[float] = mapped_column(Float, nullable=False)
    late_fee_assessed: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[RentChargeStatus] = mapped_column(
        SQLEnum(RentChargeStatus, name="rent_charge_status"),
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

    id: Mapped[int] = mapped_column(primary_key=True)

    charge_id: Mapped[int] = mapped_column(
        ForeignKey("rent_charges.id", ondelete="CASCADE"), nullable=False
    )
    lease_id: Mapped[int] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_paid: Mapped[float] = mapped_column(Float, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String, nullable=True)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    receipt_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
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
    receipt_document: Mapped[Document | None] = relationship("Document", foreign_keys=[receipt_document_id])


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("idx_expenses_owner_id", "owner_id"),
        Index("idx_expenses_property_id", "property_id"),
        Index("idx_expenses_expense_date", "expense_date"),
        Index("idx_expenses_category", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    category: Mapped[ExpenseCategory] = mapped_column(
        SQLEnum(ExpenseCategory, name="expense_category"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    receipt_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    property: Mapped[Property] = relationship("Property", back_populates="expenses")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    receipt_document: Mapped[Document | None] = relationship("Document", foreign_keys=[receipt_document_id])
