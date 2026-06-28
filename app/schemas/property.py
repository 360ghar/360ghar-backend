from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.core.exceptions import ValidationException
from app.models.enums import (
    PG_FLATMATE_TYPES,
    ImageCategory,
    ListingGenderPreference,
    ListingSharingType,
    ManagedPropertyStatus,
    PropertyPurpose,
    PropertyStatus,
    PropertyType,
)
from app.schemas.amenity import PropertyAmenityResponse
from app.utils.validators import ValidationUtils


def _validate_listing_contract(property_type: PropertyType, purpose: PropertyPurpose) -> None:
    if property_type in PG_FLATMATE_TYPES and purpose != PropertyPurpose.rent:
        raise ValueError("PG and flatmate listings must use purpose 'rent'")


class ListingPreferences(BaseModel):
    gender_preference: ListingGenderPreference | None = None
    sharing_type: ListingSharingType | None = None
    moderation_status: str | None = None
    moderation_reason: str | None = None
    video_tour_url: str | None = None
    expires_at: str | None = None
    food_habits: str | None = None
    smoking_drinking: str | None = None
    guests_policy: str | None = None
    cleanliness: str | None = None
    pets: str | None = None
    parties_at_home: str | None = None

    model_config = ConfigDict(from_attributes=True, extra="allow")


class PropertyImageBase(BaseModel):
    image_url: str
    caption: str | None = None
    image_category: ImageCategory = ImageCategory.others
    display_order: int | None = None
    is_main_image: bool = False


class PropertyImageCreate(PropertyImageBase):
    pass


class PropertyImage(PropertyImageBase):
    id: int
    property_id: int

    model_config = ConfigDict(from_attributes=True)


class PropertyBase(BaseModel):
    title: str = Field(
        ...,
        description="Listing title shown in search results and detail pages",
        examples=["2BHK Apartment in Koramangala"],
    )
    description: str | None = Field(
        default=None,
        description="Detailed description of the property (HTML/markdown allowed)",
        examples=["Spacious 2BHK with balcony, near metro station"],
    )
    property_type: PropertyType = Field(
        ...,
        description="Listing category (apartment, villa, pg, flatmate, etc.)",
        examples=["apartment"],
    )
    purpose: PropertyPurpose = Field(
        ...,
        description="Listing intent: sale, rent, or short stay",
        examples=["rent"],
    )
    base_price: float = Field(
        ...,
        description="Base price (sale price or monthly rent anchor, in INR)",
        examples=[50000],
    )

    # Location fields
    latitude: float | None = None
    longitude: float | None = None
    city: str | None = Field(
        default=None,
        description="City where the property is located",
        examples=["Bengaluru"],
    )
    state: str | None = None
    country: str = "India"
    pincode: str | None = None
    locality: str | None = Field(
        default=None,
        description="Neighbourhood or locality within the city",
        examples=["Koramangala"],
    )
    sub_locality: str | None = None
    landmark: str | None = None
    full_address: str | None = None
    area_type: str | None = None

    area_sqft: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    balconies: int | None = None
    parking_spaces: int | None = None
    listing_preferences: ListingPreferences | None = None
    video_urls: list[str] | None = None
    google_street_view_url: str | None = None
    floor_plan_url: str | None = None
    video_tour_url: str | None = None


class PropertyCreate(PropertyBase):
    price_per_sqft: float | None = None
    monthly_rent: float | None = None
    daily_rate: float | None = None
    security_deposit: float | None = None
    maintenance_charges: float | None = None
    floor_number: int | None = None
    total_floors: int | None = None
    age_of_property: int | None = None
    max_occupancy: int | None = None
    minimum_stay_days: int | None = 1
    amenity_ids: list[int] | None = None
    features: list[str] | None = None
    main_image_url: str | None = None
    image_urls: list[str] | None = None
    virtual_tour_url: str | None = None
    available_from: str | None = None
    calendar_data: dict[str, Any] | None = None
    tags: list[str] | None = None
    owner_name: str | None = None
    owner_contact: str | None = None
    builder_name: str | None = None
    floor_plan_url: str | None = None
    video_tour_url: str | None = None
    search_keywords: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return ValidationUtils.sanitize_string(v, max_length=200)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v:
            return ValidationUtils.sanitize_html(v)
        return v

    @field_validator("base_price")
    @classmethod
    def validate_base_price(cls, v: float) -> float:
        return ValidationUtils.validate_price(v, min_price=0, max_price=1e8)

    @field_validator("monthly_rent", "daily_rate", "security_deposit", "maintenance_charges", "price_per_sqft")
    @classmethod
    def validate_positive_price(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValidationException("Price values must be non-negative")
        return v

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str | None) -> str | None:
        if v:
            return ValidationUtils.validate_pincode(v)
        return v

    @field_validator("video_urls", "image_urls")
    @classmethod
    def validate_media_urls(cls, v: list[str] | None) -> list[str] | None:
        if v:
            ValidationUtils.validate_list_input(v, max_items=50)
            cleaned = []
            for url in v:
                if not url:
                    continue
                url_str = str(url).strip()
                if url_str:
                    cleaned.append(url_str[:500])
            return cleaned or None
        return v

    @field_validator("google_street_view_url")
    @classmethod
    def sanitize_street_view_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = str(v).strip()
            return sanitized[:500] if sanitized else None
        return v

    @model_validator(mode="after")
    def validate_coordinates(self):
        if self.latitude is not None and self.longitude is not None:
            ValidationUtils.validate_coordinates(self.latitude, self.longitude)
        _validate_listing_contract(self.property_type, self.purpose)
        return self

    @model_validator(mode="after")
    def validate_rent_price_for_rent_purpose(self):
        """Rent-bearing listings (purpose=rent or PG/flatmate type) must have a
        positive monthly_rent. Prevents zero-rent rows from being created via
        any client path (Flutter, web, AI agent, direct API)."""
        is_rent_listing = (
            self.purpose == PropertyPurpose.rent
            or self.property_type in PG_FLATMATE_TYPES
        )
        if is_rent_listing and (self.monthly_rent is None or self.monthly_rent <= 0):
            raise ValueError(
                "monthly_rent must be a positive number for rent/flatmate/PG listings"
            )
        return self


class PropertyUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        description="Listing title shown in search results and detail pages",
        examples=["2BHK Apartment in Koramangala"],
    )
    description: str | None = None
    property_type: PropertyType | None = None
    purpose: PropertyPurpose | None = None
    base_price: float | None = Field(
        default=None,
        description="Base price (sale price or monthly rent anchor, in INR)",
        examples=[55000],
    )
    status: PropertyStatus | None = Field(
        default=None,
        description="Listing lifecycle status (active, inactive, sold, rented)",
        examples=["active"],
    )
    is_available: bool | None = None
    amenity_ids: list[int] | None = None
    features: list[str] | None = None
    listing_preferences: ListingPreferences | None = None
    calendar_data: dict[str, Any] | None = None
    main_image_url: str | None = None
    image_urls: list[str] | None = None
    virtual_tour_url: str | None = None
    floor_plan_url: str | None = None
    video_tour_url: str | None = None
    video_urls: list[str] | None = None
    google_street_view_url: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            return ValidationUtils.sanitize_string(v, max_length=200)
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v:
            return ValidationUtils.sanitize_html(v)
        return v

    @field_validator("video_urls", "image_urls")
    @classmethod
    def validate_media_urls(cls, v: list[str] | None) -> list[str] | None:
        if v:
            ValidationUtils.validate_list_input(v, max_items=50)
            cleaned = []
            for url in v:
                if not url:
                    continue
                url_str = str(url).strip()
                if url_str:
                    cleaned.append(url_str[:500])
            return cleaned or None
        return v

    @field_validator("google_street_view_url")
    @classmethod
    def sanitize_street_view_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = str(v).strip()
            return sanitized[:500] if sanitized else None
        return v


class PropertyInDB(PropertyBase):
    id: int
    owner_id: int
    status: PropertyStatus
    price_per_sqft: float | None = None
    monthly_rent: float | None = None
    daily_rate: float | None = None
    security_deposit: float | None = None
    maintenance_charges: float | None = None
    floor_number: int | None = None
    total_floors: int | None = None
    age_of_property: int | None = None
    max_occupancy: int | None = None
    minimum_stay_days: int | None = None
    features: list[str] | None = None
    listing_preferences: ListingPreferences | None = None
    main_image_url: str | None = None
    virtual_tour_url: str | None = None
    is_available: bool
    available_from: datetime | None = None
    calendar_data: dict[str, Any] | None = None
    tags: list[str] | None = None
    owner_name: str | None = None
    owner_contact: str | None = None
    builder_name: str | None = None
    floor_plan_url: str | None = None
    video_tour_url: str | None = None
    search_keywords: str | None = None
    view_count: int
    like_count: int
    interest_count: int

    # Property Management
    is_managed: bool = False
    management_status: ManagedPropertyStatus | None = None
    payment_due_day: int | None = None
    grace_period_days: int | None = None
    late_fee_policy: dict[str, Any] | None = None
    current_lease_id: int | None = None
    current_tenant_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("main_image_url", "floor_plan_url", "video_tour_url", "virtual_tour_url", "google_street_view_url", mode="before")
    @classmethod
    def strip_relative_urls(cls, v: object) -> str | None:
        """Blank out relative paths so the app never builds a localhost URL from them."""
        if isinstance(v, str) and v and not ValidationUtils.is_absolute_url(v):
            return None
        return v  # type: ignore[return-value]

    @field_validator("features", mode="before")
    @classmethod
    def coerce_features(cls, v: object) -> list[str] | None:
        if isinstance(v, dict):
            return [k for k in v if isinstance(k, str)]
        return v  # type: ignore[return-value]

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_tags(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(i) for i in v if i is not None]
        return None

    @field_validator("video_urls", mode="before")
    @classmethod
    def coerce_video_urls(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(i) for i in v if i is not None]
        return None

    @field_validator("management_status", mode="before")
    @classmethod
    def coerce_management_status(cls, v: object) -> ManagedPropertyStatus:
        if v is None:
            return ManagedPropertyStatus.active
        return v  # type: ignore[return-value]

    @field_validator("payment_due_day", "grace_period_days", mode="before")
    @classmethod
    def coerce_pm_int_defaults(cls, v: object, info: ValidationInfo) -> int:
        if v is None:
            return 1 if info.field_name == "payment_due_day" else 5
        return v  # type: ignore[return-value]

    @field_validator("calendar_data", "late_fee_policy", mode="before")
    @classmethod
    def coerce_json_dict(cls, v: object) -> dict | None:
        if isinstance(v, dict):
            return v
        return None

    @field_validator(
        "base_price",
        "price_per_sqft",
        "monthly_rent",
        "daily_rate",
        "security_deposit",
        "maintenance_charges",
        mode="before",
    )
    @classmethod
    def coerce_decimal(cls, v: object) -> float | None:
        if v is None:
            return None
        return float(v)  # type: ignore[arg-type]

    model_config = ConfigDict(from_attributes=True)


class Property(PropertyInDB):
    images: list[PropertyImage] | None = None
    amenities: list[PropertyAmenityResponse] | None = Field(None, validation_alias="property_amenities")
    distance_km: float | None = None  # For location-based searches
    liked: bool | None = None  # For swipe history - indicates if user liked this property
    vector_distance: float | None = None  # For semantic similarity scoring
    relevance_score: float | None = None  # Combined text + vector relevance score
    # Auth-aware context populated on detail view when user is logged in
    user_has_scheduled_visit: bool | None = None
    user_scheduled_visit_count: int | None = None
    user_next_visit_date: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PropertyFilter(BaseModel):
    property_type: list[PropertyType] | None = None
    purpose: PropertyPurpose | None = None
    price_min: float | None = None
    price_max: float | None = None
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    city: str | None = None
    locality: str | None = None
    amenity_ids: list[int] | None = None
    gender_preference: ListingGenderPreference | None = None
    sharing_type: ListingSharingType | None = None
    max_distance_km: int | None = 5
    available_from: str | None = None

    # For short stay
    check_in_date: str | None = None
    check_out_date: str | None = None
    guests: int | None = None


class PropertySwipe(BaseModel):
    property_id: int
    is_liked: bool


class PropertyInterest(BaseModel):
    property_id: int
    interest_type: str  # visit, buy, rent, book
    message: str | None = None
    preferred_contact_method: str | None = None


class SortBy(str, Enum):
    distance = "distance"
    price_low = "price_low"
    price_high = "price_high"
    newest = "newest"
    popular = "popular"
    relevance = "relevance"


class UnifiedPropertyFilter(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    radius_km: int = Field(default=5, ge=1, le=100)

    # Text search field
    search_query: str | None = None

    property_ids: list[int] | None = None
    property_type: list[PropertyType] | None = None
    purpose: PropertyPurpose | None = None
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    bedrooms_min: int | None = Field(default=None, ge=0)
    bedrooms_max: int | None = Field(default=None, ge=0)
    bathrooms_min: int | None = Field(default=None, ge=0)
    bathrooms_max: int | None = Field(default=None, ge=0)
    area_min: float | None = Field(default=None, ge=0)
    area_max: float | None = Field(default=None, ge=0)
    parking_spaces_min: int | None = Field(default=None, ge=0)
    floor_number_min: int | None = Field(default=None, ge=0)
    floor_number_max: int | None = Field(default=None, ge=0)
    age_max: int | None = Field(default=None, ge=0)

    city: str | None = None
    locality: str | None = None
    pincode: str | None = None
    amenities: list[str] | None = None
    features: list[str] | None = None
    gender_preference: ListingGenderPreference | None = None
    sharing_type: ListingSharingType | None = None

    available_from: str | None = None
    move_in: str | None = None
    check_in_date: str | None = None
    check_out_date: str | None = None
    guests: int | None = Field(default=None, ge=1, le=20)

    sort_by: SortBy | None = SortBy.distance
    include_unavailable: bool = False
    # Authentication-aware filters
    # When true and user is authenticated, excludes properties the user has already swiped
    exclude_swiped: bool = False
    semantic_search: bool = False

    @model_validator(mode="after")
    def validate_range_consistency(self):
        """Ensure min values do not exceed max values for paired range fields."""
        _RANGE_PAIRS = [
            ("price_min", "price_max"),
            ("bedrooms_min", "bedrooms_max"),
            ("bathrooms_min", "bathrooms_max"),
            ("area_min", "area_max"),
            ("floor_number_min", "floor_number_max"),
        ]
        for min_field, max_field in _RANGE_PAIRS:
            min_val = getattr(self, min_field)
            max_val = getattr(self, max_field)
            if min_val is not None and max_val is not None and min_val > max_val:
                raise ValueError(
                    f"{min_field} ({min_val}) must not exceed {max_field} ({max_val})"
                )
        return self


class UnifiedPropertyResponse(BaseModel):
    properties: list[Property]
    total: int
    page: int
    limit: int
    total_pages: int
    filters_applied: dict[str, Any]
    search_center: dict[str, float] | None = None


