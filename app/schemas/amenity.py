from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import datetime

class AmenityBase(BaseModel):
    title: str
    icon: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = True

class AmenityCreate(AmenityBase):
    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Title must be at least 2 characters long')
        if len(v) > 100:
            raise ValueError('Title must be less than 100 characters')
        return v.strip()
    
    @validator('category')
    def validate_category(cls, v):
        if v:
            allowed_categories = ['safety', 'recreation', 'convenience', 'utilities', 'services', 'accessibility']
            if v not in allowed_categories:
                raise ValueError(f'Category must be one of: {", ".join(allowed_categories)}')
        return v

class AmenityUpdate(BaseModel):
    title: Optional[str] = None
    icon: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None

class AmenityInDB(AmenityBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class Amenity(AmenityInDB):
    pass

class PropertyAmenityCreate(BaseModel):
    amenity_id: int

class PropertyAmenityResponse(BaseModel):
    id: int
    title: str
    icon: Optional[str] = None
    category: Optional[str] = None
    
    class Config:
        from_attributes = True