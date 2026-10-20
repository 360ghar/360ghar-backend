from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.base import UtcDateTime


class AmenityBase(BaseModel):
    title: str
    icon: str | None = None
    category: str | None = None
    is_active: bool = True


class AmenityInDB(AmenityBase):
    id: int
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class Amenity(AmenityInDB):
    model_config = ConfigDict(from_attributes=True)


class PropertyAmenityResponse(BaseModel):
    id: int
    title: str
    icon: str | None = None
    category: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def flatten_amenity_relationship(cls, data: Any) -> Any:
        if hasattr(data, "amenity") and data.amenity is not None:
            # id is the amenity id (the value PUT /properties sends in amenity_ids),
            # not the property_amenities row id.
            amenity = data.amenity
            return {
                "id": amenity.id,
                "title": amenity.title,
                "icon": amenity.icon,
                "category": amenity.category,
            }
        return data
