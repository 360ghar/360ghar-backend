from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.property import PropertyType, PropertyPurpose, PropertyStatus
from app.utils.validators import ValidationUtils

class PropertyImageBase(BaseModel):
    image_url: str
    caption: Optional[str] = None
    display_order: int = 0
    is_main_image: bool = False

class PropertyImageCreate(PropertyImageBase):
    pass

class PropertyImage(PropertyImageBase):
    id: int
    property_id: int
    
    class Config:
        from_attributes = True

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
    amenities: Optional[List[str]] = None
    features: Optional[Dict[str, Any]] = None
    main_image_url: Optional[str] = None
    virtual_tour_url: Optional[str] = None
    available_from: Optional[str] = None
    calendar_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    owner_name: Optional[str] = None
    owner_contact: Optional[str] = None
    builder_name: Optional[str] = None

    @validator('title')
    def validate_title(cls, v):
        return ValidationUtils.sanitize_string(v, max_length=200)
    
    @validator('description')
    def validate_description(cls, v):
        if v:
            return ValidationUtils.sanitize_html(v)
        return v
    
    @validator('base_price')
    def validate_base_price(cls, v):
        return ValidationUtils.validate_price(v, min_price=0, max_price=1e8)
    
    @validator('longitude')
    def validate_coordinates(cls, v, values):
        if v is not None and 'latitude' in values and values['latitude'] is not None:
            ValidationUtils.validate_coordinates(values['latitude'], v)
        return v
    
    @validator('pincode')
    def validate_pincode(cls, v):
        if v:
            return ValidationUtils.validate_pincode(v)
        return v
    
    @validator('amenities')
    def validate_amenities(cls, v):
        if v:
            allowed_amenities = [
                'parking', 'gym', 'pool', 'security', 'elevator',
                'garden', 'powerbackup', 'clubhouse', 'playground'
            ]
            return ValidationUtils.validate_list_input(
                v, max_items=20, allowed_values=allowed_amenities
            )
        return v

class PropertyUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    base_price: Optional[float] = None
    status: Optional[PropertyStatus] = None
    is_available: Optional[bool] = None
    amenities: Optional[List[str]] = None
    features: Optional[Dict[str, Any]] = None
    calendar_data: Optional[Dict[str, Any]] = None

class PropertyInDB(PropertyBase):
    id: int
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
    amenities: Optional[List[str]] = None
    features: Optional[Dict[str, Any]] = None
    main_image_url: Optional[str] = None
    virtual_tour_url: Optional[str] = None
    is_available: bool
    available_from: Optional[str] = None
    calendar_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    owner_name: Optional[str] = None
    owner_contact: Optional[str] = None
    builder_name: Optional[str] = None
    view_count: int
    like_count: int
    interest_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class Property(PropertyInDB):
    images: Optional[List[PropertyImage]] = None
    distance_km: Optional[float] = None  # For location-based searches

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
    amenities: Optional[List[str]] = None
    max_distance_km: Optional[int] = 5
    available_from: Optional[str] = None
    
    # For short stay
    check_in_date: Optional[str] = None
    check_out_date: Optional[str] = None
    guests: Optional[int] = None

class PropertySwipe(BaseModel):
    property_id: int
    is_liked: bool
    user_location_lat: Optional[str] = None
    user_location_lng: Optional[str] = None
    session_id: Optional[str] = None

class PropertyInterest(BaseModel):
    property_id: int
    interest_type: str  # visit, buy, rent, book
    message: Optional[str] = None
    preferred_contact_method: Optional[str] = None

class UnifiedPropertyFilter(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: int = 5
    
    # Text search field
    search_query: Optional[str] = None
    
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
    
    sort_by: Optional[str] = "distance"  # distance, price_low, price_high, newest, popular, relevance
    include_unavailable: bool = False

class UnifiedPropertyResponse(BaseModel):
    properties: List[Property]
    total: int
    page: int
    limit: int
    total_pages: int
    filters_applied: Dict[str, Any]
    search_center: Optional[Dict[str, float]] = None