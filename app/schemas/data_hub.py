"""
Pydantic v2 schemas for the 360Ghar Data Hub feature.

Covers all 13 data hub entities plus calculation, builder reputation,
and paginated list response schemas.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import AuctionSource, ComplaintNature, GazetteType, ScraperStatus

# ---------------------------------------------------------------------------
# Shared meta schema
# ---------------------------------------------------------------------------

class DataHubMeta(BaseModel):
    """Metadata attached to every paginated data-hub list response."""
    last_updated: datetime | None = None
    is_stale: bool = False


# ---------------------------------------------------------------------------
# 1. Circle Rates
# ---------------------------------------------------------------------------

class CircleRateResponse(BaseModel):
    id: int
    sector: str
    colony: str | None = None
    property_type: str
    rate_per_sqyd: float | None = None
    rate_per_sqft: float | None = None
    revision_year: int
    effective_date: date | None = None
    slug: str
    source_url: str | None = None
    # last_scraped_at is not a model field; kept Optional for forward-compat
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 2. RERA Projects
# ---------------------------------------------------------------------------

class ReraProjectResponse(BaseModel):
    id: int
    rera_number: str
    project_name: str
    # Model column is `developer_name` — mapped directly
    developer_name: str | None = None
    project_type: str | None = None
    location: str | None = None
    # The model has no separate `sector` column; expose as None
    sector: str | None = None
    # Model uses `total_units` — aliased to `units_total` for API consumers
    units_total: int | None = Field(None, alias="total_units")
    units_booked: int | None = None
    possession_date: date | None = None
    registration_date: date | None = None
    expiry_date: date | None = None
    status: str | None = None
    # ORM column is `source_url`; exposed directly
    source_url: str | None = None
    slug: str | None = None
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 3. Bank Auctions
# ---------------------------------------------------------------------------

class BankAuctionResponse(BaseModel):
    id: int
    bank_name: str
    property_description: str
    # Model stores address in `full_address`
    address: str | None = Field(None, alias="full_address")
    reserve_price: float | None = None
    emd_amount: float | None = None
    auction_date: date | None = None
    emd_deadline: date | None = Field(None, alias="auction_end_date")
    # Contact info is split in model; serialised as combined string by router layer.
    # Expose as Optional here so the schema stays forward-compatible.
    contact_info: str | None = None
    source: AuctionSource
    source_url: str | None = None
    property_type: str | None = None
    # No lat/lng on the model; kept Optional for forward-compat
    lat: float | None = None
    lng: float | None = None
    slug: str | None = None
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 4. Auction Alerts
# ---------------------------------------------------------------------------

class AuctionAlertCreate(BaseModel):
    bank_name: str | None = None
    property_type: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    alert_channels: list[str] | None = None


class AuctionAlertUpdate(AuctionAlertCreate):
    pass


class AuctionAlertResponse(BaseModel):
    id: int
    user_id: int
    bank_name: str | None = None
    property_type: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    alert_channels: list[str] | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 5. Bank Rates
# ---------------------------------------------------------------------------

class BankRateResponse(BaseModel):
    id: int
    bank_name: str
    rate_type: str
    rate_value: float
    effective_date: date | None = None
    # Model stores `source` (not source_url); aliased for API surface
    source_url: str | None = Field(None, alias="source")
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 6. Jamabandi (land records) — request + response (no ORM model)
# ---------------------------------------------------------------------------

class JamabandiLookupRequest(BaseModel):
    tehsil: str
    village: str
    khasra_number: str
    captcha_token: str


class JamabandiLookupResponse(BaseModel):
    tehsil: str
    village: str
    khasra_number: str
    owner_names: list[str]
    area_acres: float | None = None
    mutation_status: str | None = None
    encumbrance: str | None = None
    raw_data: dict[str, Any] | None = None
    fetched_at: datetime
    is_cached: bool


# ---------------------------------------------------------------------------
# 7. Zoning Data
# ---------------------------------------------------------------------------

class ZoningDataResponse(BaseModel):
    id: int
    sector: str
    land_use: str | None = None
    # Model uses `far_limit`; exposed as `far` for API consumers
    far: float | None = Field(None, alias="far_limit")
    max_height_m: float | None = None
    # Model uses `max_coverage_pct`; exposed as `ground_coverage_pct`
    ground_coverage_pct: float | None = Field(None, alias="max_coverage_pct")
    permitted_uses: list[str] | None = None
    prohibited_uses: list[str] | None = None
    slug: str
    source_url: str | None = None
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 8. Colony Approvals
# ---------------------------------------------------------------------------

class ColonyApprovalResponse(BaseModel):
    id: int
    colony_name: str
    licence_number: str | None = None
    # Model uses `approval_status`; exposed as `status`
    status: str | None = Field(None, alias="approval_status")
    # Model uses `area_acres` (stored in acres); alias matches ORM column name
    approved_area_acres: float | None = Field(None, alias="area_acres")
    developer_name: str | None = None
    approval_date: date | None = None
    # No expiry_date on the model; kept Optional for forward-compat
    expiry_date: date | None = None
    source_url: str | None = None
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 9. Gazette Notifications
# ---------------------------------------------------------------------------

class GazetteNotificationResponse(BaseModel):
    id: int
    notification_number: str | None = None
    notification_date: date | None = None
    department: str | None = None
    title: str
    summary: str | None = None
    # Model stores `pdf_text`; `full_text` exposed as alias
    full_text: str | None = Field(None, alias="pdf_text")
    pdf_url: str | None = None
    # Model uses `relevance_tags`; exposed as `tags`
    tags: list[str] | None = Field(None, alias="relevance_tags")
    relevance_score: float | None = None
    notification_type: GazetteType | None = None
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 10. RERA Complaints
# ---------------------------------------------------------------------------

class ReraComplaintResponse(BaseModel):
    id: int
    rera_number: str | None = None
    # Model uses `respondent_project`; exposed as `project_name`
    project_name: str | None = Field(None, alias="respondent_project")
    # Model uses `respondent_builder`; exposed as `developer_name`
    developer_name: str | None = Field(None, alias="respondent_builder")
    complainant_type: str | None = None
    complaint_nature: ComplaintNature | None = None
    order_number: str
    order_date: date | None = None
    penalty_amount: float | None = None
    order_summary: str | None = None
    # Model uses `pdf_url`; exposed as `order_url`
    order_url: str | None = Field(None, alias="pdf_url")
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 11. Court Auctions
# ---------------------------------------------------------------------------

class CourtAuctionResponse(BaseModel):
    id: int
    case_number: str
    court_name: str | None = None
    # Model uses `borrower_name`; exposed as `debtor_name`
    debtor_name: str | None = Field(None, alias="borrower_name")
    property_description: str | None = None
    # Model stores address as `locality` (city-level); no separate `address` col
    address: str | None = Field(None, alias="locality")
    reserve_price: float | None = None
    auction_date: date | None = None
    source: AuctionSource
    source_url: str | None = None
    property_type: str | None = None
    # No lat/lng on the model; kept Optional for forward-compat
    lat: float | None = None
    lng: float | None = None
    slug: str | None = None
    last_scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 12. Neighbourhood Scores
# ---------------------------------------------------------------------------

class NeighbourhoodScoreResponse(BaseModel):
    id: int
    listing_id: int | None = None
    overall_score: int | None = None
    # Individual category scores are stored in `category_scores` JSON dict.
    # Expose them as Optional[int] mapped from the dict — router layer
    # should populate these; schema stays forward-compatible with None.
    transit_score: int | None = None
    education_score: int | None = None
    health_score: int | None = None
    retail_score: int | None = None
    # `nearby_places` dict surface for API consumers
    places_data: dict[str, Any] | None = Field(None, alias="nearby_places")
    stale_after: datetime
    last_fetched_at: datetime
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 13. Scraper Runs
# ---------------------------------------------------------------------------

class ScraperRunResponse(BaseModel):
    id: int
    scraper_name: str
    run_type: str
    status: ScraperStatus
    records_found: int
    records_upserted: int
    records_failed: int
    error_message: str | None = None
    started_at: datetime
    # Model uses `finished_at`; exposed as `completed_at`
    completed_at: datetime | None = Field(None, alias="finished_at")
    triggered_by: int | None = None
    run_metadata: dict[str, Any] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> float | None:
        """Compute run duration from started_at / completed_at."""
        if self.completed_at is not None and self.started_at is not None:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Stamp Duty Calculation
# ---------------------------------------------------------------------------

class StampDutyCalculationRequest(BaseModel):
    property_value: float = Field(..., gt=0)
    sector: str | None = None
    buyer_type: Literal["male", "female", "joint"]
    property_type: str | None = None


class StampDutyCalculationResponse(BaseModel):
    property_value: float
    circle_rate_per_sqyd: float | None = None
    stamp_duty_rate: float
    stamp_duty_amount: float
    registration_fee: float
    total_cost: float
    current_bank_rate: float | None = None


# ---------------------------------------------------------------------------
# Builder Reputation
# ---------------------------------------------------------------------------

class BuilderReputationResponse(BaseModel):
    builder_name: str
    slug: str
    total_projects: int
    total_complaints: int
    builder_score: float
    rera_projects: list[ReraProjectResponse]
    recent_complaints: list[ReraComplaintResponse]

    model_config = ConfigDict(from_attributes=True)
