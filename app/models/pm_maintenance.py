from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import (
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    WorkOrderStatus,
)

if TYPE_CHECKING:
    from app.models.agents import Agent
    from app.models.pm_documents import Document
    from app.models.pm_leases import Lease
    from app.models.properties import Property
    from app.models.users import User


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"
    __table_args__ = (
        Index("idx_maintenance_requests_owner_id", "owner_id"),
        Index("idx_maintenance_requests_property_id", "property_id"),
        Index("idx_maintenance_requests_lease_id", "lease_id"),
        Index("idx_maintenance_requests_tenant_user_id", "tenant_user_id"),
        Index("idx_maintenance_requests_request_status", "request_status"),
        Index("idx_maintenance_requests_work_order_status", "work_order_status"),
        Index("idx_maintenance_requests_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    lease_id: Mapped[int | None] = mapped_column(
        ForeignKey("leases.id", ondelete="SET NULL"), nullable=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    category: Mapped[MaintenanceCategory] = mapped_column(
        SQLEnum(MaintenanceCategory, name="maintenance_category"), nullable=False
    )
    urgency: Mapped[MaintenanceUrgency] = mapped_column(
        SQLEnum(MaintenanceUrgency, name="maintenance_urgency"), nullable=False
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_contact_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Request lifecycle
    request_status: Mapped[MaintenanceRequestStatus] = mapped_column(
        SQLEnum(MaintenanceRequestStatus, name="maintenance_request_status"),
        default=MaintenanceRequestStatus.open,
        nullable=False,
    )

    # Work order lifecycle (no vendors; RM/owner handles)
    assigned_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    work_order_status: Mapped[WorkOrderStatus | None] = mapped_column(
        SQLEnum(WorkOrderStatus, name="work_order_status"), nullable=True
    )
    priority: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    property: Mapped[Property] = relationship(
        "Property", back_populates="maintenance_requests"
    )
    lease: Mapped[Lease | None] = relationship(
        "Lease", back_populates="maintenance_requests"
    )
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    tenant_user: Mapped[User | None] = relationship("User", foreign_keys=[tenant_user_id])
    assigned_agent: Mapped[Agent | None] = relationship("Agent", foreign_keys=[assigned_agent_id])

    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="maintenance_request",
        cascade="all, delete-orphan",
    )

