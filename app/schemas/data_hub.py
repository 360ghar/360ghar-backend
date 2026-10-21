"""
Pydantic v2 schemas for the 360Ghar Data Hub feature.

Covers all 13 data hub entities plus calculation, builder reputation,
and paginated list response schemas.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import (
    AuctionKind,
    AuctionPropertyType,
    AuctionSource,
    ComplaintNature,
    GazetteType,
    ScraperStatus,
)
from app.schemas.base import Money, UtcDateTime, WriteModel

# ---------------------------------------------------------------------------
# Shared meta schema
# ---------------------------------------------------------------------------


class DataHubMeta(BaseModel):
    """Metadata attached to every paginated data-hub list response."""

    last_updated: UtcDateTime | None = None
    is_stale: bool = False


# ---------------------------------------------------------------------------
# 1. Circle Rates
# ---------------------------------------------------------------------------


class CircleRateResponse(BaseModel):
    id: int
    sector: str
    colony: str | None = None
    property_type: str
    rate_per_sqyd: Money | None = None
    rate_per_sqft: float | None = None
    revision_year: int
    effective_date: date | None = None
    slug: str
    source_url: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

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
    total_units: int | None = None
    units_booked: int | None = None
    possession_date: date | None = None
    registration_date: date | None = None
    expiry_date: date | None = None
    status: str | None = None
    # ORM column is `source_url`; exposed directly
    source_url: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 3. Bank Auctions
# ---------------------------------------------------------------------------


class ReraVerifyResult(BaseModel):
    valid: bool
    status: str | None = None
    project_name: str | None = None


class ScraperTriggerResult(BaseModel):
    message: str
    result: Any = None


class AuctionSourceInfo(BaseModel):
    source: str
    label: str
    url: str
    # Group name: central, delhi, gurgaon, meerut, aggregators or banks.
    category: str
    count: int = 0


class BankAuctionResponse(BaseModel):
    id: int
    # Bank and court rows have separate id sequences. kind says which table id belongs to.
    kind: AuctionKind = AuctionKind.bank
    bank_name: str
    property_description: str
    full_address: str | None = None
    reserve_price: Money | None = None
    emd_amount: Money | None = None
    auction_date: date | None = None
    auction_end_date: date | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    source: AuctionSource
    source_url: str | None = None
    property_type: AuctionPropertyType | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 4. Auction Alerts
# ---------------------------------------------------------------------------


class AuctionAlertCreate(WriteModel):
    # Null city or keyword means no filter on that field.
    city: str | None = Field(default=None, max_length=100)
    keyword: str | None = None
    bank_name: str | None = Field(default=None, max_length=200)
    property_type: AuctionPropertyType | None = None
    min_price: Money | None = None
    max_price: Money | None = None


class AuctionAlertResponse(BaseModel):
    id: int
    user_id: int
    city: str | None = None
    keyword: str | None = None
    bank_name: str | None = None
    property_type: AuctionPropertyType | None = None
    min_price: Money | None = None
    max_price: Money | None = None
    is_active: bool
    last_notified_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 5. Bank Rates
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. Jamabandi (land records) — request + response (no ORM model)
# ---------------------------------------------------------------------------


class JamabandiLookupRequest(WriteModel):
    tehsil: str
    village: str
    khasra_number: str
    captcha_text: str


class JamabandiLookupResponse(BaseModel):
    tehsil: str
    village: str
    khasra_number: str
    owner_names: list[str]
    area_kanal: float | None = None
    area_marla: float | None = None
    mutation_status: str | None = None
    encumbrance: str | None = None
    raw_data: dict[str, Any] | None = None
    fetched_at: UtcDateTime
    is_cached: bool


# ---------------------------------------------------------------------------
# 7. Zoning Data
# ---------------------------------------------------------------------------


class ZoningDataResponse(BaseModel):
    id: int
    sector: str
    land_use: str | None = None
    far_limit: float | None = None
    max_height_m: float | None = None
    max_coverage_pct: float | None = None
    permitted_uses: list[str] | None = None
    prohibited_uses: list[str] | None = None
    slug: str
    source_url: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 8. Colony Approvals
# ---------------------------------------------------------------------------


class ColonyApprovalResponse(BaseModel):
    id: int
    colony_name: str
    licence_number: str | None = None
    approval_status: str | None = None
    area_acres: float | None = None
    developer_name: str | None = None
    approval_date: date | None = None
    source_url: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

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
    pdf_text: str | None = None
    pdf_url: str | None = None
    relevance_tags: list[str] | None = None
    relevance_score: float | None = None
    notification_type: GazetteType | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 10. RERA Complaints
# ---------------------------------------------------------------------------


class ReraComplaintResponse(BaseModel):
    id: int
    rera_number: str | None = None
    respondent_project: str | None = None
    respondent_builder: str | None = None
    complainant_type: str | None = None
    complaint_nature: ComplaintNature | None = None
    order_number: str
    order_date: date | None = None
    penalty_amount: Money | None = None
    order_summary: str | None = None
    pdf_url: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 11. Court Auctions
# ---------------------------------------------------------------------------


class CourtAuctionResponse(BaseModel):
    id: int
    case_number: str
    court_name: str | None = None
    kind: AuctionKind = AuctionKind.court
    borrower_name: str | None = None
    property_description: str | None = None
    # Model stores locality (city-level). There is no street address column.
    locality: str | None = None
    reserve_price: Money | None = None
    auction_date: date | None = None
    source: AuctionSource
    source_url: str | None = None
    property_type: AuctionPropertyType | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

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
    nearby_places: list[dict[str, Any]] = Field(default_factory=list)
    metro_stations: list[dict[str, Any]] = Field(default_factory=list)
    schools: list[dict[str, Any]] = Field(default_factory=list)
    hospitals: list[dict[str, Any]] = Field(default_factory=list)
    stale_after: UtcDateTime
    last_fetched_at: UtcDateTime
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

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
    started_at: UtcDateTime
    finished_at: UtcDateTime | None = None
    triggered_by: int | None = None
    run_metadata: dict[str, Any] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> float | None:
        """Compute run duration from started_at / finished_at."""
        if self.finished_at is not None and self.started_at is not None:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Stamp Duty Calculation
# ---------------------------------------------------------------------------


class StampDutyCalculationRequest(WriteModel):
    property_value: float = Field(..., gt=0)
    sector: str | None = None
    buyer_type: Literal["male", "female", "joint"]
    property_type: str | None = None


class StampDutyCalculationResponse(BaseModel):
    property_value: float
    circle_rate_per_sqyd: Money | None = None
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
