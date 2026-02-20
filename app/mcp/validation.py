"""
Input validation schemas for MCP tools.

Provides Pydantic models for validating MCP tool inputs.
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class PropertySearchInput(BaseModel):
    """Input validation for property search tool."""
    
    search_query: Optional[str] = Field(None, max_length=500)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius_km: int = Field(5, ge=0, le=50)
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    include_unavailable: bool = False
    
    @field_validator('latitude')
    @classmethod
    def validate_latitude(cls, v, info):
        """Ensure latitude and longitude are both provided or both None."""
        if v is not None and info.data.get('longitude') is None:
            raise ValueError('longitude must be provided when latitude is specified')
        return v
    
    @field_validator('longitude')
    @classmethod
    def validate_longitude(cls, v, info):
        """Ensure latitude and longitude are both provided or both None."""
        if v is not None and info.data.get('latitude') is None:
            raise ValueError('latitude must be provided when longitude is specified')
        return v


class PropertyGetInput(BaseModel):
    """Input validation for get property tool."""
    
    property_id: int = Field(..., ge=1)


class SwipeInput(BaseModel):
    """Input validation for swipe tools."""
    
    property_id: int = Field(..., ge=1)


class ShortlistListInput(BaseModel):
    """Input validation for shortlist listing."""
    
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)


class VisitScheduleInput(BaseModel):
    """Input validation for visit scheduling."""
    
    property_id: int = Field(..., ge=1)
    scheduled_date_iso: str = Field(..., description="ISO-8601 formatted datetime")
    special_requirements: Optional[str] = Field(None, max_length=1000)
    
    @field_validator('scheduled_date_iso')
    @classmethod
    def validate_datetime(cls, v):
        """Validate ISO-8601 datetime format."""
        try:
            dt = datetime.fromisoformat(v)
            # Ensure date is in the future
            if dt <= datetime.now():
                raise ValueError('scheduled_date must be in the future')
            return v
        except ValueError as e:
            if 'future' in str(e):
                raise e
            raise ValueError('scheduled_date_iso must be valid ISO-8601 format')


class VisitCancelInput(BaseModel):
    """Input validation for visit cancellation."""
    
    visit_id: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=500)


class DiscoveryFeedInput(BaseModel):
    """Input validation for discovery feed."""
    
    limit: int = Field(20, ge=1, le=50)


class PropertySearchAdvancedInput(PropertySearchInput):
    """Extended property search with additional filters."""
    
    min_price: Optional[float] = Field(None, ge=0)
    max_price: Optional[float] = Field(None, ge=0)
    property_type: Optional[str] = None
    bedrooms: Optional[int] = Field(None, ge=0)
    bathrooms: Optional[int] = Field(None, ge=0)
    amenities: Optional[List[int]] = Field(None, description="List of amenity IDs")
    listing_type: Optional[str] = Field(None, description="rent, sale, or short_stay")
    
    @field_validator('max_price')
    @classmethod
    def validate_price_range(cls, v, info):
        """Ensure max_price >= min_price if both provided."""
        min_price = info.data.get('min_price')
        if v is not None and min_price is not None and v < min_price:
            raise ValueError('max_price must be greater than or equal to min_price')
        return v
    
    @field_validator('property_type')
    @classmethod
    def validate_property_type(cls, v):
        """Validate property type enum."""
        valid_types = ['apartment', 'villa', 'house', 'office', 'shop', 'land', 'other']
        if v is not None and v.lower() not in valid_types:
            raise ValueError(f'property_type must be one of: {", ".join(valid_types)}')
        return v.lower() if v else None
    
    @field_validator('listing_type')
    @classmethod
    def validate_listing_type(cls, v):
        """Validate listing type enum."""
        valid_types = ['rent', 'sale', 'short_stay']
        if v is not None and v.lower() not in valid_types:
            raise ValueError(f'listing_type must be one of: {", ".join(valid_types)}')
        return v.lower() if v else None


# ============================================================================
# User Profile Validation
# ============================================================================


class UserPreferencesInput(BaseModel):
    """Input validation for user preferences update."""
    
    preferred_locations: Optional[List[str]] = Field(None, description="Preferred city/locality names")
    preferred_property_types: Optional[List[str]] = Field(None, description="Preferred property types")
    preferred_purpose: Optional[str] = Field(None, description="buy, rent, or short_stay")
    price_range_min: Optional[float] = Field(None, ge=0)
    price_range_max: Optional[float] = Field(None, ge=0)
    bedrooms_min: Optional[int] = Field(None, ge=0, le=10)
    bedrooms_max: Optional[int] = Field(None, ge=0, le=10)
    
    @field_validator('price_range_max')
    @classmethod
    def validate_price_range(cls, v, info):
        """Ensure price_range_max >= price_range_min if both provided."""
        min_price = info.data.get('price_range_min')
        if v is not None and min_price is not None and v < min_price:
            raise ValueError('price_range_max must be >= price_range_min')
        return v


# ============================================================================
# Blog Validation
# ============================================================================


class BlogSearchInput(BaseModel):
    """Input validation for blog search."""
    
    query: Optional[str] = Field(None, max_length=200)
    categories: Optional[List[str]] = Field(None, max_length=10)
    tags: Optional[List[str]] = Field(None, max_length=20)
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=50)


class BlogGetInput(BaseModel):
    """Input validation for blog get."""
    
    identifier: str = Field(..., min_length=1, max_length=200, description="Blog post ID or slug")


# ============================================================================
# Auth Validation
# ============================================================================


class RefreshTokenInput(BaseModel):
    """Input validation for token refresh."""

    refresh_token: str = Field(..., min_length=20, description="OAuth refresh token")


# ============================================================================
# Property Management Validation (Owner Tools)
# ============================================================================


class OwnerPropertyCreateInput(BaseModel):
    """Input validation for owner property creation."""

    title: str = Field(..., min_length=5, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    property_type: str = Field(..., description="house, apartment, builder_floor, room")
    purpose: str = Field(..., description="buy, rent, short_stay")

    # Location
    full_address: str = Field(..., min_length=10, max_length=500)
    city: str = Field(..., min_length=2, max_length=100)
    locality: str = Field(..., min_length=2, max_length=100)
    sub_locality: Optional[str] = Field(None, max_length=100)
    pincode: Optional[str] = Field(None, pattern=r"^\d{6}$")
    state: Optional[str] = Field(None, max_length=100)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    # Pricing
    base_price: float = Field(..., ge=0)
    monthly_rent: Optional[float] = Field(None, ge=0)
    daily_rate: Optional[float] = Field(None, ge=0)
    security_deposit: Optional[float] = Field(None, ge=0)
    maintenance_charges: Optional[float] = Field(None, ge=0)

    # Property specs
    area_sqft: Optional[float] = Field(None, ge=0)
    bedrooms: Optional[int] = Field(None, ge=0, le=20)
    bathrooms: Optional[int] = Field(None, ge=0, le=20)
    balconies: Optional[int] = Field(None, ge=0, le=10)
    parking_spaces: Optional[int] = Field(None, ge=0, le=10)
    floor_number: Optional[int] = Field(None, ge=-5, le=100)
    total_floors: Optional[int] = Field(None, ge=1, le=100)

    # For short-stay
    max_occupancy: Optional[int] = Field(None, ge=1, le=50)
    minimum_stay_days: Optional[int] = Field(None, ge=1, le=365)

    # Media
    main_image_url: Optional[str] = Field(None, max_length=500)
    virtual_tour_url: Optional[str] = Field(None, max_length=500)

    # Amenities
    amenity_ids: Optional[List[int]] = Field(None, description="List of amenity IDs")

    @field_validator('property_type')
    @classmethod
    def validate_property_type(cls, v):
        valid = ['house', 'apartment', 'builder_floor', 'room']
        if v.lower() not in valid:
            raise ValueError(f'property_type must be one of: {", ".join(valid)}')
        return v.lower()

    @field_validator('purpose')
    @classmethod
    def validate_purpose(cls, v):
        valid = ['buy', 'rent', 'short_stay']
        if v.lower() not in valid:
            raise ValueError(f'purpose must be one of: {", ".join(valid)}')
        return v.lower()


class OwnerPropertyUpdateInput(BaseModel):
    """Input validation for owner property update."""

    property_id: int = Field(..., ge=1)

    # All fields optional for partial update
    title: Optional[str] = Field(None, min_length=5, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)

    # Pricing updates
    base_price: Optional[float] = Field(None, ge=0)
    monthly_rent: Optional[float] = Field(None, ge=0)
    daily_rate: Optional[float] = Field(None, ge=0)
    security_deposit: Optional[float] = Field(None, ge=0)

    # Availability
    is_available: Optional[bool] = None
    available_from: Optional[str] = Field(None, description="ISO-8601 date")

    # Specs updates
    bedrooms: Optional[int] = Field(None, ge=0, le=20)
    bathrooms: Optional[int] = Field(None, ge=0, le=20)
    max_occupancy: Optional[int] = Field(None, ge=1, le=50)

    # Media
    main_image_url: Optional[str] = Field(None, max_length=500)
    virtual_tour_url: Optional[str] = Field(None, max_length=500)

    @field_validator('available_from')
    @classmethod
    def validate_available_from(cls, v):
        if v is not None:
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError('available_from must be valid ISO-8601 format')
        return v


class OwnerPropertyListInput(BaseModel):
    """Input validation for owner property listing."""

    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    occupancy: Optional[str] = Field(None, description="occupied or vacant")
    q: Optional[str] = Field(None, max_length=200, description="Search query")

    @field_validator('occupancy')
    @classmethod
    def validate_occupancy(cls, v):
        if v is not None and v.lower() not in ['occupied', 'vacant']:
            raise ValueError('occupancy must be one of: occupied, vacant')
        return v.lower() if v else None


# ============================================================================
# Booking Management Validation
# ============================================================================


class BookingCreateInput(BaseModel):
    """Input validation for booking creation."""

    property_id: int = Field(..., ge=1)
    check_in_date: str = Field(..., description="ISO-8601 date")
    check_out_date: str = Field(..., description="ISO-8601 date")
    guests: int = Field(1, ge=1, le=50)
    special_requests: Optional[str] = Field(None, max_length=1000)

    @field_validator('check_in_date', 'check_out_date')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError('Date must be valid ISO-8601 format')

    @field_validator('check_out_date')
    @classmethod
    def validate_checkout_after_checkin(cls, v, info):
        check_in = info.data.get('check_in_date')
        if check_in and v:
            try:
                ci = datetime.fromisoformat(check_in)
                co = datetime.fromisoformat(v)
                if co <= ci:
                    raise ValueError('check_out_date must be after check_in_date')
            except (TypeError, ValueError):
                pass
        return v


class BookingListInput(BaseModel):
    """Input validation for booking listing."""

    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    status: Optional[str] = Field(None, description="pending, confirmed, cancelled, completed")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid = ['pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed']
        if v is not None and v.lower() not in valid:
            raise ValueError(f'status must be one of: {", ".join(valid)}')
        return v.lower() if v else None


class BookingCancelInput(BaseModel):
    """Input validation for booking cancellation."""

    booking_id: int = Field(..., ge=1)
    reason: str = Field(..., min_length=5, max_length=500)


class BookingUpdateStatusInput(BaseModel):
    """Input validation for booking status update (admin)."""

    booking_id: int = Field(..., ge=1)
    status: str = Field(..., description="confirmed, checked_in, checked_out, cancelled, completed")
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid = ['confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed']
        if v.lower() not in valid:
            raise ValueError(f'status must be one of: {", ".join(valid)}')
        return v.lower()


# ============================================================================
# Tenant Tools Validation
# ============================================================================


class MaintenanceCreateInput(BaseModel):
    """Input validation for maintenance request creation."""

    property_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10, max_length=2000)
    category: str = Field(..., description="plumbing, electrical, hvac, appliance, structural, other")
    priority: str = Field("medium", description="low, medium, high, urgent")

    @field_validator('category')
    @classmethod
    def validate_category(cls, v):
        valid = ['plumbing', 'electrical', 'hvac', 'appliance', 'structural', 'pest_control', 'cleaning', 'other']
        if v.lower() not in valid:
            raise ValueError(f'category must be one of: {", ".join(valid)}')
        return v.lower()

    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v):
        valid = ['low', 'medium', 'high', 'urgent']
        if v.lower() not in valid:
            raise ValueError(f'priority must be one of: {", ".join(valid)}')
        return v.lower()


class MaintenanceListInput(BaseModel):
    """Input validation for maintenance request listing."""

    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    status: Optional[str] = Field(None, description="open, in_progress, completed, cancelled")
    property_id: Optional[int] = Field(None, ge=1)

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid = ['open', 'in_progress', 'scheduled', 'completed', 'cancelled']
        if v is not None and v.lower() not in valid:
            raise ValueError(f'status must be one of: {", ".join(valid)}')
        return v.lower() if v else None


class MaintenanceUpdateStatusInput(BaseModel):
    """Input validation for maintenance status update (admin/agent)."""

    request_id: int = Field(..., ge=1)
    status: str = Field(..., description="in_progress, scheduled, completed, cancelled")
    notes: Optional[str] = Field(None, max_length=1000)
    scheduled_date: Optional[str] = Field(None, description="ISO-8601 date for scheduling")
    vendor_name: Optional[str] = Field(None, max_length=200)
    vendor_contact: Optional[str] = Field(None, max_length=100)
    estimated_cost: Optional[float] = Field(None, ge=0)
    actual_cost: Optional[float] = Field(None, ge=0)

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid = ['open', 'in_progress', 'scheduled', 'completed', 'cancelled']
        if v.lower() not in valid:
            raise ValueError(f'status must be one of: {", ".join(valid)}')
        return v.lower()


# ============================================================================
# Lease Management Validation (Agent/Admin)
# ============================================================================


class LeaseCreateInput(BaseModel):
    """Input validation for lease creation."""

    property_id: int = Field(..., ge=1)
    tenant_user_id: int = Field(..., ge=1)
    start_date: str = Field(..., description="ISO-8601 date")
    end_date: str = Field(..., description="ISO-8601 date")
    monthly_rent: float = Field(..., ge=0)
    security_deposit: float = Field(..., ge=0)
    payment_due_day: int = Field(1, ge=1, le=28)
    grace_period_days: int = Field(5, ge=0, le=30)
    terms: Optional[str] = Field(None, max_length=5000)
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError('Date must be valid ISO-8601 format')

    @field_validator('end_date')
    @classmethod
    def validate_end_after_start(cls, v, info):
        start = info.data.get('start_date')
        if start and v:
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(v)
                if e <= s:
                    raise ValueError('end_date must be after start_date')
            except (TypeError, ValueError):
                pass
        return v


class LeaseListInput(BaseModel):
    """Input validation for lease listing."""

    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    status: Optional[str] = Field(None, description="active, expired, terminated")
    property_id: Optional[int] = Field(None, ge=1)
    owner_id: Optional[int] = Field(None, ge=1)

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid = ['draft', 'active', 'expired', 'terminated', 'renewed']
        if v is not None and v.lower() not in valid:
            raise ValueError(f'status must be one of: {", ".join(valid)}')
        return v.lower() if v else None


class LeaseTerminateInput(BaseModel):
    """Input validation for lease termination."""

    lease_id: int = Field(..., ge=1)
    reason: str = Field(..., min_length=10, max_length=1000)
    termination_date: Optional[str] = Field(None, description="ISO-8601 date, defaults to today")

    @field_validator('termination_date')
    @classmethod
    def validate_date(cls, v):
        if v is not None:
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError('termination_date must be valid ISO-8601 format')
        return v


# ============================================================================
# Rent Collection Validation (Agent/Admin)
# ============================================================================


class RentPaymentRecordInput(BaseModel):
    """Input validation for recording rent payment."""

    lease_id: int = Field(..., ge=1)
    amount: float = Field(..., ge=0)
    payment_date: str = Field(..., description="ISO-8601 date")
    payment_method: str = Field(..., description="cash, bank_transfer, upi, cheque, online")
    transaction_reference: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator('payment_date')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError('payment_date must be valid ISO-8601 format')

    @field_validator('payment_method')
    @classmethod
    def validate_method(cls, v):
        valid = ['cash', 'bank_transfer', 'upi', 'cheque', 'online', 'other']
        if v.lower() not in valid:
            raise ValueError(f'payment_method must be one of: {", ".join(valid)}')
        return v.lower()


class RentDueListInput(BaseModel):
    """Input validation for listing due rent."""

    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    overdue_only: bool = Field(False, description="Only show overdue payments")
    owner_id: Optional[int] = Field(None, ge=1)
    property_id: Optional[int] = Field(None, ge=1)


# ============================================================================
# Agent/Admin Property Management Validation
# ============================================================================


class AgentPropertyListInput(BaseModel):
    """Input validation for agent property listing."""

    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=100)
    owner_id: Optional[int] = Field(None, ge=1)
    occupancy: Optional[str] = Field(None, description="occupied or vacant")
    q: Optional[str] = Field(None, max_length=200)

    @field_validator('occupancy')
    @classmethod
    def validate_occupancy(cls, v):
        if v is not None and v.lower() not in ['occupied', 'vacant']:
            raise ValueError('occupancy must be one of: occupied, vacant')
        return v.lower() if v else None


class AgentPropertyVerifyInput(BaseModel):
    """Input validation for property verification."""

    property_id: int = Field(..., ge=1)
    is_verified: bool = Field(..., description="Verification status")
    verification_notes: Optional[str] = Field(None, max_length=1000)


class DashboardInput(BaseModel):
    """Input validation for dashboard overview."""

    owner_id: Optional[int] = Field(None, ge=1, description="Filter by owner (agents only)")
    period: str = Field("month", description="day, week, month, year")

    @field_validator('period')
    @classmethod
    def validate_period(cls, v):
        valid = ['day', 'week', 'month', 'quarter', 'year']
        if v.lower() not in valid:
            raise ValueError(f'period must be one of: {", ".join(valid)}')
        return v.lower()
