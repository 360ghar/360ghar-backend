from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.functions import ST_AsBinary, ST_GeogFromText
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import (
    ImageCategory,
    ManagedPropertyStatus,
    PropertyPurpose,
    PropertyStatus,
    PropertyType,
    VisitStatus,
)

if TYPE_CHECKING:
    from app.models.agents import Agent
    from app.models.bookings import Booking
    from app.models.pm_documents import Document
    from app.models.pm_finance import Expense, RentCharge
    from app.models.pm_inspections import InspectionChecklist
    from app.models.pm_leases import Lease
    from app.models.pm_maintenance import MaintenanceRequest
    from app.models.users import User, UserSwipe


# GeoAlchemy2's Geography type isn't supported by SQLite (used in tests).
# Compile it as TEXT for the SQLite dialect so Base.metadata.create_all works.
@compiles(Geography, "sqlite")
def _compile_geography_sqlite(_type, _compiler, **_kw):  # noqa: ANN001
    return "TEXT"


@compiles(ST_GeogFromText, "sqlite")
def _compile_st_geog_from_text_sqlite(element, compiler, **kw):  # noqa: ANN001
    clauses = list(element.clauses)
    if not clauses:
        return "NULL"
    return compiler.process(clauses[0], **kw)


@compiles(ST_AsBinary, "sqlite")
def _compile_st_as_binary_sqlite(element, compiler, **kw):  # noqa: ANN001
    clauses = list(element.clauses)
    if not clauses:
        return "NULL"
    return compiler.process(clauses[0], **kw)

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
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    property_type: Mapped[PropertyType] = mapped_column(SQLEnum(PropertyType, name='property_type'), nullable=False)
    purpose: Mapped[PropertyPurpose] = mapped_column(SQLEnum(PropertyPurpose, name='property_purpose'), nullable=False)
    status: Mapped[PropertyStatus] = mapped_column(SQLEnum(PropertyStatus, name='property_status'), default=PropertyStatus.available)

    # Location
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[str | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str] = mapped_column(String, default="India")
    pincode: Mapped[str | None] = mapped_column(String, nullable=True)
    locality: Mapped[str | None] = mapped_column(String, nullable=True)
    sub_locality: Mapped[str | None] = mapped_column(String, nullable=True)
    landmark: Mapped[str | None] = mapped_column(String, nullable=True)
    full_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    area_type: Mapped[str | None] = mapped_column(String, nullable=True)

    # Pricing
    base_price: Mapped[float] = mapped_column(Float, nullable=False)
    price_per_sqft: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_rent: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    security_deposit: Mapped[float | None] = mapped_column(Float, nullable=True)
    maintenance_charges: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Details
    area_sqft: Mapped[float | None] = mapped_column(Float, nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    balconies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking_spaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    floor_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_floors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_of_property: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_occupancy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_stay_days: Mapped[int] = mapped_column(Integer, default=1)

    # Features
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    listing_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    main_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    virtual_tour_url: Mapped[str | None] = mapped_column(String, nullable=True)
    google_street_view_url: Mapped[str | None] = mapped_column(String, nullable=True)
    video_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    floor_plan_url: Mapped[str | None] = mapped_column(String, nullable=True)
    video_tour_url: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    search_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Owner info
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    builder_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Meta
    # Property Management
    is_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    management_status: Mapped[ManagedPropertyStatus] = mapped_column(
        SQLEnum(ManagedPropertyStatus, name="managed_property_status"),
        default=ManagedPropertyStatus.active,
    )
    payment_due_day: Mapped[int] = mapped_column(Integer, default=1)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=5)
    late_fee_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    current_lease_id: Mapped[int | None] = mapped_column(ForeignKey("leases.id"), nullable=True)
    current_tenant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calendar_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    interest_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    owner: Mapped[User] = relationship(
        "User",
        back_populates="owned_properties",
        foreign_keys=[owner_id],
    )
    images: Mapped[list[PropertyImage]] = relationship(back_populates="property", cascade="all, delete-orphan")
    property_amenities: Mapped[list[PropertyAmenity]] = relationship(back_populates="property", cascade="all, delete-orphan")
    swipes: Mapped[list[UserSwipe]] = relationship(
        "UserSwipe",
        back_populates="property",
        foreign_keys="UserSwipe.property_id",
    )
    visits: Mapped[list[Visit]] = relationship(back_populates="property")
    bookings: Mapped[list[Booking]] = relationship(back_populates="property")
    # PM relationships (declared by name to avoid circular imports)
    leases: Mapped[list[Lease]] = relationship(
        "Lease",
        back_populates="property",
        foreign_keys="Lease.property_id",
    )
    maintenance_requests: Mapped[list[MaintenanceRequest]] = relationship(
        "MaintenanceRequest", back_populates="property"
    )
    expenses: Mapped[list[Expense]] = relationship("Expense", back_populates="property")
    rent_charges: Mapped[list[RentCharge]] = relationship("RentCharge", back_populates="property")
    inspection_checklists: Mapped[list[InspectionChecklist]] = relationship(
        "InspectionChecklist", back_populates="property"
    )
    documents: Mapped[list[Document]] = relationship("Document", back_populates="property")

class PropertyImage(Base):
    __tablename__ = "property_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[str | None] = mapped_column(String, nullable=True)
    image_category: Mapped[ImageCategory] = mapped_column(SQLEnum(ImageCategory, name='image_category'), default=ImageCategory.others)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_main_image: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    property: Mapped[Property] = relationship(back_populates="images")

class Amenity(Base):
    __tablename__ = "amenities"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g., "safety", "recreation", "convenience"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    property_amenities: Mapped[list[PropertyAmenity]] = relationship(back_populates="amenity", cascade="all, delete-orphan")

class PropertyAmenity(Base):
    __tablename__ = "property_amenities"
    __table_args__ = (
        Index('idx_property_amenity_unique', 'property_id', 'amenity_id', unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    amenity_id: Mapped[int] = mapped_column(ForeignKey("amenities.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    property: Mapped[Property] = relationship(back_populates="property_amenities")
    amenity: Mapped[Amenity] = relationship(back_populates="property_amenities")

class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    counterparty_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    match_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_matches.id", ondelete="SET NULL"),
        nullable=True,
    )
    visit_context: Mapped[str] = mapped_column(String(32), default="property_tour")
    scheduled_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[VisitStatus] = mapped_column(SQLEnum(VisitStatus, name='visit_status'), default=VisitStatus.scheduled)
    special_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    visit_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitor_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_level: Mapped[str | None] = mapped_column(String, nullable=True)
    follow_up_required: Mapped[bool] = mapped_column(Boolean, default=False)
    follow_up_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rescheduled_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    user: Mapped[User] = relationship(back_populates="visits", foreign_keys=[user_id])
    counterparty_user: Mapped[User | None] = relationship(foreign_keys=[counterparty_user_id])
    property: Mapped[Property] = relationship(back_populates="visits")
    agent: Mapped[Agent | None] = relationship(back_populates="visits")
