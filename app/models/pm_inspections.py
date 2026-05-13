from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import InspectionType

if TYPE_CHECKING:
    from app.models.pm_documents import Document
    from app.models.pm_leases import Lease
    from app.models.properties import Property
    from app.models.users import User


class InspectionChecklist(Base):
    __tablename__ = "inspection_checklists"
    __table_args__ = (
        Index("idx_inspection_checklists_owner_id", "owner_id"),
        Index("idx_inspection_checklists_property_id", "property_id"),
        Index("idx_inspection_checklists_lease_id", "lease_id"),
        Index("idx_inspection_checklists_conducted_at", "conducted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    lease_id: Mapped[int] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    inspection_type: Mapped[InspectionType] = mapped_column(
        SQLEnum(InspectionType, name="inspection_type"), nullable=False
    )

    conducted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    conducted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rooms_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    overall_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant_signature_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    owner_signature_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    signed_by_tenant_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by_owner_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    property: Mapped[Property] = relationship(
        "Property", back_populates="inspection_checklists"
    )
    lease: Mapped[Lease] = relationship("Lease", back_populates="inspection_checklists")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    conducted_by: Mapped[User] = relationship("User", foreign_keys=[conducted_by_user_id])
    tenant_signature_document: Mapped[Document | None] = relationship(
        "Document", foreign_keys=[tenant_signature_document_id]
    )
    owner_signature_document: Mapped[Document | None] = relationship(
        "Document", foreign_keys=[owner_signature_document_id]
    )
