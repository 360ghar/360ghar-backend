from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TenantStatus


class RentalApplicationFormCreate(BaseModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    property_id: int | None = None
    title: str
    description: str | None = None
    application_fee_amount: float | None = None
    required_document_types: dict[str, Any] | None = None
    questions: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class RentalApplicationForm(BaseModel):
    id: int
    owner_id: int
    property_id: int | None = None
    title: str
    description: str | None = None
    slug: str
    is_active: bool
    application_fee_amount: float | None = None
    required_document_types: dict[str, Any] | None = None
    questions: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PublicRentalApplicationForm(BaseModel):
    slug: str
    title: str
    description: str | None = None
    property_id: int | None = None
    application_fee_amount: float | None = None
    required_document_types: dict[str, Any] | None = None
    questions: dict[str, Any] | None = None
    config: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class RentalApplicationSubmit(BaseModel):
    property_id: int | None = None
    applicant_full_name: str | None = None
    applicant_phone: str | None = None
    applicant_email: str | None = None
    answers: dict[str, Any] | None = None
    application_data: dict[str, Any] | None = None
    emergency_contacts: dict[str, Any] | None = None


class RentalApplicationDecision(BaseModel):
    decision: TenantStatus


class RentalApplication(BaseModel):
    id: int
    form_id: int
    property_id: int
    owner_id: int
    status: TenantStatus
    applicant_user_id: int | None = None
    applicant_full_name: str | None = None
    applicant_phone: str | None = None
    applicant_email: str | None = None
    answers: dict[str, Any] | None = None
    application_data: dict[str, Any] | None = None
    emergency_contacts: dict[str, Any] | None = None
    submitted_at: datetime | None = None
    decision_at: datetime | None = None
    decided_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

