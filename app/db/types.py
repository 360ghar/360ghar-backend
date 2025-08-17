"""
Type definitions for database responses using TypedDict for better type safety
"""
from typing import TypedDict, Optional, List, Any, Union
from datetime import datetime
from enum import Enum

# Enum types matching database
class PropertyType(str, Enum):
    HOUSE = "house"
    APARTMENT = "apartment"
    BUILDER_FLOOR = "builder_floor"
    ROOM = "room"

class PropertyPurpose(str, Enum):
    BUY = "buy"
    RENT = "rent"
    SHORT_STAY = "short_stay"

class PropertyStatus(str, Enum):
    AVAILABLE = "available"
    SOLD = "sold"
    RENTED = "rented"
    UNDER_OFFER = "under_offer"
    MAINTENANCE = "maintenance"

class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    REFUNDED = "refunded"
    FAILED = "failed"

class VisitStatus(str, Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"

class AgentType(str, Enum):
    GENERAL = "general"
    SPECIALIST = "specialist"
    SENIOR = "senior"

class ExperienceLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"

class ResponseStyle(str, Enum):
    FORMAL = "formal"
    CONVERSATIONAL = "conversational"
    CASUAL = "casual"

# Database response types
class UserDB(TypedDict, total=False):
    id: int
    supabase_user_id: str
    email: str
    phone: Optional[str]
    full_name: Optional[str]
    date_of_birth: Optional[str]
    profile_image_url: Optional[str]
    is_active: bool
    is_verified: bool
    preferences: Optional[dict]
    current_latitude: Optional[float]
    current_longitude: Optional[float]
    preferred_locations: Optional[List[dict]]
    notification_settings: Optional[dict]
    privacy_settings: Optional[dict]
    agent_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    # Relations
    agent: Optional['AgentDB']

class PropertyDB(TypedDict, total=False):
    id: int
    title: str
    description: Optional[str]
    property_type: PropertyType
    purpose: PropertyPurpose
    status: PropertyStatus
    latitude: Optional[float]
    longitude: Optional[float]
    city: Optional[str]
    state: Optional[str]
    country: str
    pincode: Optional[str]
    locality: Optional[str]
    sub_locality: Optional[str]
    landmark: Optional[str]
    full_address: Optional[str]
    area_type: Optional[str]
    base_price: float
    price_per_sqft: Optional[float]
    monthly_rent: Optional[float]
    daily_rate: Optional[float]
    security_deposit: Optional[float]
    maintenance_charges: Optional[float]
    area_sqft: Optional[float]
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    balconies: Optional[int]
    parking_spaces: Optional[int]
    floor_number: Optional[int]
    total_floors: Optional[int]
    age_of_property: Optional[int]
    max_occupancy: Optional[int]
    minimum_stay_days: int
    amenities: Optional[List[str]]
    features: Optional[dict]
    main_image_url: Optional[str]
    virtual_tour_url: Optional[str]
    is_available: bool
    available_from: Optional[str]
    calendar_data: Optional[dict]
    tags: Optional[List[str]]
    search_keywords: Optional[str]
    owner_name: Optional[str]
    owner_contact: Optional[str]
    builder_name: Optional[str]
    view_count: int
    like_count: int
    interest_count: int
    created_at: datetime
    updated_at: Optional[datetime]
    # Computed fields
    distance_km: Optional[float]
    images: Optional[List['PropertyImageDB']]

class PropertyImageDB(TypedDict, total=False):
    id: int
    property_id: int
    image_url: str
    caption: Optional[str]
    display_order: int
    is_main_image: bool
    created_at: datetime
    updated_at: Optional[datetime]

class UserSwipeDB(TypedDict, total=False):
    id: int
    user_id: int
    property_id: int
    is_liked: bool
    swipe_timestamp: datetime
    user_location_lat: Optional[float]
    user_location_lng: Optional[float]
    session_id: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    # Relations
    user: Optional[UserDB]
    property: Optional[PropertyDB]

class UserFavoriteDB(TypedDict, total=False):
    id: int
    user_id: int
    property_id: int
    is_favorite: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    # Relations
    user: Optional[UserDB]
    property: Optional[PropertyDB]

class UserSearchHistoryDB(TypedDict, total=False):
    id: int
    user_id: int
    search_query: Optional[str]
    search_filters: Optional[dict]
    search_location: Optional[str]
    search_radius: Optional[int]
    results_count: Optional[int]
    user_location_lat: Optional[float]
    user_location_lng: Optional[float]
    search_type: Optional[str]
    session_id: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

class VisitDB(TypedDict, total=False):
    id: int
    user_id: int
    property_id: int
    agent_id: Optional[int]
    scheduled_date: datetime
    actual_date: Optional[datetime]
    status: VisitStatus
    special_requirements: Optional[str]
    visit_notes: Optional[str]
    visitor_feedback: Optional[str]
    interest_level: Optional[str]
    follow_up_required: bool
    follow_up_date: Optional[datetime]
    cancellation_reason: Optional[str]
    rescheduled_from: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    # Relations
    user: Optional[UserDB]
    property: Optional[PropertyDB]
    agent: Optional['AgentDB']

class AgentDB(TypedDict, total=False):
    id: int
    name: str
    agent_code: str
    description: Optional[str]
    avatar_url: Optional[str]
    personality_traits: Optional[dict]
    specializations: Optional[List[str]]
    languages: Optional[List[str]]
    agent_type: AgentType
    experience_level: ExperienceLevel
    max_concurrent_users: int
    ai_model: str
    system_prompt: Optional[str]
    response_style: ResponseStyle
    is_active: bool
    is_available: bool
    working_hours: Optional[dict]
    total_users_assigned: int
    total_interactions: int
    average_response_time_seconds: int
    user_satisfaction_rating: float
    created_at: datetime
    updated_at: Optional[datetime]
    last_active_at: Optional[datetime]

class BookingDB(TypedDict, total=False):
    id: int
    user_id: int
    property_id: int
    booking_reference: str
    check_in_date: datetime
    check_out_date: datetime
    nights: int
    guests: int
    base_amount: float
    taxes_amount: float
    service_charges: float
    discount_amount: float
    total_amount: float
    booking_status: BookingStatus
    payment_status: PaymentStatus
    primary_guest_name: str
    primary_guest_phone: str
    primary_guest_email: str
    guest_details: Optional[dict]
    special_requests: Optional[str]
    internal_notes: Optional[str]
    actual_check_in: Optional[datetime]
    actual_check_out: Optional[datetime]
    early_check_in: bool
    late_check_out: bool
    cancellation_date: Optional[datetime]
    cancellation_reason: Optional[str]
    refund_amount: Optional[float]
    payment_method: Optional[str]
    transaction_id: Optional[str]
    payment_date: Optional[datetime]
    guest_rating: Optional[int]
    guest_review: Optional[str]
    host_rating: Optional[int]
    host_review: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    # Relations
    user: Optional[UserDB]
    property: Optional[PropertyDB]

# Response types for API
class PaginatedResponse(TypedDict):
    items: List[Any]
    total: int
    page: int
    limit: int
    total_pages: int