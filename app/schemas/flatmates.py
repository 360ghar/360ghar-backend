from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    Cleanliness,
    ConversationSource,
    ConversationStatus,
    FlatmatesDrinkingType,
    FlatmatesMode,
    FlatmatesProfileStatus,
    FlatmatesSmokingType,
    FoodHabits,
    GuestsPolicy,
    MessageType,
    SleepSchedule,
    SwipeAction,
    SwipeTargetType,
    UserMatchStatus,
    UserReportReason,
    UserReportStatus,
    VisitStatus,
    WorkStyle,
)
from app.schemas.property import Property as PropertySchema
from app.utils.validators import ValidationUtils


class DiscoverProfilesQuery(BaseModel):
    """Query parameters for the discovery profiles endpoint."""

    city: str | None = None
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    move_in: str | None = None
    age_min: int | None = Field(default=None, ge=18, le=100)
    age_max: int | None = Field(default=None, ge=18, le=100)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_age_range(self):
        if (
            self.age_min is not None
            and self.age_max is not None
            and self.age_max < self.age_min
        ):
            raise ValueError("age_max must be greater than or equal to age_min")
        return self


class FlatmatesProfileUpdate(BaseModel):
    full_name: str | None = None
    profile_image_url: str | None = None
    mode: FlatmatesMode | None = None
    profile_status: FlatmatesProfileStatus | None = None
    onboarding_completed: bool | None = None
    bio: str | None = None
    age: int | None = Field(default=None, ge=18, le=100)
    profession: str | None = None
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    move_in_timeline: str | None = None
    city: str | None = None
    locality: str | None = None
    sleep_schedule: SleepSchedule | None = None
    cleanliness: Cleanliness | None = None
    food_habits: FoodHabits | None = None
    smoking: FlatmatesSmokingType | None = None
    drinking: FlatmatesDrinkingType | None = None
    native_place: str | None = Field(default=None, max_length=120)
    linkedin_url: str | None = Field(default=None, max_length=255)
    guests_policy: GuestsPolicy | None = None
    email: str | None = None
    phone: str | None = None
    work_style: WorkStyle | None = None
    gender: str | None = None
    gender_preference: str | None = None
    preferences: dict[str, Any] | None = None

    @field_validator("native_place", mode="before")
    @classmethod
    def normalize_native_place(cls, v: object) -> str | None:
        if isinstance(v, str):
            value = v.strip()
            return value or None
        return v  # type: ignore[return-value]

    @field_validator("linkedin_url", mode="before")
    @classmethod
    def validate_linkedin_url(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("linkedin_url must be a string")
        value = v.strip()
        if not value:
            # Empty string clears the field.
            return None
        if len(value) > 255:
            raise ValueError("linkedin_url must be at most 255 characters")
        if not ValidationUtils.is_absolute_url(value):
            raise ValueError("linkedin_url must be a valid http(s) URL")
        return value

    @model_validator(mode="after")
    def validate_budget_range(self):
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_max < self.budget_min
        ):
            raise ValueError("budget_max must be greater than or equal to budget_min")
        return self


class FlatmatesProfile(BaseModel):
    id: int
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    profile_image_url: str | None = None
    mode: FlatmatesMode | None = None
    profile_status: FlatmatesProfileStatus = FlatmatesProfileStatus.draft
    onboarding_completed: bool = False
    bio: str | None = None
    age: int | None = None
    profession: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    move_in_timeline: str | None = None
    city: str | None = None
    locality: str | None = None
    sleep_schedule: SleepSchedule | None = None
    cleanliness: Cleanliness | None = None
    food_habits: FoodHabits | None = None
    smoking: FlatmatesSmokingType | None = None
    drinking: FlatmatesDrinkingType | None = None
    native_place: str | None = None
    linkedin_url: str | None = None
    age_bucket: str | None = None
    guests_policy: GuestsPolicy | None = None
    work_style: WorkStyle | None = None
    gender: str | None = None
    gender_preference: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    last_active_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CatalogEntry(BaseModel):
    key: str
    version: int
    payload: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class FlatmatesRealtimeConfig(BaseModel):
    provider: Literal["supabase"] = "supabase"
    channel: str
    private: bool = True
    events: list[str]


class FlatmatesBootstrap(BaseModel):
    profile: FlatmatesProfile
    catalogs: list[CatalogEntry]
    active_listing_count: int
    conversation_count: int
    unread_message_count: int
    realtime: FlatmatesRealtimeConfig


class FlatmatesPeer(BaseModel):
    id: int
    full_name: str | None = None
    profile_image_url: str | None = None
    mode: FlatmatesMode | None = None
    city: str | None = None
    locality: str | None = None
    # Exact age is never exposed on peer payloads (privacy bucket only); the
    # field is retained as always-null for backward compatibility.
    age: int | None = None
    age_bucket: str | None = None
    profession: str | None = None
    bio: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    move_in_timeline: str | None = None
    sleep_schedule: str | None = None
    cleanliness: str | None = None
    food_habits: str | None = None
    smoking: str | None = None
    drinking: str | None = None
    native_place: str | None = None
    linkedin_url: str | None = None
    guests_policy: str | None = None
    work_style: str | None = None
    gender: str | None = None
    gender_preference: str | None = None
    non_negotiables: list[str] = Field(default_factory=list)
    has_pets: bool = False
    party_habit: str | None = None
    match_percentage: float | None = None
    top_matches: list[str] = Field(default_factory=list)
    phone_number: str | None = None


class ConversationPropertyContext(BaseModel):
    id: int
    title: str
    locality: str | None = None
    city: str | None = None
    monthly_rent: float | None = None
    main_image_url: str | None = None
    owner_name: str | None = None
    owner_image_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ConversationQnAAnswer(BaseModel):
    user_id: int
    q1: str | None = None
    q2: str | None = None
    q3: str | None = None


class ConversationQnAState(BaseModel):
    current_user: ConversationQnAAnswer | None = None
    peer: ConversationQnAAnswer | None = None
    both_answered: bool = False


class ConversationSummary(BaseModel):
    id: int
    source: ConversationSource
    status: ConversationStatus
    peer: FlatmatesPeer
    context_property: ConversationPropertyContext | None = None
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0
    matched_at: datetime | None = None
    qna: ConversationQnAState | None = None


class MessageCreate(BaseModel):
    body: str | None = None
    attachment_url: str | None = None
    message_type: MessageType = MessageType.text
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_content(self):
        if not (self.body and self.body.strip()) and not self.attachment_url:
            raise ValueError("body or attachment_url is required")
        return self


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    body: str | None = None
    attachment_url: str | None = None
    message_type: MessageType
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="message_metadata",
        serialization_alias="metadata",
    )
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MatchSummary(BaseModel):
    id: int
    status: UserMatchStatus
    peer: FlatmatesPeer
    context_property: ConversationPropertyContext | None = None
    created_at: datetime


class IncomingLikeSummary(BaseModel):
    id: int
    peer: FlatmatesPeer
    context_property: ConversationPropertyContext | None = None
    created_at: datetime


class OutgoingLikeSummary(BaseModel):
    id: int
    target_type: SwipeTargetType
    peer: FlatmatesPeer | None = None
    property: PropertySchema | None = None
    context_property: ConversationPropertyContext | None = None
    created_at: datetime


class SwipeRequest(BaseModel):
    target_type: SwipeTargetType
    action: SwipeAction
    property_id: int | None = None
    target_user_id: int | None = None
    context_property_id: int | None = None

    @model_validator(mode="after")
    def validate_target(self):
        if self.target_type == SwipeTargetType.property and self.property_id is None:
            raise ValueError("property_id is required for property swipes")
        if self.target_type == SwipeTargetType.user and self.target_user_id is None:
            raise ValueError("target_user_id is required for user swipes")
        return self


class SwipeResult(BaseModel):
    stored: bool = True
    action: SwipeAction
    target_type: SwipeTargetType
    conversation_id: int | None = None
    match_id: int | None = None
    did_match: bool = False


class ProfileViewEventCreate(BaseModel):
    target_user_id: int = Field(gt=0)
    context_property_id: int | None = Field(default=None, gt=0)
    duration_seconds: int = Field(ge=0, le=60 * 60)
    scroll_depth_percent: int | None = Field(default=None, ge=0, le=100)
    source: str = Field(default="swipe_deck", min_length=1, max_length=64)


class ProfileViewEventOut(BaseModel):
    id: int
    viewer_user_id: int
    viewed_user_id: int
    context_property_id: int | None = None
    source: str
    duration_seconds: int
    scroll_depth_percent: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SocietyTagVoteCreate(BaseModel):
    tag: str = Field(min_length=1, max_length=80)
    vote: Literal["up", "down"]


class SocietyTagVoteOut(BaseModel):
    property_id: int
    tag: str
    current_vote: Literal["up", "down"]
    upvotes: int
    downvotes: int
    disputed: bool = False


class ReportCreate(BaseModel):
    reported_user_id: int
    reason: UserReportReason
    conversation_id: int | None = None
    property_id: int | None = None
    notes: str | None = None


class ReportOut(BaseModel):
    id: int
    reporter_user_id: int
    reported_user_id: int
    reason: UserReportReason
    status: UserReportStatus
    notes: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BlockCreate(BaseModel):
    blocked_user_id: int
    unmatch_only: bool = False


class BlockOut(BaseModel):
    id: int
    blocker_user_id: int
    blocked_user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FlatmatesNotificationOut(BaseModel):
    id: str
    type: str = "general"
    title: str
    body: str
    is_read: bool = False
    reference_id: int | None = None
    route: str | None = None
    created_at: datetime


class FlatmatesNotificationUpdate(BaseModel):
    is_read: bool | None = None
    mark_all_read: bool | None = None


class FlatmateVisitUpdate(BaseModel):
    status: VisitStatus | None = None
    scheduled_date: datetime | None = None


class QnAAnswers(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_keys(self):
        for key in self.answers:
            try:
                idx = int(key)
            except ValueError as exc:
                raise ValueError(f"Answer index must be an integer, got '{key}'") from exc
            if idx < 0 or idx > 2:
                raise ValueError(f"Answer index must be between 0 and 2, got {idx}")
        return self


class MessageListResponse(BaseModel):
    """Paginated message list envelope."""
    messages: list[MessageOut]
    total: int
    has_more: bool


class BlockedUserOut(BaseModel):
    """Block record with nested peer data for the blocked user."""
    id: int
    blocked_user: FlatmatesPeer
    created_at: datetime | None = None


class ConversationCreate(BaseModel):
    """Payload for creating (or retrieving) a conversation with a peer."""
    peer_user_id: int
    initial_message: str | None = None


class ListingModerationAction(BaseModel):
    """Payload for moderating a flatmates listing (approve, reject, or request edit)."""
    action: Literal["approve", "reject", "request_edit"]
    reason: str = ""


class ReportModerationAction(BaseModel):
    """Payload for moderating a user report (dismiss, warn, suspend, or escalate)."""
    action: Literal["dismiss", "warn_user", "suspend_user", "escalate"]
    notes: str = ""


class CompatibilityDimension(BaseModel):
    """Single dimension in a compatibility breakdown."""

    name: str
    weight: float
    user_value: str | None = None
    peer_value: str | None = None
    score: float
    match: bool
    summary: str


class CompatibilityBreakdown(BaseModel):
    """Full compatibility breakdown between the current user and a peer."""

    user_id: int
    peer_id: int
    overall_percentage: float | None = None
    color: Literal["green", "amber", "red"]
    dimensions: list[CompatibilityDimension]
    summary: list[str] = Field(default_factory=list)
