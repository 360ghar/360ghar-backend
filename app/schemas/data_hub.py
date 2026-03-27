"""
Pydantic v2 schemas for the 360Ghar Data Hub feature.

Covers all 13 data hub entities plus calculation, builder reputation,
and paginated list response schemas.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import AuctionSource, ComplaintNature, GazetteType, ScraperStatus
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Shared meta schema
# ---------------------------------------------------------------------------

class DataHubMeta(BaseModel):
    """Metadata attached to every paginated data-hub list response."""
    last_updated: Optional[datetime] = None
    is_stale: bool = False


# ---------------------------------------------------------------------------
# 1. Circle Rates
# ---------------------------------------------------------------------------

class CircleRateResponse(BaseModel):
    id: int
    sector: str
    colony: Optional[str] = None
    property_type: str
    rate_per_sqyd: Optional[float] = None
    rate_per_sqft: Optional[float] = None
    revision_year: int
    effective_date: Optional[date] = None
    slug: str
    source_url: Optional[str] = None
    # last_scraped_at is not a model field; kept Optional for forward-compat
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CircleRateListResponse(PaginatedResponse):
    items: List[CircleRateResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 2. RERA Projects
# ---------------------------------------------------------------------------

class ReraProjectResponse(BaseModel):
    id: int
    rera_number: str
    project_name: str
    # Model column is `developer_name` — mapped directly
    developer_name: Optional[str] = None
    project_type: Optional[str] = None
    location: Optional[str] = None
    # The model has no separate `sector` column; expose as None
    sector: Optional[str] = None
    # Model uses `total_units` — aliased to `units_total` for API consumers
    units_total: Optional[int] = Field(None, alias="total_units")
    units_booked: Optional[int] = None
    possession_date: Optional[date] = None
    registration_date: Optional[date] = None
    expiry_date: Optional[date] = None
    status: Optional[str] = None
    # ORM column is `source_url`; exposed directly
    source_url: Optional[str] = None
    slug: Optional[str] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ReraProjectListResponse(PaginatedResponse):
    items: List[ReraProjectResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 3. Bank Auctions
# ---------------------------------------------------------------------------

class BankAuctionResponse(BaseModel):
    id: int
    bank_name: str
    property_description: str
    # Model stores address in `full_address`
    address: Optional[str] = Field(None, alias="full_address")
    reserve_price: Optional[float] = None
    emd_amount: Optional[float] = None
    auction_date: Optional[date] = None
    emd_deadline: Optional[date] = None
    # Contact info is split in model; serialised as combined string by router layer.
    # Expose as Optional here so the schema stays forward-compatible.
    contact_info: Optional[str] = None
    source: AuctionSource
    source_url: Optional[str] = None
    property_type: Optional[str] = None
    # No lat/lng on the model; kept Optional for forward-compat
    lat: Optional[float] = None
    lng: Optional[float] = None
    slug: Optional[str] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AuctionListResponse(PaginatedResponse):
    items: List[BankAuctionResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 4. Auction Alerts
# ---------------------------------------------------------------------------

class AuctionAlertCreate(BaseModel):
    bank_name: Optional[str] = None
    property_type: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    alert_channels: Optional[List[str]] = None


class AuctionAlertUpdate(AuctionAlertCreate):
    pass


class AuctionAlertResponse(BaseModel):
    id: int
    user_id: int
    bank_name: Optional[str] = None
    property_type: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    alert_channels: Optional[List[str]] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 5. Bank Rates
# ---------------------------------------------------------------------------

class BankRateResponse(BaseModel):
    id: int
    bank_name: str
    rate_type: str
    rate_value: float
    effective_date: Optional[date] = None
    # Model stores `source` (not source_url); aliased for API surface
    source_url: Optional[str] = Field(None, alias="source")
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class BankRateListResponse(PaginatedResponse):
    items: List[BankRateResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


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
    owner_names: List[str]
    area_acres: Optional[float] = None
    mutation_status: Optional[str] = None
    encumbrance: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    fetched_at: datetime
    is_cached: bool


# ---------------------------------------------------------------------------
# 7. Zoning Data
# ---------------------------------------------------------------------------

class ZoningDataResponse(BaseModel):
    id: int
    sector: str
    land_use: Optional[str] = None
    # Model uses `far_limit`; exposed as `far` for API consumers
    far: Optional[float] = Field(None, alias="far_limit")
    max_height_m: Optional[float] = None
    # Model uses `max_coverage_pct`; exposed as `ground_coverage_pct`
    ground_coverage_pct: Optional[float] = Field(None, alias="max_coverage_pct")
    permitted_uses: Optional[List[str]] = None
    prohibited_uses: Optional[List[str]] = None
    slug: str
    source_url: Optional[str] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ZoningDataListResponse(PaginatedResponse):
    items: List[ZoningDataResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 8. Colony Approvals
# ---------------------------------------------------------------------------

class ColonyApprovalResponse(BaseModel):
    id: int
    colony_name: str
    licence_number: Optional[str] = None
    # Model uses `approval_status`; exposed as `status`
    status: Optional[str] = Field(None, alias="approval_status")
    # Model uses `area_acres` (stored in acres); alias matches ORM column name
    approved_area_acres: Optional[float] = Field(None, alias="area_acres")
    developer_name: Optional[str] = None
    approval_date: Optional[date] = None
    # No expiry_date on the model; kept Optional for forward-compat
    expiry_date: Optional[date] = None
    source_url: Optional[str] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ColonyApprovalListResponse(PaginatedResponse):
    items: List[ColonyApprovalResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 9. Gazette Notifications
# ---------------------------------------------------------------------------

class GazetteNotificationResponse(BaseModel):
    id: int
    notification_number: Optional[str] = None
    notification_date: Optional[date] = None
    department: Optional[str] = None
    title: str
    summary: Optional[str] = None
    # Model stores `pdf_text`; `full_text` exposed as alias
    full_text: Optional[str] = Field(None, alias="pdf_text")
    pdf_url: Optional[str] = None
    # Model uses `relevance_tags`; exposed as `tags`
    tags: Optional[List[str]] = Field(None, alias="relevance_tags")
    relevance_score: Optional[float] = None
    notification_type: Optional[GazetteType] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GazetteNotificationListResponse(PaginatedResponse):
    items: List[GazetteNotificationResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 10. RERA Complaints
# ---------------------------------------------------------------------------

class ReraComplaintResponse(BaseModel):
    id: int
    rera_number: Optional[str] = None
    # Model uses `respondent_project`; exposed as `project_name`
    project_name: Optional[str] = Field(None, alias="respondent_project")
    # Model uses `respondent_builder`; exposed as `developer_name`
    developer_name: Optional[str] = Field(None, alias="respondent_builder")
    complainant_type: Optional[str] = None
    complaint_nature: Optional[ComplaintNature] = None
    order_number: str
    order_date: Optional[date] = None
    penalty_amount: Optional[float] = None
    order_summary: Optional[str] = None
    # Model uses `pdf_url`; exposed as `order_url`
    order_url: Optional[str] = Field(None, alias="pdf_url")
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ReraComplaintListResponse(PaginatedResponse):
    items: List[ReraComplaintResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 11. Court Auctions
# ---------------------------------------------------------------------------

class CourtAuctionResponse(BaseModel):
    id: int
    case_number: str
    court_name: Optional[str] = None
    # Model uses `borrower_name`; exposed as `debtor_name`
    debtor_name: Optional[str] = Field(None, alias="borrower_name")
    property_description: Optional[str] = None
    # Model stores address as `locality` (city-level); no separate `address` col
    address: Optional[str] = Field(None, alias="locality")
    reserve_price: Optional[float] = None
    auction_date: Optional[date] = None
    source: AuctionSource
    source_url: Optional[str] = None
    property_type: Optional[str] = None
    # No lat/lng on the model; kept Optional for forward-compat
    lat: Optional[float] = None
    lng: Optional[float] = None
    slug: Optional[str] = None
    last_scraped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 12. Neighbourhood Scores
# ---------------------------------------------------------------------------

class NeighbourhoodScoreResponse(BaseModel):
    id: int
    listing_id: Optional[int] = None
    overall_score: Optional[int] = None
    # Individual category scores are stored in `category_scores` JSON dict.
    # Expose them as Optional[int] mapped from the dict — router layer
    # should populate these; schema stays forward-compatible with None.
    transit_score: Optional[int] = None
    education_score: Optional[int] = None
    health_score: Optional[int] = None
    retail_score: Optional[int] = None
    # `nearby_places` dict surface for API consumers
    places_data: Optional[Dict[str, Any]] = Field(None, alias="nearby_places")
    stale_after: datetime
    last_fetched_at: datetime
    created_at: datetime
    updated_at: Optional[datetime] = None

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
    error_message: Optional[str] = None
    started_at: datetime
    # Model uses `finished_at`; exposed as `completed_at`
    completed_at: Optional[datetime] = Field(None, alias="finished_at")
    triggered_by: Optional[int] = None
    run_metadata: Optional[Dict[str, Any]] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> Optional[float]:
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
    sector: Optional[str] = None
    buyer_type: Literal["male", "female", "joint"]
    property_type: Optional[str] = None


class StampDutyCalculationResponse(BaseModel):
    property_value: float
    circle_rate_per_sqyd: Optional[float] = None
    stamp_duty_rate: float
    stamp_duty_amount: float
    registration_fee: float
    total_cost: float
    current_bank_rate: Optional[float] = None


# ---------------------------------------------------------------------------
# Builder Reputation
# ---------------------------------------------------------------------------

class BuilderReputationResponse(BaseModel):
    builder_name: str
    slug: str
    total_projects: int
    total_complaints: int
    builder_score: float
    rera_projects: List[ReraProjectResponse]
    recent_complaints: List[ReraComplaintResponse]

    model_config = ConfigDict(from_attributes=True)


class BuilderListResponse(PaginatedResponse):
    items: List[BuilderReputationResponse]
    meta: DataHubMeta = Field(default_factory=DataHubMeta)

    model_config = ConfigDict(from_attributes=True)
