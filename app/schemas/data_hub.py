"""
Pydantic v2 schemas for the 360Ghar Data Hub feature.

Covers all 13 data hub entities plus calculation, builder reputation,
and paginated list response schemas.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, computed_field

from app.models.enums import (
    AuctionKind,
    AuctionPropertyType,
    AuctionSource,
    ComplaintNature,
    GazetteType,
    MarketSentiment,
    ProjectPersonRole,
    ProjectPriceSource,
    ProjectStage,
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


class DataHubProvenanceSource(BaseModel):
    """Public-safe source metadata; never includes content, artifacts, or reviewer notes."""

    authority: str
    citation_url: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    checked_at: UtcDateTime


class DataHubProvenanceSummary(BaseModel):
    """Public-safe source metadata and explicit verification status."""

    verification_status: Literal["unverified", "verified"] = "unverified"
    sources: list[DataHubProvenanceSource] = Field(default_factory=list)


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
    # The public URL key of the project-intelligence page (`/project/{slug}`).
    # Null for a row whose filing named no project name to build one from; those
    # rows have no page to link to, so a list must render them unlinked rather
    # than point at a 404. See `POST /data-hub/watchlist`, which refuses one for
    # the same reason.
    slug: str | None = None
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
    provenance: DataHubProvenanceSummary | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# 3. Bank Auctions
# ---------------------------------------------------------------------------


class ReraVerifyResult(BaseModel):
    valid: bool | None = None
    verification_status: Literal["unknown", "unverified", "verified"] = "unknown"
    status: str | None = None
    project_name: str | None = None
    official_source_url: str | None = None


class ScraperTriggerResult(BaseModel):
    message: str
    result: Any = None


class ScraperTriggerRequest(BaseModel):
    """Operator arguments for a manual scraper trigger.

    Only ``rera_portal_scan`` reads these. It walks a range of HRERA portal ids and
    refuses to run without an ``end_id``, so the range has to come from the
    operator rather than from a default. Every other scraper ignores the body, and
    an option a scraper does not accept is dropped rather than passed on.
    """

    start_id: int | None = Field(default=None, ge=1)
    end_id: int | None = Field(default=None, ge=1)
    delay_seconds: float | None = Field(default=None, ge=0, le=30)


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
    provenance: DataHubProvenanceSummary | None = None
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
    provenance: DataHubProvenanceSummary | None = None
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


# ---------------------------------------------------------------------------
# Project intelligence (Phase 3): projects, developers, micro-markets, watchlist
# ---------------------------------------------------------------------------


class ProjectProfileResponse(BaseModel):
    """REP-I filing profile scalars. Never carries contact details."""

    portal_project_id: str | None = None
    licensed_land_acres: float | None = None
    land_area_sqm: float | None = None
    proposed_far: float | None = None
    permissible_far: float | None = None
    towers: int | None = None
    floors: int | None = None
    total_units: int | None = None
    units_per_acre: float | None = None
    rera_received_date: date | None = None
    construction_start_date: date | None = None
    proposed_completion_date: date | None = None
    launch_price_per_sqft: float | None = None
    current_price_per_sqft: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    stage: ProjectStage | None = None

    model_config = ConfigDict(from_attributes=True)


class LandUsageResponse(BaseModel):
    particular: str
    area_sqm: float | None = None
    area_acres: float | None = None
    percentage: float | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectCostResponse(BaseModel):
    land_cost: Money | None = None
    construction_cost: Money | None = None
    infrastructure_cost: Money | None = None
    other_cost: Money | None = None
    total_cost: Money | None = None

    model_config = ConfigDict(from_attributes=True)


class QuarterlyExpenditureResponse(BaseModel):
    category: str
    year: int
    quarter: int
    particular: str
    amount: Money | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectDocumentResponse(BaseModel):
    ordinal: int
    description: str
    uploaded_on: date | None = None
    view_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StatutoryApprovalResponse(BaseModel):
    loi_number: str | None = None
    loi_date: date | None = None
    licence_number: str | None = None
    licence_date: date | None = None
    electric_load_kw: float | None = None
    water_available: bool | None = None
    storm_water_available: bool | None = None
    sewerage_available: bool | None = None
    plan_approvals: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class FacilityResponse(BaseModel):
    facility: str
    estimated_cost: Money | None = None
    status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class NocResponse(BaseModel):
    facility: str
    provider_agency: str | None = None
    approved: bool | None = None
    approval_reference: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectPersonResponse(BaseModel):
    """Promoter-side person. Contact details (email, phones, address) are never serialized."""

    role: ProjectPersonRole
    name: str
    pan_last4: str | None = None
    photo_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class BankAccountResponse(BaseModel):
    """Project collection account. The account number and operators are never serialized."""

    bank_name: str | None = None
    branch_name: str | None = None
    ifsc: str | None = None
    micr: str | None = None
    branch_code: str | None = None

    model_config = ConfigDict(from_attributes=True)


class UnitConfigResponse(BaseModel):
    ordinal: int
    unit_type: str
    carpet_area_sqm: float | None = None
    built_up_area_sqm: float | None = None
    super_built_up_area_sqm: float | None = None
    carpet_efficiency: float | None = None
    units: int | None = None
    towers: int | None = None
    parkings: int | None = None
    price: Money | None = None

    model_config = ConfigDict(from_attributes=True)


class SpecificationResponse(BaseModel):
    scope: str
    unit_type: str
    spec_key: str
    spec_value: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PricePointResponse(BaseModel):
    quarter: str
    period_start: date | None = None
    unit_type: str
    price_per_sqft: float | None = None
    source: ProjectPriceSource

    model_config = ConfigDict(from_attributes=True)


class FaqItemResponse(BaseModel):
    question: str
    answer: str


class ProjectFaqResponse(BaseModel):
    items: list[FaqItemResponse] = Field(default_factory=list)


class ProjectSummaryResponse(BaseModel):
    """List-level project card. Field names are frozen: the web UI codes against them."""

    id: int
    slug: str
    rera_number: str
    project_name: str
    developer_name: str | None = None
    developer_slug: str | None = None
    location: str | None = None
    district: str
    stage: ProjectStage | None = None
    total_units: int | None = None
    towers: int | None = None
    land_area_acres: float | None = None
    proposed_far: float | None = None
    proposed_completion_date: date | None = None
    current_price_per_sqft: float | None = None
    possession_date: date | None = None
    status: str | None = None
    complaint_count: int = 0
    source_url: str | None = None
    updated_at: UtcDateTime
    provenance: DataHubProvenanceSummary | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectDetailResponse(ProjectSummaryResponse):
    """Every summary field plus the full filing. Contact details are never included."""

    profile: ProjectProfileResponse | None = None
    land_usage: list[LandUsageResponse] = Field(default_factory=list)
    cost: ProjectCostResponse | None = None
    expenditure: list[QuarterlyExpenditureResponse] = Field(default_factory=list)
    documents: list[ProjectDocumentResponse] = Field(default_factory=list)
    statutory: StatutoryApprovalResponse | None = None
    facilities: list[FacilityResponse] = Field(default_factory=list)
    nocs: list[NocResponse] = Field(default_factory=list)
    people: list[ProjectPersonResponse] = Field(default_factory=list)
    bank_account: BankAccountResponse | None = None
    unit_configs: list[UnitConfigResponse] = Field(default_factory=list)
    specifications: list[SpecificationResponse] = Field(default_factory=list)
    nearby: list[ProjectSummaryResponse] = Field(default_factory=list)
    price_history: list[PricePointResponse] = Field(default_factory=list)
    faq: list[FaqItemResponse] = Field(default_factory=list)


class ProjectMapPointResponse(BaseModel):
    """One project pin. Only projects with filed coordinates are returned."""

    slug: str
    project_name: str
    developer_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    stage: ProjectStage | None = None


class DeveloperSummaryResponse(BaseModel):
    id: int
    slug: str
    name: str
    legal_name: str | None = None
    logo_url: str | None = None
    website_url: str | None = None
    headquarters: str | None = None
    founded_year: int | None = None
    is_listed: bool | None = None
    total_score: float | None = None
    project_count: int = 0
    complaint_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class DeveloperScoreResponse(BaseModel):
    delivery: float | None = None
    regulatory: float | None = None
    complaints: float | None = None
    financials: float | None = None
    market_reception: float | None = None
    total_score: float | None = None
    project_count: int = 0
    delivered_count: int = 0
    under_construction_count: int = 0
    complaint_count: int = 0
    computed_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class DeveloperDetailResponse(DeveloperSummaryResponse):
    summary: str | None = None
    dossier: str | None = None
    cin: str | None = None
    geographies: list[str] | None = None
    score: DeveloperScoreResponse | None = None
    projects: list[ProjectSummaryResponse] = Field(default_factory=list)


class MicroMarketResponse(BaseModel):
    id: int
    city: str
    name: str
    slug: str
    district: str | None = None
    summary: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    model_config = ConfigDict(from_attributes=True)


class MicroMarketDetailResponse(MicroMarketResponse):
    project_count: int = 0
    avg_price_per_sqft: float | None = None
    stage_breakdown: dict[str, int] = Field(default_factory=dict)


class MarketPulseResponse(BaseModel):
    city: str
    captured_on: date
    sentiment: MarketSentiment
    avg_price_per_sqft: float | None = None
    price_change_90d_pct: float | None = None
    # ``None`` means the reading was not taken, which is not the same as ``0``.
    # The Delhi register states no registration date, and no complaint has ever
    # been collected, so both counts are unknown rather than zero.
    new_registrations: int | None = None
    new_complaints: int | None = None
    computed_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class WatchlistItemCreate(WriteModel):
    """Watchlist body. Unknown keys fail with 422."""

    project_id: int
    notes: str | None = None
    # Keys are the watchlist alert type keys; values must be real booleans, so a
    # client cannot send "false" or 0 and still receive the alert.
    alert_prefs: (
        dict[
            Literal[
                "watchlist_price_change",
                "watchlist_stage_change",
                "watchlist_possession_change",
                "watchlist_new_filing",
            ],
            StrictBool,
        ]
        | None
    ) = None


class WatchlistItemResponse(BaseModel):
    id: int
    # Model column is rera_project_id; the public name is project_id.
    project_id: int
    notes: str | None = None
    alert_prefs: dict[str, Any] | None = None
    created_at: UtcDateTime
    project: ProjectSummaryResponse | None = None

    model_config = ConfigDict(from_attributes=True)
