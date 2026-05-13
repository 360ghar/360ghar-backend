from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import TenantStatus

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

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    application_fee_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    required_document_types: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    questions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

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

    id: Mapped[int] = mapped_column(primary_key=True)

    form_id: Mapped[int] = mapped_column(
        ForeignKey("rental_application_forms.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    status: Mapped[TenantStatus] = mapped_column(
        SQLEnum(TenantStatus, name="tenant_status"), default=TenantStatus.applicant
    )

    applicant_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applicant_full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    applicant_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    applicant_email: Mapped[str | None] = mapped_column(String, nullable=True)

    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    application_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    emergency_contacts: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    applicant_user: Mapped[User | None] = relationship(
        "User", foreign_keys=[applicant_user_id]
    )
    decided_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[decided_by_user_id]
    )

    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="rental_application",
        cascade="all, delete-orphan",
    )
