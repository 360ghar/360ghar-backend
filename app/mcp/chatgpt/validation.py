"""
Validation schemas for ChatGPT App tools.

These Pydantic models validate input parameters for ChatGPT-specific tools.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator

from app.models.enums import PropertyType, PropertyPurpose


class PropertySearchInput(BaseModel):
    """Input schema for discovery_search tool."""

    query: Optional[str] = Field(
        None,
        description="Text search query for property title, description, or locality",
        max_length=200,
    )
    latitude: Optional[float] = Field(
        None,
        ge=-90,
        le=90,
        description="Search center latitude for location-based search",
    )
    longitude: Optional[float] = Field(
        None,
        ge=-180,
        le=180,
        description="Search center longitude for location-based search",
    )
    radius_km: int = Field(
        5,
        ge=1,
        le=100,
        description="Search radius in kilometers (default 5, max 100)",
    )
    property_type: Optional[str] = Field(
        None,
        description="Filter by property type: house, apartment, builder_floor, room",
    )
    purpose: Optional[str] = Field(
        None,
        description="Filter by purpose: buy, rent, short_stay",
    )
    price_min: Optional[float] = Field(
        None,
        ge=0,
        description="Minimum price filter",
    )
    price_max: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum price filter",
    )
    bedrooms_min: Optional[int] = Field(
        None,
        ge=0,
        le=20,
        description="Minimum number of bedrooms",
    )
    bedrooms_max: Optional[int] = Field(
        None,
        ge=0,
        le=20,
        description="Maximum number of bedrooms",
    )
    amenities: Optional[List[str]] = Field(
        None,
        description="List of required amenity names",
    )
    page: int = Field(
        1,
        ge=1,
        description="Page number for pagination",
    )
    limit: int = Field(
        20,
        ge=1,
        le=50,
        description="Results per page (max 50)",
    )

    @field_validator("property_type")
    @classmethod
    def validate_property_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_types = [t.value for t in PropertyType]
            if v not in valid_types:
                raise ValueError(f"Invalid property_type. Must be one of: {valid_types}")
        return v

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_purposes = [p.value for p in PropertyPurpose]
            if v not in valid_purposes:
                raise ValueError(f"Invalid purpose. Must be one of: {valid_purposes}")
        return v

    @field_validator("price_max")
    @classmethod
    def validate_price_range(cls, v: Optional[float], info) -> Optional[float]:
        price_min = info.data.get("price_min")
        if v is not None and price_min is not None and v < price_min:
            raise ValueError("price_max must be greater than or equal to price_min")
        return v


class PropertyGetInput(BaseModel):
    """Input schema for discovery_property_get tool."""

    property_id: int = Field(
        ...,
        gt=0,
        description="Property ID to retrieve",
    )


class DiscoveryFeedInput(BaseModel):
    """Input schema for discovery_feed tool."""

    latitude: Optional[float] = Field(
        None,
        ge=-90,
        le=90,
        description="User's current latitude for personalized recommendations",
    )
    longitude: Optional[float] = Field(
        None,
        ge=-180,
        le=180,
        description="User's current longitude for personalized recommendations",
    )
    purpose: Optional[str] = Field(
        None,
        description="Filter by purpose: buy, rent, short_stay",
    )
    limit: int = Field(
        10,
        ge=1,
        le=20,
        description="Number of properties to return (max 20)",
    )

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_purposes = [p.value for p in PropertyPurpose]
            if v not in valid_purposes:
                raise ValueError(f"Invalid purpose. Must be one of: {valid_purposes}")
        return v


class SwipeInput(BaseModel):
    """Input schema for discovery_swipe tool."""

    property_id: int = Field(
        ...,
        gt=0,
        description="Property ID being swiped",
    )
    is_liked: bool = Field(
        ...,
        description="True for like (right swipe), False for pass (left swipe)",
    )


class ShortlistInput(BaseModel):
    """Input schema for discovery_shortlist tool."""

    page: int = Field(
        1,
        ge=1,
        description="Page number for pagination",
    )
    limit: int = Field(
        20,
        ge=1,
        le=50,
        description="Results per page (max 50)",
    )


class VisitScheduleInput(BaseModel):
    """Input schema for visits_schedule tool."""

    property_id: int = Field(
        ...,
        gt=0,
        description="Property ID to schedule visit for",
    )
    scheduled_date: datetime = Field(
        ...,
        description="Scheduled date and time for the visit (ISO 8601 format)",
    )
    notes: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional notes for the visit",
    )

    @field_validator("scheduled_date")
    @classmethod
    def validate_future_date(cls, v: datetime) -> datetime:
        from datetime import timezone

        now = datetime.now(timezone.utc)
        # Make naive datetime aware (assume UTC)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= now:
            raise ValueError("scheduled_date must be in the future")
        return v


class VisitListInput(BaseModel):
    """Input schema for visits_list tool."""

    status: Optional[str] = Field(
        None,
        description="Filter by status: scheduled, confirmed, completed, cancelled, rescheduled",
    )
    page: int = Field(
        1,
        ge=1,
        description="Page number for pagination",
    )
    limit: int = Field(
        20,
        ge=1,
        le=50,
        description="Results per page (max 50)",
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_statuses = ["scheduled", "confirmed", "completed", "cancelled", "rescheduled"]
            if v not in valid_statuses:
                raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")
        return v


class VisitGetInput(BaseModel):
    """Input schema for visits_get tool."""

    visit_id: int = Field(
        ...,
        gt=0,
        description="Visit ID to retrieve",
    )


class VisitCancelInput(BaseModel):
    """Input schema for visits_cancel tool."""

    visit_id: int = Field(
        ...,
        gt=0,
        description="Visit ID to cancel",
    )
    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional reason for cancellation",
    )
