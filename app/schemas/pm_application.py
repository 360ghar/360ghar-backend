from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.models.enums import ApplicationFieldType, RentalApplicationStatus
from app.schemas.base import Money, UtcDateTime, WriteModel


class CustomField(BaseModel):
    """One question on an application form. Stored in the form's ``questions`` column."""

    id: str = Field(min_length=1, max_length=64, description="Stable key; answers use this id")
    label: str = Field(min_length=1, max_length=200)
    field_type: ApplicationFieldType = ApplicationFieldType.text
    is_required: bool = False
    options: list[str] | None = None


class RentalApplicationFormCreate(WriteModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    property_id: int | None = None
    title: str
    description: str | None = None
    application_fee_amount: Annotated[Money | None, Field(ge=0)] = None
    required_document_types: dict[str, Any] | None = None
    custom_fields: list[CustomField] | None = None
    is_active: bool = True
    expires_at: UtcDateTime | None = None
    config: dict[str, Any] | None = None


class RentalApplicationForm(BaseModel):
    id: int
    owner_id: int
    property_id: int | None = None
    property_name: str | None = None
    property_address: str | None = None
    title: str
    description: str | None = None
    slug: str
    is_active: bool
    expires_at: UtcDateTime | None = None
    application_fee_amount: Money | None = None
    required_document_types: dict[str, Any] | None = None
    custom_fields: list[CustomField] | None = Field(
        default=None, validation_alias=AliasChoices("custom_fields", "questions")
    )
    config: dict[str, Any] | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PublicRentalApplicationForm(BaseModel):
    slug: str
    title: str
    description: str | None = None
    property_id: int | None = None
    property_name: str | None = None
    property_address: str | None = None
    application_fee_amount: Money | None = None
    required_document_types: dict[str, Any] | None = None
    custom_fields: list[CustomField] | None = Field(
        default=None, validation_alias=AliasChoices("custom_fields", "questions")
    )
    expires_at: UtcDateTime | None = None
    config: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RentalApplicationSubmit(WriteModel):
    """Public submit body. ``answers`` is keyed by custom field id. Notes go in ``application_data``."""

    property_id: int | None = Field(
        default=None, description="Ignored when the form is tied to a property."
    )
    applicant_full_name: str | None = None
    applicant_phone: str | None = None
    applicant_email: str | None = None
    answers: dict[str, Any] | None = None
    application_data: dict[str, Any] | None = None
    emergency_contacts: dict[str, Any] | None = None


class PublicRentalApplicationSubmitted(BaseModel):
    """What an anonymous submitter sees. No owner or internal user ids."""

    id: int
    status: RentalApplicationStatus
    submitted_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)


class RentalApplicationDecision(WriteModel):
    decision: Literal["approved", "rejected"]
    notes: str | None = None


class RentalApplication(BaseModel):
    id: int
    form_id: int
    property_id: int
    property_name: str | None = None
    property_address: str | None = None
    owner_id: int
    status: RentalApplicationStatus
    applicant_full_name: str | None = None
    applicant_phone: str | None = None
    applicant_email: str | None = None
    answers: dict[str, Any] | None = None
    application_data: dict[str, Any] | None = None
    emergency_contacts: dict[str, Any] | None = None
    submitted_at: UtcDateTime | None = None
    decision_at: UtcDateTime | None = None
    decided_by_user_id: int | None = None
    decision_notes: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)
