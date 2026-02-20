from pydantic import BaseModel, EmailStr, field_validator, ConfigDict
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from datetime import date, datetime
from app.models.enums import PropertyPurpose, PropertyType
from app.utils.validators import ValidationUtils

if TYPE_CHECKING:
    from app.schemas.agent import Agent

class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None

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
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    profile_image_url: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None
    preferred_locations: Optional[List[str]] = None
    notification_settings: Optional[Dict[str, bool]] = None
    privacy_settings: Optional[Dict[str, Any]] = None

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
                raise ValueError(f"Invalid date of birth")
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
    role: str = 'user'
    is_active: bool
    is_verified: bool
    profile_image_url: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None
    preferred_locations: Optional[List[str]] = None
    notification_settings: Optional[Dict[str, bool]] = None
    privacy_settings: Optional[Dict[str, Any]] = None
    agent_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class User(UserInDB):
    pass

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    phone: Optional[str] = None

class UserPreferences(BaseModel):
    property_type: Optional[List[PropertyType]] = None
    purpose: Optional[PropertyPurpose] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    bedrooms_max: Optional[int] = None
    area_min: Optional[float] = None
    area_max: Optional[float] = None
    location_preference: Optional[List[str]] = None
    max_distance_km: Optional[int] = 5

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
