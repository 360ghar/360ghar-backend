from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InspectionType
from app.schemas.base import UtcDateTime, WriteModel


class InspectionChecklistCreate(WriteModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    lease_id: int
    inspection_type: InspectionType
    rooms_data: dict[str, Any] | None = None
    overall_notes: str | None = None
    conducted_at: UtcDateTime | None = None


class InspectionChecklist(BaseModel):
    id: int
    property_id: int
    lease_id: int
    owner_id: int
    inspection_type: InspectionType
    conducted_by_user_id: int
    conducted_at: UtcDateTime
    rooms_data: dict[str, Any] | None = None
    overall_notes: str | None = None
    tenant_signature_document_id: int | None = None
    owner_signature_document_id: int | None = None
    signed_by_tenant_at: UtcDateTime | None = None
    signed_by_owner_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)


class InspectionSign(WriteModel):
    """Both fields are optional. An empty object is a valid body."""

    tenant_signature_document_id: int | None = None
    owner_signature_document_id: int | None = None
