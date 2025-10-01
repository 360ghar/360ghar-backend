from sqlalchemy import Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Text, Index
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Enum as SQLEnum
from typing import Optional, List
from datetime import datetime
from app.core.database import Base
from app.models.enums import (
    PropertyType, PropertyPurpose, PropertyStatus, BookingStatus, PaymentStatus,
    VisitStatus, AgentType, ExperienceLevel, BugType, BugSeverity, BugStatus, PageFormat, ImageCategory
)
from geoalchemy2 import Geography

class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        Index('idx_property_filters', 'property_type', 'purpose', 'is_available'),
        Index('idx_property_price', 'base_price'),
        # PostGIS and FTS indexes are created by migrations:
        # - supabase/migrations/20250818081100_add_geography_to_properties.sql
        # - supabase/migrations/20250818081200_add_full_text_search_to_properties.sql
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    __ts_vector__: Mapped[str] = mapped_column(TSVECTOR, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    property_type: Mapped[PropertyType] = mapped_column(SQLEnum(PropertyType, name='property_type'), nullable=False)
    purpose: Mapped[PropertyPurpose] = mapped_column(SQLEnum(PropertyPurpose, name='property_purpose'), nullable=False)
    status: Mapped[PropertyStatus] = mapped_column(SQLEnum(PropertyStatus, name='property_status'), default=PropertyStatus.available)

    # Location
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(Geography(geometry_type='POINT', srid=4326), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    country: Mapped[str] = mapped_column(String, default="India")
    pincode: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    locality: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sub_locality: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    landmark: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    full_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    area_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Pricing
    base_price: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_sqft: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    monthly_rent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    security_deposit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    maintenance_charges: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Details
    area_sqft: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bedrooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    balconies: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parking_spaces: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    floor_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_floors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    age_of_property: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_occupancy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_stay_days: Mapped[int] = mapped_column(Integer, default=1)

    # Features
    features: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    main_image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    virtual_tour_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    floor_plan_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    video_tour_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    search_keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Owner info
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    owner_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    owner_contact: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    builder_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Meta
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    available_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    calendar_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    interest_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="owned_properties")
    images: Mapped[List["PropertyImage"]] = relationship(back_populates="property", cascade="all, delete-orphan")
    property_amenities: Mapped[List["PropertyAmenity"]] = relationship(back_populates="property", cascade="all, delete-orphan")
    swipes: Mapped[List["UserSwipe"]] = relationship(back_populates="property")
    visits: Mapped[List["Visit"]] = relationship(back_populates="property")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="property")

class PropertyImage(Base):
    __tablename__ = "property_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    image_category: Mapped[ImageCategory] = mapped_column(SQLEnum(ImageCategory, name='image_category'), default=ImageCategory.others)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_main_image: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    property: Mapped["Property"] = relationship(back_populates="images")

class Amenity(Base):
    __tablename__ = "amenities"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    icon: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # e.g., "safety", "recreation", "convenience"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationships
    property_amenities: Mapped[List["PropertyAmenity"]] = relationship(back_populates="amenity", cascade="all, delete-orphan")

class PropertyAmenity(Base):
    __tablename__ = "property_amenities"
    __table_args__ = (
        Index('idx_property_amenity_unique', 'property_id', 'amenity_id', unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    amenity_id: Mapped[int] = mapped_column(ForeignKey("amenities.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    property: Mapped["Property"] = relationship(back_populates="property_amenities")
    amenity: Mapped["Amenity"] = relationship(back_populates="property_amenities")

class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id"), nullable=True)
    scheduled_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actual_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[VisitStatus] = mapped_column(SQLEnum(VisitStatus, name='visit_status'), default=VisitStatus.scheduled)
    special_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visit_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visitor_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    interest_level: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    follow_up_required: Mapped[bool] = mapped_column(Boolean, default=False)
    follow_up_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rescheduled_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    user: Mapped["User"] = relationship(back_populates="visits")
    property: Mapped["Property"] = relationship(back_populates="visits")
    agent: Mapped[Optional["Agent"]] = relationship(back_populates="visits")