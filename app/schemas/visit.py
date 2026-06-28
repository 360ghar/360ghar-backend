from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.models.enums import VisitContext, VisitStatus
from app.schemas.property import Property as PropertySchema
from app.schemas.user import User as UserSchema


class VisitBase(BaseModel):
    property_id: int
    scheduled_date: datetime
    special_requirements: str | None = None
    visit_context: VisitContext = VisitContext.property_tour
    counterparty_user_id: int | None = None
    conversation_id: int | None = None
    match_id: int | None = None

class VisitCreate(BaseModel):
    property_id: int = Field(
        ...,
        description="ID of the property to visit",
        examples=[1],
    )
    scheduled_date: datetime = Field(
        ...,
        description="Requested visit date and time (ISO 8601)",
        examples=["2026-07-01T10:00:00Z"],
    )
    user_id: int | None = None
    special_requirements: str | None = Field(
        default=None,
        description="Any special requests for the visit",
        examples=["Need a wheelchair-accessible entrance"],
    )
    visit_context: VisitContext = VisitContext.property_tour
    counterparty_user_id: int | None = None
    conversation_id: int | None = None
    match_id: int | None = None

class VisitUpdate(BaseModel):
    scheduled_date: datetime | None = None
    status: VisitStatus | None = None
    special_requirements: str | None = None
    visit_notes: str | None = None
    visitor_feedback: str | None = None
    interest_level: str | None = None
    follow_up_required: bool | None = None
    follow_up_date: datetime | None = None
    cancellation_reason: str | None = None
    visit_context: VisitContext | None = None
    counterparty_user_id: int | None = None
    conversation_id: int | None = None
    match_id: int | None = None

class VisitReschedule(BaseModel):
    new_date: datetime
    reason: str | None = None

class VisitCancel(BaseModel):
    reason: str

class VisitComplete(BaseModel):
    """Payload for marking a visit as completed."""
    notes: str | None = None
    feedback: str | None = None

class VisitAgentInfo(BaseModel):
    id: int
    name: str
    phone: str | None = Field(
        default=None, validation_alias=AliasChoices("contact_number", "phone")
    )
    avatar_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class Visit(VisitBase):
    id: int
    user_id: int
    agent_id: int | None = None
    agents: VisitAgentInfo | None = Field(
        default=None, validation_alias=AliasChoices("agent", "agents")
    )
    actual_date: datetime | None = None
    status: VisitStatus
    visit_notes: str | None = None
    visitor_feedback: str | None = None
    interest_level: str | None = None
    follow_up_required: bool = False
    follow_up_date: datetime | None = None
    cancellation_reason: str | None = None
    rescheduled_from: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    property: PropertySchema | None = None
    counterparty_user: UserSchema | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("visit_context", mode="before")
    @classmethod
    def coerce_visit_context(cls, v: Any) -> VisitContext:
        try:
            return VisitContext(v)
        except ValueError:
            return VisitContext.property_tour

class VisitSlice(BaseModel):
    visits: list[Visit]
    total: int
