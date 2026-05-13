from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class AmenityBase(BaseModel):
    title: str
    icon: str | None = None
    category: str | None = None
    is_active: bool = True

class AmenityCreate(AmenityBase):
    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if not v or len(v.strip()) < 2:
            raise ValueError('Title must be at least 2 characters long')
        if len(v) > 100:
            raise ValueError('Title must be less than 100 characters')
        return v.strip()

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v:
            allowed_categories = ['safety', 'recreation', 'convenience', 'utilities', 'services', 'accessibility']
            if v not in allowed_categories:
                raise ValueError(f'Category must be one of: {", ".join(allowed_categories)}')
        return v

class AmenityUpdate(BaseModel):
    title: str | None = None
    icon: str | None = None
    category: str | None = None
    is_active: bool | None = None

class AmenityInDB(AmenityBase):
    id: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

class Amenity(AmenityInDB):
    pass

class PropertyAmenityCreate(BaseModel):
    amenity_id: int

class PropertyAmenityResponse(BaseModel):
    id: int
    title: str
    icon: str | None = None
    category: str | None = None

    model_config = ConfigDict(from_attributes=True)
