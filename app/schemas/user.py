from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.core.logging import get_logger
from app.models.enums import AuthMethod, PropertyPurpose, PropertyType, UserRole
from app.schemas.base import Money, NotNullable, PatchModel, UtcDateTime, WriteModel
from app.schemas.common import (
    NotificationSettings,
    NotificationSettingsWrite,
    PrivacySettings,
    PrivacySettingsPatch,
)
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)

AuthStage = Literal[
    "identifier_verification", "password_setup", "profile_completion", "app_onboarding", "active"
]
AuthNextAction = Literal[
    "verify_identifier", "set_password", "complete_profile", "complete_onboarding", "grant_access"
]


def _blank_date_to_none(value: Any) -> Any:
    """An empty date string (from a blank form field) means "no date"."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _validated_phone(value: str) -> str:
    """E.164 check. Failures carry a stable code (PHONE_INVALID) for the client."""
    try:
        return ValidationUtils.validate_phone(value)
    except ValueError as exc:
        raise PydanticCustomError("PHONE_INVALID", str(exc)) from None


_BlobModel = TypeVar("_BlobModel", bound=BaseModel)


def read_typed_blob(model: type[_BlobModel], raw: Any) -> _BlobModel:
    """Typed view of a stored JSON blob (preferences, notifications, privacy).

    Keys outside ``model`` are dropped. A key whose stored value fails validation
    is dropped and logged. A NULL or non-object column reads as the defaults.
    A stored value of the wrong type never fails the read.
    """
    if isinstance(raw, model):
        return raw
    if not isinstance(raw, dict):
        return model()
    valid: dict[str, Any] = {}
    for key in model.model_fields:
        if key not in raw or raw[key] is None:
            continue
        try:
            model.model_validate({key: raw[key]})
        except ValidationError:
            logger.warning("Dropping invalid stored %s key %s", model.__name__, key)
            continue
        valid[key] = raw[key]
    return model(**valid)


class UserPreferences(BaseModel):
    """Stored preferences as returned by the API."""

    property_type: list[PropertyType] | None = None
    purpose: PropertyPurpose | None = None
    budget_min: Money | None = None
    budget_max: Money | None = None
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    location_preference: list[str] | None = None
    max_distance_km: int | None = 5


class UserBase(BaseModel):
    email: EmailStr | None = Field(
        default=None,
        description="User email address (unique, used for login)",
        examples=["user@example.com"],
    )
    full_name: str | None = Field(
        default=None,
        description="Full display name of the user",
        examples=["Rahul Sharma"],
    )
    phone: str | None = Field(
        default=None,
        description="Phone number in E.164 format",
        examples=["+919876543210"],
    )
    date_of_birth: date | None = None

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v):
        # Coerce empty strings to None so Optional[EmailStr] passes validation
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def empty_dob_to_none(cls, v: Any) -> Any:
        return _blank_date_to_none(v)


class UserUpdate(PatchModel):
    """Self-service profile update. Only sent keys change.

    Email changes go through Supabase. Phone changes go through
    ``PUT /users/me/phone`` (OTP). Preferences go through
    ``PUT /users/preferences``. Unknown keys fail with 422.
    """

    full_name: str | None = Field(
        default=None,
        description="Full display name of the user",
        examples=["Rahul Sharma"],
    )
    phone: str | None = Field(
        default=None,
        description="Phone number in E.164 format. A blank value is ignored; null is rejected.",
        examples=["+919876543210"],
    )
    date_of_birth: date | None = None
    current_latitude: float | None = Field(default=None, ge=-90, le=90)
    current_longitude: float | None = Field(default=None, ge=-180, le=180)
    notification_settings: NotificationSettingsWrite | None = None
    privacy_settings: PrivacySettingsPatch | None = None

    @model_validator(mode="before")
    @classmethod
    def drop_blank_phone(cls, data: Any) -> Any:
        # An unchanged blank phone (phoneless account) is "not sent", not a clear.
        if (
            isinstance(data, dict)
            and isinstance(data.get("phone"), str)
            and not data["phone"].strip()
        ):
            return {key: value for key, value in data.items() if key != "phone"}
        return data

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v):
        # null clears the name (the column is nullable). A blank or one-character
        # name is rejected, so '' never reaches the database.
        if v is None:
            return v
        v = ValidationUtils.sanitize_string(v, max_length=100)
        if len(v) < 2:
            raise PydanticCustomError("NAME_LENGTH", "Name must be at least 2 characters long")
        return v

    @field_validator("phone", mode="after")
    @classmethod
    def validate_phone(cls, v: str | None) -> str:
        if v is None:
            raise PydanticCustomError(
                "PHONE_REQUIRED", "Phone cannot be cleared here. Use PUT /users/me/phone."
            )
        return _validated_phone(v)

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def empty_dob_to_none(cls, v: Any) -> Any:
        return _blank_date_to_none(v)

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v):
        if v:
            min_age = 18
            max_age = 120
            today = datetime.now(UTC).date()
            age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))

            # Stable codes: clients localize the code in details.fields[].type.
            if age < min_age:
                raise PydanticCustomError("AGE_RANGE", f"Must be at least {min_age} years old")
            if age > max_age:
                raise PydanticCustomError("AGE_RANGE", "Invalid date of birth")
        return v


class AdminUserUpdate(UserUpdate):
    """Update body for PUT /users/{id}. ``is_active`` is staff-only (admins)."""

    is_active: Annotated[bool | None, NotNullable] = None


class UserInDB(UserBase):
    """A user as the API returns it. The Supabase UUID is not part of this shape."""

    id: int
    role: UserRole = UserRole.user
    is_active: bool
    is_verified: bool
    phone_verified: bool = False
    email_verified: bool = False
    last_auth_method: AuthMethod | None = None
    last_auth_method_at: UtcDateTime | None = None
    profile_image_url: str | None = None
    # Stored JSON blobs are typed on read (read_typed_blob): keys outside the
    # model and invalid stored values are dropped, a NULL column reads as defaults.
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    current_latitude: float | None = None
    current_longitude: float | None = None
    notification_settings: NotificationSettings = Field(default_factory=NotificationSettings)
    privacy_settings: PrivacySettings = Field(default_factory=PrivacySettings)
    agent_id: int | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def coerce_dob(cls, v: Any) -> Any:
        if isinstance(v, datetime):
            return v.date()
        return v

    @field_validator("preferences", mode="before")
    @classmethod
    def typed_preferences(cls, v: Any) -> Any:
        return read_typed_blob(UserPreferences, v)

    @field_validator("notification_settings", mode="before")
    @classmethod
    def typed_notification_settings(cls, v: Any) -> Any:
        return read_typed_blob(NotificationSettings, v)

    @field_validator("privacy_settings", mode="before")
    @classmethod
    def typed_privacy_settings(cls, v: Any) -> Any:
        return read_typed_blob(PrivacySettings, v)

    model_config = ConfigDict(from_attributes=True)


class User(UserInDB):
    """The public user shape. Used by every route that returns a user."""

    model_config = ConfigDict(from_attributes=True)


class SelfUser(User):
    """The signed-in user's own record (GET/PUT /users/me and the profile routes)."""

    supabase_user_id: str  # UUID from Supabase Auth. Not a credential.


class AgentSummary(BaseModel):
    """The agent assigned to a user, as admins and agents see it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_number: str | None = None


class AdminUser(User):
    """A user as admins and agents see it: adds the assigned agent summary."""

    agent: AgentSummary | None = None


class AuthGateState(BaseModel):
    """Result of GET /users/me/auth-state: the gate the client routes to."""

    stage: AuthStage
    next_action: AuthNextAction
    missing_fields: list[str] = Field(default_factory=list)


class Token(BaseModel):
    access_token: str
    token_type: str


class UserPreferencesPatch(PatchModel):
    """Body of PUT /users/preferences. A key sent as null is removed from the stored object."""

    property_type: list[PropertyType] | None = None
    purpose: PropertyPurpose | None = None
    budget_min: Money | None = None
    budget_max: Money | None = None
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    location_preference: list[str] | None = None
    max_distance_km: int | None = None


class LocationUpdate(WriteModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class UserLocation(BaseModel):
    """The stored location after PUT /users/location."""

    current_latitude: float | None
    current_longitude: float | None


class PhoneUpdate(WriteModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not v or not v.strip():
            raise PydanticCustomError("PHONE_REQUIRED", "Phone number is required")
        return _validated_phone(v)
