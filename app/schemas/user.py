from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.enums import PropertyPurpose, PropertyType, UserRole
from app.utils.validators import ValidationUtils


class UserBase(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    phone: str | None = None
    date_of_birth: date | None = None

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v):
        # Coerce empty strings to None so Optional[EmailStr] passes validation
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

class UserCreate(UserBase):
    phone: str  # Override to make phone required for registration
    password: str

    @field_validator('phone')
    @classmethod
    def validate_phone_create(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Phone number is required for registration")
        return ValidationUtils.validate_phone(v)

class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    phone: str | None = None
    date_of_birth: date | None = None
    profile_image_url: str | None = None
    preferences: dict[str, Any] | None = None
    current_latitude: float | None = None
    current_longitude: float | None = None
    notification_settings: dict[str, bool] | None = None
    privacy_settings: dict[str, Any] | None = None

    @field_validator('full_name')
    @classmethod
    def validate_name(cls, v):
        if v:
            v = ValidationUtils.sanitize_string(v, max_length=100)
            if len(v) < 2:
                raise ValueError("Name must be at least 2 characters long")
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v:
            return ValidationUtils.validate_phone(v)
        return v

    @field_validator('date_of_birth')
    @classmethod
    def validate_dob(cls, v):
        if v:
            min_age = 18
            max_age = 120
            today = date.today()
            age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))

            if age < min_age:
                raise ValueError(f"Must be at least {min_age} years old")
            if age > max_age:
                raise ValueError("Invalid date of birth")
        return v

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v):
        # Coerce empty strings to None so Optional[EmailStr] passes validation
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

class UserLogin(BaseModel):
    phone: str
    password: str

    @field_validator('phone')
    @classmethod
    def validate_phone_login(cls, v: str) -> str:
        return ValidationUtils.validate_phone(v)

class UserInDB(UserBase):
    id: int
    supabase_user_id: str  # UUID from Supabase Auth
    role: UserRole = UserRole.user
    is_active: bool
    is_verified: bool
    profile_image_url: str | None = None
    preferences: dict[str, Any] | None = None
    current_latitude: float | None = None
    current_longitude: float | None = None
    notification_settings: dict[str, bool] | None = None
    privacy_settings: dict[str, Any] | None = None
    agent_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

class User(UserInDB):
    pass

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    phone: str | None = None

class UserPreferences(BaseModel):
    property_type: list[PropertyType] | None = None
    purpose: PropertyPurpose | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    location_preference: list[str] | None = None
    max_distance_km: int | None = 5

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
