from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    Cleanliness,
    ConversationSource,
    ConversationStatus,
    FlatmatesMode,
    FlatmatesProfileStatus,
    FoodHabits,
    GuestsPolicy,
    MessageType,
    SleepSchedule,
    SmokingDrinking,
    SwipeAction,
    SwipeTargetType,
    UserMatchStatus,
    UserReportReason,
    UserReportStatus,
    VisitStatus,
    WorkStyle,
)


class DiscoverProfilesQuery(BaseModel):
    """Query parameters for the discovery profiles endpoint."""

    city: str | None = None
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    move_in: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


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
    smoking_drinking: SmokingDrinking | None = None
    guests_policy: GuestsPolicy | None = None
    email: str | None = None
    phone: str | None = None
    work_style: WorkStyle | None = None
    gender: str | None = None
    gender_preference: str | None = None
    preferences: dict[str, Any] | None = None

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
    smoking_drinking: SmokingDrinking | None = None
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


class FlatmatesBootstrap(BaseModel):
    profile: FlatmatesProfile
    catalogs: list[CatalogEntry]
    active_listing_count: int
    conversation_count: int
    unread_message_count: int


class FlatmatesPeer(BaseModel):
    id: int
    full_name: str | None = None
    profile_image_url: str | None = None
    mode: FlatmatesMode | None = None
    city: str | None = None
    locality: str | None = None
    age: int | None = None
    profession: str | None = None
    bio: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    move_in_timeline: str | None = None
    sleep_schedule: str | None = None
    cleanliness: str | None = None
    food_habits: str | None = None
    smoking_drinking: str | None = None
    guests_policy: str | None = None
    work_style: str | None = None
    gender: str | None = None
    gender_preference: str | None = None
    non_negotiables: list[str] = Field(default_factory=list)
    has_pets: bool = False
    party_habit: str | None = None
    match_percentage: float | None = None
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
