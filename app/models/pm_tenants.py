from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, db_enum
from app.models.enums import RentalApplicationStatus

if TYPE_CHECKING:
    from app.models.pm_documents import Document
    from app.models.properties import Property
    from app.models.users import User


class RentalApplicationForm(Base):
    __tablename__ = "rental_application_forms"
    __table_args__ = (
        Index("idx_rental_application_forms_owner_id", "owner_id"),
        Index("idx_rental_application_forms_property_id", "property_id"),
        Index("idx_rental_application_forms_slug", "slug", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    property_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    application_fee_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    required_document_types: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    questions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    property: Mapped[Property | None] = relationship("Property")
    applications: Mapped[list[RentalApplication]] = relationship(
        "RentalApplication", back_populates="form", cascade="all, delete-orphan"
    )


class RentalApplication(Base):
    __tablename__ = "rental_applications"
    __table_args__ = (
        Index("idx_rental_applications_owner_id", "owner_id"),
        Index("idx_rental_applications_property_id", "property_id"),
        Index("idx_rental_applications_form_id", "form_id"),
        Index("idx_rental_applications_status", "status"),
        Index("idx_rental_applications_submitted_at", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    form_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rental_application_forms.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[RentalApplicationStatus] = mapped_column(
        db_enum(RentalApplicationStatus, "rental_application_status"),
        default=RentalApplicationStatus.applicant,
    )

    applicant_full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    applicant_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    applicant_email: Mapped[str | None] = mapped_column(String, nullable=True)

    answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    application_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    emergency_contacts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    form: Mapped[RentalApplicationForm] = relationship(
        "RentalApplicationForm", back_populates="applications"
    )
    property: Mapped[Property] = relationship("Property")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    decided_by: Mapped[User | None] = relationship("User", foreign_keys=[decided_by_user_id])

    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="rental_application",
        cascade="all, delete-orphan",
    )
