from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.models.enums import VisitContext, VisitStatus
from app.schemas.base import NotNullable, PatchModel, PublicUserRef, UtcDateTime, WriteModel
from app.schemas.property import Property as PropertySchema

# Cancel, reschedule and complete each have one route. PUT /visits/{id} only confirms.
_PUT_STATUS_ROUTE = {
    VisitStatus.cancelled: "Use POST /visits/{id}/cancel to cancel a visit.",
    VisitStatus.completed: "Use POST /visits/{id}/complete to complete a visit.",
    VisitStatus.reschedule_suggested: "Use POST /visits/{id}/reschedule to reschedule a visit.",
    VisitStatus.requested: "A visit cannot return to the requested status.",
}


def _require_utc_offset(value: object) -> object:
    """Reject a naive visit time. UtcDateTime would read it as UTC, so 14:00 IST is stored 5h30m late."""
    parsed: object = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value  # the datetime validator reports the format error
    if isinstance(parsed, datetime) and parsed.tzinfo is None:
        raise ValueError(
            "Include a UTC offset, for example 2026-07-01T10:00:00+05:30 or 2026-07-01T04:30:00Z"
        )
    return value


# A visit time must carry an offset or Z. The API stores and returns UTC.
VisitTime = Annotated[UtcDateTime, BeforeValidator(_require_utc_offset)]


class VisitBase(BaseModel):
    property_id: int
    scheduled_date: UtcDateTime
    special_requirements: str | None = None
    visit_context: VisitContext = VisitContext.property_tour
    counterparty_user_id: int | None = None
    conversation_id: int | None = None
    match_id: int | None = None


class VisitCreate(WriteModel):
    property_id: int = Field(
        ...,
        description="ID of the property to visit",
        examples=[1],
    )
    scheduled_date: VisitTime = Field(
        ...,
        description="Requested visit date and time (ISO 8601). Include a UTC offset, for example +05:30 or Z.",
        examples=["2026-07-01T10:00:00Z"],
    )
    user_id: int | None = Field(
        default=None,
        description="Visit owner. Admins and agents may set it. Other callers always own the visit.",
    )
    time_slot_label: str | None = Field(
        default=None,
        max_length=64,
        description="Label of the chosen time slot, for example 'morning'",
        examples=["morning"],
    )
    special_requirements: str | None = Field(
        default=None,
        description="Any special requests for the visit",
        examples=["Need a wheelchair-accessible entrance"],
    )
    visit_context: VisitContext = VisitContext.property_tour
    counterparty_user_id: int | None = None
    conversation_id: int | None = None
    match_id: int | None = None


class VisitUpdate(PatchModel):
    """Partial update. Cancel, reschedule and complete have their own routes."""

    status: Annotated[VisitStatus | None, NotNullable] = None
    special_requirements: str | None = None
    visit_notes: str | None = None
    visitor_feedback: str | None = None
    interest_level: str | None = None
    follow_up_required: Annotated[bool | None, NotNullable] = None
    follow_up_date: UtcDateTime | None = None

    @field_validator("status")
    @classmethod
    def only_confirm_through_put(cls, value: VisitStatus | None) -> VisitStatus | None:
        if value is None or value == VisitStatus.confirmed:
            return value
        raise ValueError(_PUT_STATUS_ROUTE.get(value, "Only 'confirmed' can be set here."))


class VisitReschedule(WriteModel):
    new_date: VisitTime
    reason: str | None = None


class VisitCancel(WriteModel):
    # Whitespace is stripped before the length check, so "   " is rejected.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class VisitComplete(WriteModel):
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


class Visit(BaseModel):
    """Visit response. The counterparty is a PublicUserRef: name and avatar only."""

    id: int
    property_id: int
    user_id: int
    counterparty_user_id: int | None = None
    conversation_id: int | None = None
    match_id: int | None = None
    visit_context: VisitContext = VisitContext.property_tour
    scheduled_date: UtcDateTime
    time_slot_label: str | None = None
    special_requirements: str | None = None
    agent_id: int | None = None
    agents: VisitAgentInfo | None = Field(
        default=None, validation_alias=AliasChoices("agent", "agents")
    )
    status: VisitStatus
    actual_date: UtcDateTime | None = None
    visit_notes: str | None = None
    visitor_feedback: str | None = None
    interest_level: str | None = None
    follow_up_required: bool = False
    follow_up_date: UtcDateTime | None = None
    cancellation_reason: str | None = Field(
        default=None,
        description="Cancel reason. A reschedule reason is also stored here (no separate column).",
    )
    rescheduled_from: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None
    property: PropertySchema | None = None
    user: PublicUserRef | None = None
    counterparty_user: PublicUserRef | None = None

    model_config = ConfigDict(from_attributes=True)
