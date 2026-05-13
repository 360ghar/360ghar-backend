from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InspectionType


class InspectionChecklistCreate(BaseModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    lease_id: int
    inspection_type: InspectionType
    rooms_data: dict[str, Any] | None = None
    overall_notes: str | None = None
    conducted_at: datetime | None = None


class InspectionChecklist(BaseModel):
    id: int
    property_id: int
    lease_id: int
    owner_id: int
    inspection_type: InspectionType
    conducted_by_user_id: int
    conducted_at: datetime
    rooms_data: dict[str, Any] | None = None
    overall_notes: str | None = None
    tenant_signature_document_id: int | None = None
    owner_signature_document_id: int | None = None
    signed_by_tenant_at: datetime | None = None
    signed_by_owner_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class InspectionSign(BaseModel):
    tenant_signature_document_id: int | None = None
    owner_signature_document_id: int | None = None

