from pydantic import BaseModel, field_validator, ConfigDict, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.enums import (
    ManagedPropertyStatus,
    PropertyType,
    PropertyPurpose,
    PropertyStatus,
    ImageCategory,
)
from app.utils.validators import ValidationUtils
from app.schemas.amenity import PropertyAmenityResponse
from enum import Enum

class PropertyImageBase(BaseModel):
    image_url: str
    caption: Optional[str] = None
    image_category: ImageCategory = ImageCategory.others
    display_order: Optional[int] = None
    is_main_image: bool = False

class PropertyImageCreate(PropertyImageBase):
    pass

class PropertyImage(PropertyImageBase):
    id: int
    property_id: int
    
    model_config = ConfigDict(from_attributes=True)

class PropertyBase(BaseModel):
    title: str
    description: Optional[str] = None
    property_type: PropertyType
    purpose: PropertyPurpose
    base_price: float
    
    # Location fields
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "India"
    pincode: Optional[str] = None
    locality: Optional[str] = None
    sub_locality: Optional[str] = None
    landmark: Optional[str] = None
    full_address: Optional[str] = None
    area_type: Optional[str] = None
    
    area_sqft: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    balconies: Optional[int] = None
    parking_spaces: Optional[int] = None
    video_urls: Optional[List[str]] = None
    google_street_view_url: Optional[str] = None
    floor_plan_url: Optional[str] = None
    video_tour_url: Optional[str] = None

class PropertyCreate(PropertyBase):
    price_per_sqft: Optional[float] = None
    monthly_rent: Optional[float] = None
    daily_rate: Optional[float] = None
    security_deposit: Optional[float] = None
    maintenance_charges: Optional[float] = None
    floor_number: Optional[int] = None
    total_floors: Optional[int] = None
    age_of_property: Optional[int] = None
    max_occupancy: Optional[int] = None
    minimum_stay_days: Optional[int] = 1
    amenity_ids: Optional[List[int]] = None
    features: Optional[List[str]] = None
    main_image_url: Optional[str] = None
    virtual_tour_url: Optional[str] = None
    available_from: Optional[str] = None
    calendar_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    owner_name: Optional[str] = None
    owner_contact: Optional[str] = None
    builder_name: Optional[str] = None
    floor_plan_url: Optional[str] = None
    video_tour_url: Optional[str] = None
    search_keywords: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return ValidationUtils.sanitize_string(v, max_length=200)
    
    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return ValidationUtils.sanitize_html(v)
        return v
    
    @field_validator("base_price")
    @classmethod
    def validate_base_price(cls, v: float) -> float:
        return ValidationUtils.validate_price(v, min_price=0, max_price=1e8)
    
    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return ValidationUtils.validate_pincode(v)
        return v

    @field_validator("video_urls")
    @classmethod
    def validate_media_urls(cls, v: Optional[List[str]]) -> Optional[List[str]]:
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
    def sanitize_street_view_url(cls, v: Optional[str]) -> Optional[str]:
        if v:
            sanitized = str(v).strip()
            return sanitized[:500] if sanitized else None
        return v

    @model_validator(mode="after")
    def validate_coordinates(self):
        if self.latitude is not None and self.longitude is not None:
            ValidationUtils.validate_coordinates(self.latitude, self.longitude)
        return self
    

class PropertyUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    base_price: Optional[float] = None
    status: Optional[PropertyStatus] = None
    is_available: Optional[bool] = None
    amenity_ids: Optional[List[int]] = None
    features: Optional[List[str]] = None
    calendar_data: Optional[Dict[str, Any]] = None
    main_image_url: Optional[str] = None
    virtual_tour_url: Optional[str] = None
    floor_plan_url: Optional[str] = None
    video_tour_url: Optional[str] = None
    video_urls: Optional[List[str]] = None
    google_street_view_url: Optional[str] = None

    @field_validator("video_urls")
    @classmethod
    def validate_media_urls(cls, v: Optional[List[str]]) -> Optional[List[str]]:
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
    def sanitize_street_view_url(cls, v: Optional[str]) -> Optional[str]:
        if v:
            sanitized = str(v).strip()
            return sanitized[:500] if sanitized else None
        return v

class PropertyInDB(PropertyBase):
    id: int
    owner_id: int
    status: PropertyStatus
    price_per_sqft: Optional[float] = None
    monthly_rent: Optional[float] = None
    daily_rate: Optional[float] = None
    security_deposit: Optional[float] = None
    maintenance_charges: Optional[float] = None
    floor_number: Optional[int] = None
    total_floors: Optional[int] = None
    age_of_property: Optional[int] = None
    max_occupancy: Optional[int] = None
    minimum_stay_days: Optional[int] = None
    features: Optional[List[str]] = None
    main_image_url: Optional[str] = None
    virtual_tour_url: Optional[str] = None
    is_available: bool
    available_from: Optional[datetime] = None
    calendar_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    owner_name: Optional[str] = None
    owner_contact: Optional[str] = None
    builder_name: Optional[str] = None
    floor_plan_url: Optional[str] = None
    video_tour_url: Optional[str] = None
    search_keywords: Optional[str] = None
    view_count: int
    like_count: int
    interest_count: int

    # Property Management
    is_managed: bool = False
    management_status: Optional[ManagedPropertyStatus] = None
    payment_due_day: Optional[int] = None
    grace_period_days: Optional[int] = None
    late_fee_policy: Optional[Dict[str, Any]] = None
    current_lease_id: Optional[int] = None
    current_tenant_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class Property(PropertyInDB):
    images: Optional[List[PropertyImage]] = None
    amenities: Optional[List[PropertyAmenityResponse]] = None
    distance_km: Optional[float] = None  # For location-based searches
    liked: Optional[bool] = None  # For swipe history - indicates if user liked this property
    vector_distance: Optional[float] = None  # For semantic similarity scoring
    relevance_score: Optional[float] = None  # Combined text + vector relevance score
    # Auth-aware context populated on detail view when user is logged in
    user_has_scheduled_visit: Optional[bool] = None
    user_scheduled_visit_count: Optional[int] = None
    user_next_visit_date: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class PropertyFilter(BaseModel):
    property_type: Optional[List[PropertyType]] = None
    purpose: Optional[PropertyPurpose] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    bedrooms_max: Optional[int] = None
    area_min: Optional[float] = None
    area_max: Optional[float] = None
    city: Optional[str] = None
    locality: Optional[str] = None
    amenity_ids: Optional[List[int]] = None
    max_distance_km: Optional[int] = 5
    available_from: Optional[str] = None
    
    # For short stay
    check_in_date: Optional[str] = None
    check_out_date: Optional[str] = None
    guests: Optional[int] = None

class PropertySwipe(BaseModel):
    property_id: int
    is_liked: bool

class PropertyInterest(BaseModel):
    property_id: int
    interest_type: str  # visit, buy, rent, book
    message: Optional[str] = None
    preferred_contact_method: Optional[str] = None

class SortBy(str, Enum):
    distance = "distance"
    price_low = "price_low"
    price_high = "price_high"
    newest = "newest"
    popular = "popular"
    relevance = "relevance"

class UnifiedPropertyFilter(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: int = 5
    
    # Text search field
    search_query: Optional[str] = None
    
    property_ids: Optional[List[int]] = None
    property_type: Optional[List[PropertyType]] = None
    purpose: Optional[PropertyPurpose] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    bedrooms_max: Optional[int] = None
    bathrooms_min: Optional[int] = None
    bathrooms_max: Optional[int] = None
    area_min: Optional[float] = None
    area_max: Optional[float] = None
    parking_spaces_min: Optional[int] = None
    floor_number_min: Optional[int] = None
    floor_number_max: Optional[int] = None
    age_max: Optional[int] = None
    
    city: Optional[str] = None
    locality: Optional[str] = None
    pincode: Optional[str] = None
    amenities: Optional[List[str]] = None
    features: Optional[List[str]] = None
    
    available_from: Optional[str] = None
    check_in_date: Optional[str] = None
    check_out_date: Optional[str] = None
    guests: Optional[int] = None
    
    sort_by: Optional[SortBy] = SortBy.distance
    include_unavailable: bool = False
    # Authentication-aware filters
    # When true and user is authenticated, excludes properties the user has already swiped
    exclude_swiped: bool = False
    semantic_search: bool = False

class UnifiedPropertyResponse(BaseModel):
    properties: List[Property]
    total: int
    page: int
    limit: int
    total_pages: int
    filters_applied: Dict[str, Any]
    search_center: Optional[Dict[str, float]] = None

class SwipeHistoryResponse(BaseModel):
    properties: List[Property]
    total: int
    page: int
    limit: int
    total_pages: int
    filters_applied: Dict[str, Any]
    search_center: Optional[Dict[str, float]] = None
