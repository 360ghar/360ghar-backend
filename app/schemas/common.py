from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.base import NotNullable, PatchModel, WriteModel


class MessageResponse(BaseModel):
    message: str


class NotificationSettings(BaseModel):
    """Notification preferences: one key per channel or category, as returned by the API.

    Keys with no implementation are not part of the contract. Marketing consent
    is ``promotional_emails`` only. A missing or false value means opt-out.
    Unknown stored keys are ignored on read.
    """

    model_config = ConfigDict(extra="ignore")

    push_notifications: bool = True
    email_notifications: bool = True
    sms_notifications: bool = False
    promotional_emails: bool = False


class NotificationSettingsWrite(NotificationSettings):
    """Body of a settings update. Unknown keys fail with 422."""

    model_config = ConfigDict(extra="forbid")


ProfileVisibility = Literal["public", "agents_only", "private"]


class PrivacySettings(BaseModel):
    """Privacy preferences as returned by the API. Unknown stored keys are ignored on read."""

    model_config = ConfigDict(extra="ignore")

    profile_visibility: ProfileVisibility = "public"
    location_sharing: bool = True
    contact_sharing: bool = True
    search_history_tracking: bool = True
    hide_last_name: bool = False
    show_phone: bool = False
    show_email: bool = False
    allow_location_tracking: bool = True
    data_sharing_consent: bool = False

    @field_validator("profile_visibility", mode="before")
    @classmethod
    def _unknown_visibility_is_private(cls, value: object) -> object:
        """A stored legacy value (such as "friends") reads as the most restrictive option.

        Without this the whole blob fails validation and falls back to "public", which would
        expose a profile the user had restricted.
        """
        if isinstance(value, str) and value not in ("public", "agents_only", "private"):
            return "private"
        return value


class PrivacySettingsPatch(PatchModel):
    """Body of a privacy update. Only sent keys change; unknown keys and nulls fail with 422."""

    profile_visibility: Annotated[ProfileVisibility | None, NotNullable] = None
    location_sharing: Annotated[bool | None, NotNullable] = None
    contact_sharing: Annotated[bool | None, NotNullable] = None
    search_history_tracking: Annotated[bool | None, NotNullable] = None
    hide_last_name: Annotated[bool | None, NotNullable] = None
    show_phone: Annotated[bool | None, NotNullable] = None
    show_email: Annotated[bool | None, NotNullable] = None
    allow_location_tracking: Annotated[bool | None, NotNullable] = None
    data_sharing_consent: Annotated[bool | None, NotNullable] = None


class AssignAgentPayload(WriteModel):
    """Payload for assigning an agent to a user. Unknown keys fail with 422."""

    agent_id: int
