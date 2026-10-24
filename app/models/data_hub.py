from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, db_enum
from app.models.enums import (
    AuctionSource,
    ComplaintNature,
    GazetteType,
    MarketSentiment,
    ProjectPersonRole,
    ProjectPriceSource,
    ProjectStage,
    ScraperStatus,
)

if TYPE_CHECKING:
    from app.models.properties import Property
    from app.models.users import User


class CircleRate(Base):
    __tablename__ = "circle_rates"
    __table_args__ = (
        UniqueConstraint("sector", "colony", "property_type", "revision_year"),
        Index("idx_circle_rates_slug", "slug", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, default="Gurugram")
    tehsil: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sector: Mapped[str] = mapped_column(String(200), nullable=False)
    colony: Mapped[str | None] = mapped_column(String(200), nullable=True)
    property_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # residential, commercial, plot, industrial
    rate_per_sqyd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rate_per_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rate_per_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    revision_year: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraProject(Base):
    __tablename__ = "rera_projects"
    __table_args__ = (
        Index("idx_rera_projects_slug", "slug", unique=True),
        # The HRERA filing page states only the portal's pre-registration project
        # id, never the registration number, so the portal-id scan keys on this
        # expression instead of on rera_number. Partial, so rows from other
        # sources that carry no portal id stay unconstrained.
        Index(
            "idx_rera_projects_portal_project_id",
            text("(raw_data ->> 'portal_project_id')"),
            unique=True,
            postgresql_where=text("raw_data ->> 'portal_project_id' IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_number: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    # Public URL key, derived from the project name and the RERA number. The RERA
    # number is unique, so the slug is unique by construction. Postgres allows
    # repeated NULLs in a unique index, so pre-existing rows may keep a null slug.
    slug: Mapped[str | None] = mapped_column(String(300), nullable=True)
    project_name: Mapped[str] = mapped_column(String(500), nullable=False)
    developer_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    developer_slug: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, default="Gurugram")
    # The micro-market this project's filed address resolves to, derived from
    # ``location`` by ``micro_market.derive_locality``. Without this the read side
    # can only scope by district, so two localities in one district report the
    # same project count and average rate under different names — a false claim
    # on a public page. Null when the address names no locality the parser can
    # read, which is honest: an unreadable address belongs to no micro-market.
    micro_market_id: Mapped[int | None] = mapped_column(
        ForeignKey("micro_markets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    total_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_booked: Mapped[int | None] = mapped_column(Integer, nullable=True)
    possession_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )  # registered, lapsed, revoked, completed
    project_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    complaint_count: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scraper_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BankAuction(Base):
    __tablename__ = "bank_auctions"
    __table_args__ = (
        UniqueConstraint(
            "bank_name", "normalized_address_hash", "auction_date", name="uq_bank_auctions_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[AuctionSource] = mapped_column(
        db_enum(AuctionSource, "auction_source"), nullable=False
    )
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
    possession_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # physical, symbolic
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    normalized_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuctionAlert(Base):
    __tablename__ = "auction_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    keyword: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])


class BankRate(Base):
    __tablename__ = "bank_rates"
    __table_args__ = (
        UniqueConstraint("bank_name", "rate_type", "effective_date", name="uq_bank_rates_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rate_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # repo, mclr_1y, home_loan_min, etc.
    rate_value: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JamabandiCache(Base):
    """Cached Jamabandi land records. No updated_at — rows are replaced, not updated."""

    __tablename__ = "jamabandi_cache"
    __table_args__ = (UniqueConstraint("tehsil", "village", "khasra_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tehsil: Mapped[str] = mapped_column(String(200), nullable=False)
    village: Mapped[str] = mapped_column(String(200), nullable=False)
    khasra_number: Mapped[str] = mapped_column(String(100), nullable=False)
    khewat_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_names: Mapped[list | None] = mapped_column(JSONB, nullable=True)
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
    __table_args__ = (
        UniqueConstraint("sector", "land_use"),
        Index("idx_zoning_data_slug", "slug", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sector: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    land_use: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # residential, commercial, industrial, etc.
    far_limit: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    max_height_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    setback_front_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    setback_rear_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    master_plan_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scraper_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ColonyApproval(Base):
    __tablename__ = "colony_approvals"
    __table_args__ = (
        Index(
            "idx_colony_approvals_unique_with_licence",
            "colony_name",
            "licence_number",
            unique=True,
            postgresql_where=text("licence_number IS NOT NULL"),
        ),
        Index(
            "idx_colony_approvals_unique_no_licence",
            "colony_name",
            unique=True,
            postgresql_where=text("licence_number IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    colony_name: Mapped[str] = mapped_column(String(300), nullable=False)
    developer_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, default="Gurugram")
    licence_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approval_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # approved, pending, revoked
    clu_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # approved, pending, rejected
    approval_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    area_acres: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scraper_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GazetteNotification(Base):
    __tablename__ = "gazette_notifications"
    __table_args__ = (
        Index(
            "idx_gazette_unique_with_number",
            "notification_number",
            "notification_date",
            unique=True,
            postgresql_where=text("notification_number IS NOT NULL"),
        ),
        Index(
            "idx_gazette_unique_no_number",
            "title",
            "notification_date",
            unique=True,
            postgresql_where=text("notification_number IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notification_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notification_type: Mapped[GazetteType | None] = mapped_column(
        db_enum(GazetteType, "gazette_type"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraComplaint(Base):
    __tablename__ = "rera_complaints"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    complainant_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    respondent_builder: Mapped[str | None] = mapped_column(String(300), nullable=True)
    respondent_project: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rera_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    complaint_nature: Mapped[ComplaintNature | None] = mapped_column(
        db_enum(ComplaintNature, "complaint_nature"), nullable=True
    )
    order_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    penalty_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    direction_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    builder_slug: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CourtAuction(Base):
    __tablename__ = "court_auctions"
    __table_args__ = (UniqueConstraint("case_number", "auction_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[AuctionSource] = mapped_column(
        db_enum(AuctionSource, "auction_source"), nullable=False
    )
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
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NeighbourhoodScore(Base):
    __tablename__ = "neighbourhood_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    nearby_places: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    metro_stations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    schools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    hospitals: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    malls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    it_parks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    landmarks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    api_calls_made: Mapped[int] = mapped_column(Integer, default=0)
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    stale_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    property: Mapped[Property | None] = relationship("Property", foreign_keys=[listing_id])


class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scraper_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="cron"
    )  # cron, manual, manual_override
    triggered_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ScraperStatus] = mapped_column(
        db_enum(ScraperStatus, "scraper_status"), nullable=False, default=ScraperStatus.running
    )
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    records_upserted: Mapped[int] = mapped_column(Integer, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    triggered_by_user: Mapped[User | None] = relationship("User", foreign_keys=[triggered_by])


class SourceDocument(Base):
    """Restricted source metadata; source content itself is never persisted here."""

    __tablename__ = "source_documents"
    __table_args__ = (
        CheckConstraint(
            "NULLIF(BTRIM(canonical_url), '') IS NOT NULL "
            "OR NULLIF(BTRIM(source_record_id), '') IS NOT NULL",
            name="ck_source_documents_has_locator",
        ),
        CheckConstraint(
            "effective_from IS NULL OR effective_to IS NULL OR effective_from <= effective_to",
            name="ck_source_documents_effective_dates",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_source_documents_sha256",
        ),
        Index(
            "uq_source_documents_url_hash",
            "canonical_url",
            "content_sha256",
            unique=True,
            postgresql_where=text("canonical_url IS NOT NULL"),
        ),
        Index(
            "uq_source_documents_record_hash",
            "authority",
            "source_record_id",
            "content_sha256",
            unique=True,
            postgresql_where=text("source_record_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    authority: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    license_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    reuse_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DataHubEvidenceAssertion(Base):
    __tablename__ = "data_hub_evidence_assertions"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(rera_project_id, zoning_data_id, colony_approval_id) = 1",
            name="ck_data_hub_assertions_exactly_one_target",
        ),
        CheckConstraint(
            "field_path IN ("
            "'rera_project.rera_number', 'rera_project.project_name', "
            "'rera_project.developer_name', 'rera_project.location', "
            "'rera_project.district', 'rera_project.total_units', "
            "'rera_project.units_booked', 'rera_project.possession_date', "
            "'rera_project.registration_date', 'rera_project.expiry_date', "
            "'rera_project.status', 'rera_project.project_type', "
            "'rera_project.total_area_sqm', "
            "'zoning_data.sector', 'zoning_data.land_use', 'zoning_data.far_limit', "
            "'zoning_data.max_height_m', 'zoning_data.max_coverage_pct', "
            "'zoning_data.setback_front_m', 'zoning_data.setback_rear_m', "
            "'zoning_data.master_plan_year', 'zoning_data.notes', "
            "'colony_approval.colony_name', 'colony_approval.developer_name', "
            "'colony_approval.district', 'colony_approval.licence_number', "
            "'colony_approval.approval_status', 'colony_approval.clu_status', "
            "'colony_approval.approval_date', 'colony_approval.area_acres', "
            "'colony_approval.sector')",
            name="ck_data_hub_assertions_field_path",
        ),
        CheckConstraint(
            "status IN ('unreviewed', 'accepted', 'rejected', 'superseded')",
            name="ck_data_hub_assertions_status",
        ),
        CheckConstraint(
            "method IN ('scrape', 'manual', 'ocr', 'derived')",
            name="ck_data_hub_assertions_method",
        ),
        CheckConstraint(
            "locator_page IS NULL OR locator_page > 0",
            name="ck_data_hub_assertions_locator_page",
        ),
        CheckConstraint(
            "locator_table IS NULL OR locator_table > 0",
            name="ck_data_hub_assertions_locator_table",
        ),
        CheckConstraint(
            "locator_row IS NULL OR locator_row > 0",
            name="ck_data_hub_assertions_locator_row",
        ),
        CheckConstraint(
            "locator_column IS NULL OR locator_column > 0",
            name="ck_data_hub_assertions_locator_column",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="ck_data_hub_assertions_validity_dates",
        ),
        Index(
            "uq_data_hub_assertions_rera_run_field_source",
            "rera_project_id",
            "source_run_id",
            "field_path",
            "source_document_id",
            unique=True,
            postgresql_where=text("rera_project_id IS NOT NULL"),
        ),
        Index(
            "uq_data_hub_assertions_zoning_run_field_source",
            "zoning_data_id",
            "source_run_id",
            "field_path",
            "source_document_id",
            unique=True,
            postgresql_where=text("zoning_data_id IS NOT NULL"),
        ),
        Index(
            "uq_data_hub_assertions_colony_run_field_source",
            "colony_approval_id",
            "source_run_id",
            "field_path",
            "source_document_id",
            unique=True,
            postgresql_where=text("colony_approval_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rera_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="RESTRICT"), nullable=True
    )
    zoning_data_id: Mapped[int | None] = mapped_column(
        ForeignKey("zoning_data.id", ondelete="RESTRICT"), nullable=True
    )
    colony_approval_id: Mapped[int | None] = mapped_column(
        ForeignKey("colony_approvals.id", ondelete="RESTRICT"), nullable=True
    )
    field_path: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_value: Mapped[dict | list | str | int | float | bool] = mapped_column(
        JSONB, nullable=False
    )
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=False
    )
    locator_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_table: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_column: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unreviewed", server_default=text("'unreviewed'")
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scraper_runs.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_hub_evidence_assertions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DataHubEntityRevision(Base):
    __tablename__ = "data_hub_entity_revisions"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(rera_project_id, zoning_data_id, colony_approval_id) = 1",
            name="ck_data_hub_revisions_exactly_one_target",
        ),
        CheckConstraint("revision_number > 0", name="ck_data_hub_revisions_positive_number"),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_data_hub_revisions_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(normalized_snapshot) = 'object'",
            name="ck_data_hub_revisions_snapshot_object",
        ),
        CheckConstraint(
            "normalized_snapshot - ARRAY["
            "'rera_number', 'project_name', 'developer_name', 'location', 'district', "
            "'total_units', 'units_booked', 'possession_date', 'registration_date', "
            "'expiry_date', 'status', 'project_type', 'total_area_sqm', "
            "'sector', 'land_use', 'far_limit', 'max_height_m', 'max_coverage_pct', "
            "'setback_front_m', 'setback_rear_m', 'master_plan_year', 'notes', "
            "'colony_name', 'licence_number', 'approval_status', 'clu_status', "
            "'approval_date', 'area_acres']::TEXT[] = '{}'::JSONB",
            name="ck_data_hub_revisions_snapshot_allowlist",
        ),
        CheckConstraint(
            "jsonb_typeof(changed_fields) = 'array'",
            name="ck_data_hub_revisions_changed_fields_array",
        ),
        Index(
            "uq_data_hub_revisions_rera_number",
            "rera_project_id",
            "revision_number",
            unique=True,
            postgresql_where=text("rera_project_id IS NOT NULL"),
        ),
        Index(
            "uq_data_hub_revisions_zoning_number",
            "zoning_data_id",
            "revision_number",
            unique=True,
            postgresql_where=text("zoning_data_id IS NOT NULL"),
        ),
        Index(
            "uq_data_hub_revisions_colony_number",
            "colony_approval_id",
            "revision_number",
            unique=True,
            postgresql_where=text("colony_approval_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rera_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="RESTRICT"), nullable=True
    )
    zoning_data_id: Mapped[int | None] = mapped_column(
        ForeignKey("zoning_data.id", ondelete="RESTRICT"), nullable=True
    )
    colony_approval_id: Mapped[int | None] = mapped_column(
        ForeignKey("colony_approvals.id", ondelete="RESTRICT"), nullable=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scraper_runs.id", ondelete="RESTRICT"), nullable=True
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# REP-I project intelligence
#
# One filing page per project supplies every row below
# (haryanarera.gov.in/view_project/project_preview_open/{portal_project_id}).
# Collection tables are replaced wholesale only after a filing parses in full,
# so a failed parse can never leave a half-written filing behind. Every table
# carries ``source_document_id`` so a row traces back to the filing it came from.
# ---------------------------------------------------------------------------


class ReraProjectProfile(Base):
    """1:1 scalar facts from REP-I Parts A/C/D that do not fit ``rera_projects``."""

    __tablename__ = "rera_project_profiles"
    __table_args__ = (
        UniqueConstraint("rera_project_id", name="uq_rera_project_profiles_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False
    )
    # Portal-side identifier, so a later refresh needs no search round trip.
    portal_project_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    licensed_land_acres: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    land_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    proposed_far: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    permissible_far: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    towers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    floors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_per_acre: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    rera_received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    construction_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    proposed_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    launch_price_per_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_price_per_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    stage: Mapped[ProjectStage | None] = mapped_column(
        db_enum(ProjectStage, "project_stage"), nullable=True, index=True
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraLandUsage(Base):
    """REP-I land-usage split, one row per particular (plots, roads, parks, ...)."""

    __tablename__ = "rera_land_usage"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id", "particular", name="uq_rera_land_usage_project_particular"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    particular: Mapped[str] = mapped_column(String(200), nullable=False)
    area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    area_acres: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReraProjectCost(Base):
    """1:1 REP-I cost breakdown. Amounts are in rupees as filed."""

    __tablename__ = "rera_project_costs"
    __table_args__ = (
        UniqueConstraint("rera_project_id", name="uq_rera_project_costs_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False
    )
    land_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    construction_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    infrastructure_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraQuarterlyExpenditure(Base):
    """REP-I 7-year quarterly expenditure, per category and particular."""

    __tablename__ = "rera_quarterly_expenditure"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id",
            "category",
            "year",
            "quarter",
            "particular",
            name="uq_rera_quarterly_expenditure_point",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # apartment | infrastructure
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    particular: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReraProjectDocument(Base):
    """A document uploaded to the filing. ``ordinal`` is its position in the filing table."""

    __tablename__ = "rera_project_documents"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id", "ordinal", name="uq_rera_project_documents_project_ordinal"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    view_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReraStatutoryApproval(Base):
    """1:1 REP-I statutory approvals and utility availability."""

    __tablename__ = "rera_statutory_approvals"
    __table_args__ = (
        UniqueConstraint("rera_project_id", name="uq_rera_statutory_approvals_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False
    )
    loi_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    loi_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    licence_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    licence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    electric_load_kw: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    water_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    storm_water_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sewerage_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Ten plan-approval booleans keyed by approval name; the portal list changes.
    plan_approvals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraProjectFacility(Base):
    """Declared project facility with its filed cost and status."""

    __tablename__ = "rera_project_facilities"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id", "facility", name="uq_rera_project_facilities_project_facility"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    facility: Mapped[str] = mapped_column(String(200), nullable=False)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReraProjectNoc(Base):
    """REP-I no-objection certificate row: facility, provider agency, approval state."""

    __tablename__ = "rera_project_nocs"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id", "facility", name="uq_rera_project_nocs_project_facility"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    facility: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_agency: Mapped[str | None] = mapped_column(String(300), nullable=True)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approval_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReraProjectPerson(Base):
    """A promoter-side person listed in the filing.

    Only the last four PAN characters are stored. The filing page publishes the
    full identifier to anyone who loads it; keeping the rest out of our database
    means a leak here cannot expose it. Contact details stay private to the API.
    """

    __tablename__ = "rera_project_people"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id", "role", "name", name="uq_rera_project_people_role_name"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ProjectPersonRole] = mapped_column(
        db_enum(ProjectPersonRole, "project_person_role"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    pan_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    phones: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraProjectBankAccount(Base):
    """The project's designated collection account.

    ``account_number`` is stored because the filing states it and reconciliation
    needs it, but it is never part of a public response payload.
    """

    __tablename__ = "rera_project_bank_accounts"
    __table_args__ = (
        UniqueConstraint("rera_project_id", name="uq_rera_project_bank_accounts_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False
    )
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    micr: Mapped[str | None] = mapped_column(String(20), nullable=True)
    branch_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    operators: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraProjectUnitConfig(Base):
    """Apartment type with its areas, parking count, and filed price.

    ``ordinal`` is the row's position in the filing table. A project can list the
    same apartment type at two carpet areas, so the type alone is not a key.
    """

    __tablename__ = "rera_project_unit_configs"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id", "ordinal", name="uq_rera_project_unit_configs_project_ordinal"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_type: Mapped[str] = mapped_column(String(200), nullable=False)
    carpet_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    built_up_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    super_built_up_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    carpet_efficiency: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    towers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parkings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReraProjectSpecification(Base):
    """Construction specification line, either project-wide or per apartment type."""

    __tablename__ = "rera_project_specifications"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id",
            "scope",
            "unit_type",
            "spec_key",
            name="uq_rera_project_specifications_line",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # project | unit
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    # "all" for project-wide lines; otherwise the apartment type it belongs to.
    unit_type: Mapped[str] = mapped_column(String(200), nullable=False, default="all")
    spec_key: Mapped[str] = mapped_column(String(200), nullable=False)
    spec_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Developer(Base):
    """A promoter organisation, one row per slug shared by every project it filed."""

    __tablename__ = "developers"
    __table_args__ = (Index("idx_developers_slug", "slug", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cin: Mapped[str | None] = mapped_column(String(30), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    dossier: Mapped[str | None] = mapped_column(Text, nullable=True)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_listed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    headquarters: Mapped[str | None] = mapped_column(String(300), nullable=True)
    geographies: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scraper_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DeveloperScore(Base):
    """Current five-pillar trust score. Each recompute writes a new row's worth of values."""

    __tablename__ = "developer_scores"
    __table_args__ = (
        UniqueConstraint("developer_id", name="uq_developer_scores_developer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    developer_id: Mapped[int] = mapped_column(
        ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delivery: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    regulatory: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    complaints: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    financials: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    market_reception: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True, index=True)
    project_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    under_construction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complaint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProjectPriceHistory(Base):
    """A price point for one project.

    ``filing`` and ``launch`` points are read from a filing. ``derived`` points
    are computed from them and are marked as such, so a derived number is never
    mistaken for a filed one.
    """

    __tablename__ = "project_price_history"
    __table_args__ = (
        UniqueConstraint(
            "rera_project_id",
            "quarter",
            "unit_type",
            "source",
            name="uq_project_price_history_point",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quarter: Mapped[str] = mapped_column(String(7), nullable=False)  # e.g. 2024-Q1
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit_type: Mapped[str] = mapped_column(String(200), nullable=False, default="all")
    price_per_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    source: Mapped[ProjectPriceSource] = mapped_column(
        db_enum(ProjectPriceSource, "project_price_source"), nullable=False
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MicroMarket(Base):
    """A named sub-market inside a city, the unit used for rate comparisons."""

    __tablename__ = "micro_markets"
    __table_args__ = (
        UniqueConstraint("city", "slug", name="uq_micro_markets_city_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProjectWatchlist(Base):
    """A user's saved project, with the alert switches they chose for it."""

    __tablename__ = "project_watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "rera_project_id", name="uq_project_watchlist_user_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rera_project_id: Mapped[int] = mapped_column(
        ForeignKey("rera_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_prefs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # The values the user was last told. Only the alert service writes it; see
    # app/services/data_hub/watchlist_alerts.py.
    alert_baseline: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MarketPulseSnapshot(Base):
    """One city's market reading for a day. Rows are the history; nothing is overwritten."""

    __tablename__ = "market_pulse_snapshots"
    __table_args__ = (
        UniqueConstraint("city", "captured_on", name="uq_market_pulse_snapshots_city_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    captured_on: Mapped[date] = mapped_column(Date, nullable=False)
    sentiment: Mapped[MarketSentiment] = mapped_column(
        db_enum(MarketSentiment, "market_sentiment"), nullable=False
    )
    avg_price_per_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_change_90d_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    new_registrations: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    new_complaints: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
