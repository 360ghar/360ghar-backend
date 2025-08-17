from pydantic import BaseModel, EmailStr, validator
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from datetime import date, datetime
from app.utils.validators import ValidationUtils

if TYPE_CHECKING:
    from app.schemas.agent import Agent

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None

class UserCreate(UserBase):
    password: str
    
class UserUpdate(BaseModel):
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

    @validator('full_name')
    def validate_name(cls, v):
        if v:
            v = ValidationUtils.sanitize_string(v, max_length=100)
            if len(v) < 2:
                raise ValueError("Name must be at least 2 characters long")
        return v
    
    @validator('phone')
    def validate_phone(cls, v):
        if v:
            return ValidationUtils.validate_phone(v)
        return v
    
    @validator('date_of_birth')
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

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserInDB(UserBase):
    id: int
    supabase_user_id: str  # UUID from Supabase Auth
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
    
    class Config:
        from_attributes = True

class User(UserInDB):
    pass

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class UserPreferences(BaseModel):
    property_type: Optional[List[str]] = None  # house, apartment, builder_floor, room
    purpose: Optional[str] = None  # buy, rent, short_stay
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