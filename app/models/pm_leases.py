from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import LeaseStatus

if TYPE_CHECKING:
    from app.models.pm_documents import Document
    from app.models.pm_finance import RentCharge
    from app.models.pm_inspections import InspectionChecklist
    from app.models.pm_maintenance import MaintenanceRequest
    from app.models.properties import Property
    from app.models.users import User


class Lease(Base):
    __tablename__ = "leases"
    __table_args__ = (
        Index("idx_leases_owner_id", "owner_id"),
        Index("idx_leases_property_id", "property_id"),
        Index("idx_leases_tenant_user_id", "tenant_user_id"),
        Index("idx_leases_status", "status"),
        Index("idx_leases_end_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Tenant is a platform user. This can be nullable for pre-account tenants.
    tenant_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tenant_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_email: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[LeaseStatus] = mapped_column(
        SQLEnum(LeaseStatus, name="lease_status"),
        default=LeaseStatus.draft,
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    monthly_rent: Mapped[float] = mapped_column(Float, nullable=False)
    security_deposit: Mapped[float] = mapped_column(Float, nullable=False)

    late_fee_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    late_fee_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=5)
    payment_due_day: Mapped[int] = mapped_column(Integer, default=1)

    lease_terms: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    special_clauses: Mapped[str | None] = mapped_column(Text, nullable=True)

    signed_by_tenant_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by_owner_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    lease_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    property: Mapped[Property] = relationship(
        "Property",
        back_populates="leases",
        foreign_keys=[property_id],
    )
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    tenant_user: Mapped[User | None] = relationship("User", foreign_keys=[tenant_user_id])
    lease_document: Mapped[Document | None] = relationship("Document", foreign_keys=[lease_document_id])

    rent_charges: Mapped[list[RentCharge]] = relationship(
        "RentCharge", back_populates="lease", cascade="all, delete-orphan"
    )
    maintenance_requests: Mapped[list[MaintenanceRequest]] = relationship(
        "MaintenanceRequest", back_populates="lease"
    )
    inspection_checklists: Mapped[list[InspectionChecklist]] = relationship(
        "InspectionChecklist", back_populates="lease"
    )
