from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import AuctionSource, ComplaintNature, GazetteType, ScraperStatus

if TYPE_CHECKING:
    from app.models.properties import Property
    from app.models.users import User


class CircleRate(Base):
    __tablename__ = "circle_rates"
    __table_args__ = (UniqueConstraint('sector', 'colony', 'property_type', 'revision_year', name='uq_circle_rates_key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, default="Gurugram")
    tehsil: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sector: Mapped[str] = mapped_column(String(200), nullable=False)
    colony: Mapped[str | None] = mapped_column(String(200), nullable=True)
    property_type: Mapped[str] = mapped_column(String(50), nullable=False)  # residential, commercial, plot, industrial
    rate_per_sqyd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rate_per_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rate_per_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    revision_year: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class ReraProject(Base):
    __tablename__ = "rera_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_number: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    project_name: Mapped[str] = mapped_column(String(500), nullable=False)
    developer_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    developer_slug: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, default="Gurugram")
    total_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_booked: Mapped[int | None] = mapped_column(Integer, nullable=True)
    possession_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)  # registered, lapsed, revoked, completed
    project_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    complaint_count: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class BankAuction(Base):
    __tablename__ = "bank_auctions"
    __table_args__ = (UniqueConstraint('bank_name', 'normalized_address_hash', 'auction_date', name='uq_bank_auctions_key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[AuctionSource] = mapped_column(SQLEnum(AuctionSource, name='auction_source'), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(200), nullable=False)
    property_description: Mapped[str] = mapped_column(Text, nullable=False)
    property_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    area_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="Delhi NCR")
    locality: Mapped[str | None] = mapped_column(String(300), nullable=True)
    full_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserve_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    emd_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    auction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    auction_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    possession_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # physical, symbolic
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    normalized_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class AuctionAlert(Base):
    __tablename__ = "auction_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="Delhi NCR")
    property_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    keyword: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_channels: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=lambda: ["email"])
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])


class BankRate(Base):
    __tablename__ = "bank_rates"
    __table_args__ = (UniqueConstraint('bank_name', 'rate_type', 'effective_date', name='uq_bank_rates_key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(50), nullable=False)  # repo, mclr_1y, home_loan_min, etc.
    rate_value: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class JamabandiCache(Base):
    """Cached Jamabandi land records. No updated_at — rows are replaced, not updated."""
    __tablename__ = "jamabandi_cache"
    __table_args__ = (UniqueConstraint('tehsil', 'village', 'khasra_number', name='uq_jamabandi_key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tehsil: Mapped[str] = mapped_column(String(200), nullable=False)
    village: Mapped[str] = mapped_column(String(200), nullable=False)
    khasra_number: Mapped[str] = mapped_column(String(100), nullable=False)
    khewat_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    area_kanal: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    area_marla: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    mutation_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    encumbrance_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    survey_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ZoningData(Base):
    __tablename__ = "zoning_data"
    __table_args__ = (UniqueConstraint('sector', 'land_use', name='uq_zoning_data_key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sector: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    land_use: Mapped[str | None] = mapped_column(String(100), nullable=True)  # residential, commercial, industrial, etc.
    far_limit: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    max_height_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    setback_front_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    setback_rear_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    master_plan_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class ColonyApproval(Base):
    __tablename__ = "colony_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    colony_name: Mapped[str] = mapped_column(String(300), nullable=False)
    developer_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, default="Gurugram")
    licence_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approval_status: Mapped[str | None] = mapped_column(String(50), nullable=True)  # approved, pending, revoked
    clu_status: Mapped[str | None] = mapped_column(String(50), nullable=True)  # approved, pending, rejected
    approval_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    area_acres: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class GazetteNotification(Base):
    __tablename__ = "gazette_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notification_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notification_type: Mapped[GazetteType | None] = mapped_column(SQLEnum(GazetteType, name='gazette_type'), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class ReraComplaint(Base):
    __tablename__ = "rera_complaints"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    complainant_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    respondent_builder: Mapped[str | None] = mapped_column(String(300), nullable=True)
    respondent_project: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rera_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    complaint_nature: Mapped[ComplaintNature | None] = mapped_column(SQLEnum(ComplaintNature, name='complaint_nature'), nullable=True)
    order_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    penalty_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    direction_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    builder_slug: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class CourtAuction(Base):
    __tablename__ = "court_auctions"
    __table_args__ = (UniqueConstraint('case_number', 'auction_date', name='uq_court_auctions_key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[AuctionSource] = mapped_column(SQLEnum(AuctionSource, name='auction_source'), nullable=False)
    case_number: Mapped[str] = mapped_column(String(200), nullable=False)
    borrower_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    property_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="Delhi NCR")
    locality: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reserve_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    auction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    presiding_officer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    court_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class NeighbourhoodScore(Base):
    __tablename__ = "neighbourhood_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True, unique=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    nearby_places: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metro_stations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    schools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hospitals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    malls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    it_parks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    landmarks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    api_calls_made: Mapped[int] = mapped_column(Integer, default=0)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stale_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    property: Mapped[Property | None] = relationship("Property", foreign_keys=[listing_id])


class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scraper_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False, default="cron")  # cron, manual, manual_override
    triggered_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[ScraperStatus] = mapped_column(SQLEnum(ScraperStatus, name='scraper_status'), nullable=False, default=ScraperStatus.running)
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    records_upserted: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    triggered_by_user: Mapped[User | None] = relationship("User", foreign_keys=[triggered_by])
