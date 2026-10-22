from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.models.enums import (
    PG_FLATMATE_TYPES,
    FurnishingLevel,
    ImageCategory,
    KitchenType,
    ListingGenderPreference,
    ListingSharingType,
    ManagedPropertyStatus,
    MoveInTimeline,
    PropertyPurpose,
    PropertyStatus,
    PropertyType,
    VentilationType,
)
from app.schemas.amenity import PropertyAmenityResponse
from app.schemas.base import Money, NotNullable, PatchModel, UtcDateTime, WriteModel
from app.utils.validators import ValidationUtils

# One cap for every money field on create and update. 9999999999.99 is the largest
# value NUMERIC(12,2) holds, so the database and the API agree.
BASE_PRICE_MAX = 9_999_999_999.99


def _normalize_furnishing_level(v: object) -> object:
    """Coerce legacy furnishing strings to the canonical column contract.

    The DB column is free-form ``VARCHAR(32)`` and holds legacy values such
    as ``fully-furnished`` / ``Fully Furnished`` / ``semi-furnished``. Normalize
    known variants to the canonical ``FurnishingLevel`` values and coerce
    empty/unknown input to ``None`` so a single dirty row never breaks search.
    """
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    normalized = v.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return None
    if normalized in {"furnished", "fully_furnished", "fullyfurnished", "full_furnished"}:
        return FurnishingLevel.furnished.value
    if normalized in {
        "semi_furnished",
        "semifurnished",
        "partially_furnished",
        "partly_furnished",
    }:
        return FurnishingLevel.semi_furnished.value
    if normalized in {"unfurnished", "none"}:
        return FurnishingLevel.unfurnished.value
    return None


def _date_only(value: object) -> object:
    """Accept a date, or a datetime stored as UTC midnight, and return the UTC date."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date()
    return value


class ListingPreferences(BaseModel):
    """Listing preferences stored in properties.listing_preferences (JSONB).

    Moderator keys (moderated_by, moderation_reason, ai_prescreen_*, auto_paused_*)
    are not declared here. They are kept in the stored dict and returned to admins
    only. See ``app.services.visibility.mask_listing_preferences``.
    """

    gender_preference: ListingGenderPreference | None = None
    sharing_type: ListingSharingType | None = None
    moderation_status: str | None = None
    expires_at: str | None = None
    food_habits: str | None = None
    smoking_drinking: str | None = None
    guests_policy: str | None = None
    cleanliness: str | None = None
    pets: str | None = None
    parties_at_home: str | None = None

    model_config = ConfigDict(from_attributes=True, extra="allow")


class PropertyImageBase(BaseModel):
    image_url: str
    caption: str | None = None
    image_category: ImageCategory = ImageCategory.others
    display_order: int = 0
    is_main_image: bool = False


class PropertyImage(PropertyImageBase):
    id: int
    property_id: int

    model_config = ConfigDict(from_attributes=True)


# Money input: NUMERIC(12,2) on the database side. Negative values and values above
# BASE_PRICE_MAX fail with 422.
MoneyInput = Annotated[Money, Field(ge=0, le=BASE_PRICE_MAX)]


class PropertyFields(PatchModel):
    """Writable listing fields. Shared by ``PropertyCreate`` and ``PropertyUpdate``.

    Every field is optional here. ``NotNullable`` marks the fields that must never
    be cleared, so an explicit ``null`` on a PATCH gives 422. ``PropertyCreate``
    makes the required fields mandatory.
    """

    title: Annotated[str | None, NotNullable] = Field(
        default=None,
        description="Listing title shown in search results and detail pages",
        examples=["2BHK Apartment in Koramangala"],
    )
    description: str | None = Field(
        default=None,
        description="Detailed description of the property (HTML/markdown allowed)",
        examples=["Spacious 2BHK with balcony, near metro station"],
    )
    property_type: Annotated[PropertyType | None, NotNullable] = Field(
        default=None,
        description="Listing category (apartment, villa, pg, flatmate, etc.)",
        examples=["apartment"],
    )
    purpose: Annotated[PropertyPurpose | None, NotNullable] = Field(
        default=None,
        description="Listing intent: buy, rent, or short_stay",
        examples=["rent"],
    )
    base_price: Annotated[MoneyInput | None, NotNullable] = Field(
        default=None,
        description="Sale price for purpose buy. Also the monthly rent anchor for rent listings.",
        examples=[50000],
    )
    status: Annotated[PropertyStatus | None, NotNullable] = Field(
        default=None,
        description="Listing lifecycle status (available, sold, rented, under_offer, maintenance)",
        examples=["available"],
    )
    is_available: Annotated[bool | None, NotNullable] = None

    # Location
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    city: str | None = Field(
        default=None,
        description="City where the property is located",
        examples=["Bengaluru"],
    )
    state: str | None = None
    country: Annotated[str | None, NotNullable] = None
    pincode: str | None = None
    locality: str | None = Field(
        default=None,
        description="Neighbourhood or locality within the city",
        examples=["Koramangala"],
    )
    sub_locality: str | None = None
    landmark: str | None = None
    full_address: str | None = None
    area_type: str | None = None

    # Details
    area_sqft: float | None = Field(default=None, ge=0, le=1_000_000)
    bedrooms: int | None = Field(default=None, ge=0, le=50)
    bathrooms: int | None = Field(default=None, ge=0, le=50)
    balconies: int | None = Field(default=None, ge=0, le=50)
    parking_spaces: int | None = Field(default=None, ge=0, le=100)
    floor_number: int | None = Field(default=None, ge=-5, le=200)
    total_floors: int | None = Field(default=None, ge=0, le=200)
    age_of_property: int | None = Field(default=None, ge=0, le=500)
    max_occupancy: int | None = Field(default=None, ge=0, le=1000)
    # NOT NULL in the database (migration 20261014001004). Null gives 422 on create and update.
    minimum_stay_days: Annotated[int | None, NotNullable] = Field(default=None, ge=1, le=3650)

    # Pricing. The price field used depends on purpose: rent -> monthly_rent,
    # short_stay -> daily_rate, buy -> base_price. price_per_sqft is computed on read.
    monthly_rent: MoneyInput | None = None
    daily_rate: MoneyInput | None = None
    security_deposit: MoneyInput | None = None
    maintenance_charges: MoneyInput | None = None
    setup_cost: MoneyInput | None = None
    other_charges: MoneyInput | None = None
    other_charges_description: str | None = Field(default=None, max_length=300)

    # Features and media
    features: list[str] | None = None
    amenity_ids: list[int] | None = None
    listing_preferences: ListingPreferences | None = None
    calendar_data: dict[str, Any] | None = None
    main_image_url: str | None = None
    image_urls: list[str] | None = None
    video_urls: list[str] | None = None
    virtual_tour_url: str | None = None
    floor_plan_url: str | None = None
    video_tour_url: str | None = None
    google_street_view_url: str | None = None

    # Flatmates listing enhancements
    kitchen_type: KitchenType | None = None
    ventilation_type: VentilationType | None = None
    windows_count: int | None = Field(default=None, ge=0, le=100)
    ventilation_shafts: int | None = Field(default=None, ge=0, le=50)
    furnishing_level: FurnishingLevel | None = None

    # Owner and marketing
    owner_name: str | None = None
    owner_contact: str | None = None
    builder_name: str | None = None
    search_keywords: str | None = None
    tags: list[str] | None = None
    available_from: date | None = Field(
        default=None, description="Date the listing is available from (YYYY-MM-DD)."
    )

    # Flatmate listing preferences. The service stores these in listing_preferences (JSONB).
    gender_preference: ListingGenderPreference | None = None
    sharing_type: ListingSharingType | None = None
    society_type: str | None = None
    society_amenities: list[str] | None = None
    society_vibe_tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            return ValidationUtils.sanitize_string(v, max_length=200)
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v:
            return ValidationUtils.sanitize_html(v)
        return v

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str | None) -> str | None:
        if v:
            return ValidationUtils.validate_pincode(v)
        return v

    @field_validator("video_urls", "image_urls")
    @classmethod
    def validate_media_urls(cls, v: list[str] | None) -> list[str] | None:
        if v:
            ValidationUtils.validate_list_input(v, max_items=50)
            cleaned = []
            for url in v:
                if not url:
                    continue
                url_str = str(url).strip()
                if url_str:
                    cleaned.append(url_str[:500])
            return cleaned or None
        return v

    @field_validator("google_street_view_url")
    @classmethod
    def sanitize_street_view_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = str(v).strip()
            return sanitized[:500] if sanitized else None
        return v


class PropertyCreate(PropertyFields):
    """POST /properties body. Required: title, property_type, purpose, base_price."""

    title: str = Field(
        ...,
        description="Listing title shown in search results and detail pages",
        examples=["2BHK Apartment in Koramangala"],
    )
    property_type: PropertyType = Field(
        ...,
        description="Listing category (apartment, villa, pg, flatmate, etc.)",
        examples=["apartment"],
    )
    purpose: PropertyPurpose = Field(
        ...,
        description="Listing intent: buy, rent, or short_stay",
        examples=["rent"],
    )
    base_price: MoneyInput = Field(
        ...,
        description="Sale price for purpose buy. Also the monthly rent anchor for rent listings.",
        examples=[50000],
    )
    country: str = "India"
    # Not null: the database column is NOT NULL. Omitted means 1; explicit null gives 422.
    minimum_stay_days: Annotated[int, NotNullable] = Field(default=1, ge=1, le=3650)

    @field_validator("purpose")
    @classmethod
    def validate_pg_flatmate_purpose(
        cls, value: PropertyPurpose, info: ValidationInfo
    ) -> PropertyPurpose:
        # A field error (loc body.purpose), so the client maps it to the purpose field.
        if info.data.get("property_type") in PG_FLATMATE_TYPES and value != PropertyPurpose.rent:
            raise PydanticCustomError(
                "listing_purpose", "PG and flatmate listings must use purpose 'rent'"
            )
        return value

    @model_validator(mode="after")
    def validate_listing_rules(self):
        is_rent_listing = (
            self.purpose == PropertyPurpose.rent or self.property_type in PG_FLATMATE_TYPES
        )
        if is_rent_listing and (self.monthly_rent is None or self.monthly_rent <= 0):
            raise ValueError("monthly_rent must be a positive number for rent/flatmate/PG listings")
        return self


class PropertyUpdate(PropertyFields):
    """PATCH /properties/{id} body. Send only the keys to change. Explicit null clears
    a nullable field. Null on a NotNullable field gives 422."""


class PropertyInDB(BaseModel):
    """Listing as returned by the API. Output only; the write shape is PropertyFields."""

    id: int
    owner_id: int
    title: str
    description: str | None = None
    property_type: PropertyType
    purpose: PropertyPurpose
    status: PropertyStatus

    # Price fields. price_per_sqft and nightly_rate are computed (see _derive_prices).
    base_price: float
    price_per_sqft: float | None = None
    monthly_rent: float | None = None
    daily_rate: float | None = None
    nightly_rate: float | None = None
    security_deposit: float | None = None
    maintenance_charges: float | None = None
    setup_cost: float | None = None
    other_charges: float | None = None
    other_charges_description: str | None = None

    latitude: float | None = None
    longitude: float | None = None
    city: str | None = None
    state: str | None = None
    country: str = "India"
    pincode: str | None = None
    locality: str | None = None
    sub_locality: str | None = None
    landmark: str | None = None
    full_address: str | None = None
    area_type: str | None = None
    area_sqft: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    balconies: int | None = None
    parking_spaces: int | None = None
    floor_number: int | None = None
    total_floors: int | None = None
    age_of_property: int | None = None
    max_occupancy: int | None = None
    minimum_stay_days: int | None = None

    features: list[str] | None = None
    listing_preferences: ListingPreferences | None = None
    video_urls: list[str] | None = None
    main_image_url: str | None = None
    virtual_tour_url: str | None = None
    floor_plan_url: str | None = None
    video_tour_url: str | None = None
    google_street_view_url: str | None = None
    kitchen_type: KitchenType | None = None
    ventilation_type: VentilationType | None = None
    windows_count: int | None = None
    ventilation_shafts: int | None = None
    furnishing_level: FurnishingLevel | None = None

    owner_name: str | None = None
    owner_contact: str | None = None
    builder_name: str | None = None
    search_keywords: str | None = None
    tags: list[str] | None = None
    calendar_data: dict[str, Any] | None = None

    is_available: bool
    available_from: date | None = None
    view_count: int
    like_count: int
    interest_count: int

    # Property Management
    is_managed: bool = False
    management_status: ManagedPropertyStatus | None = None
    payment_due_day: int | None = None
    grace_period_days: int | None = None
    late_fee_policy: dict[str, Any] | None = None
    current_lease_id: int | None = None
    current_tenant_id: int | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _derive_prices(self):
        """price_per_sqft is the purpose price divided by the area. nightly_rate is the
        per-night price for short stays."""
        if self.purpose == PropertyPurpose.rent:
            price = self.monthly_rent
        elif self.purpose == PropertyPurpose.short_stay:
            price = self.daily_rate
        else:
            price = self.base_price
        if price and self.area_sqft and self.area_sqft > 0:
            self.price_per_sqft = round(price / self.area_sqft, 2)
        else:
            self.price_per_sqft = None
        self.nightly_rate = self.daily_rate if self.purpose == PropertyPurpose.short_stay else None
        return self

    @field_validator("available_from", mode="before")
    @classmethod
    def coerce_available_from(cls, v: object) -> object:
        return _date_only(v)

    @field_validator("furnishing_level", mode="before")
    @classmethod
    def normalize_furnishing_level(cls, v: object) -> object:
        # Legacy rows hold values such as "fully-furnished". One such row must not fail a page.
        return _normalize_furnishing_level(v)

    @field_validator(
        "main_image_url",
        "floor_plan_url",
        "video_tour_url",
        "virtual_tour_url",
        "google_street_view_url",
        mode="before",
    )
    @classmethod
    def strip_relative_urls(cls, v: object) -> str | None:
        """Blank out relative paths so the app never builds a localhost URL from them."""
        if isinstance(v, str) and v and not ValidationUtils.is_absolute_url(v):
            return None
        return v  # type: ignore[return-value]

    @field_validator("features", mode="before")
    @classmethod
    def coerce_features(cls, v: object) -> list[str] | None:
        # Stored as arrays since migration 20261014001001. Object-form values are not read.
        if isinstance(v, list):
            return [str(i) for i in v if i is not None]
        return None

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_tags(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(i) for i in v if i is not None]
        return None

    @field_validator("video_urls", mode="before")
    @classmethod
    def coerce_video_urls(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(i) for i in v if i is not None]
        return None

    @field_validator("management_status", mode="before")
    @classmethod
    def coerce_management_status(cls, v: object) -> ManagedPropertyStatus:
        if v is None:
            return ManagedPropertyStatus.active
        return v  # type: ignore[return-value]

    @field_validator("payment_due_day", "grace_period_days", mode="before")
    @classmethod
    def coerce_pm_int_defaults(cls, v: object, info: ValidationInfo) -> int:
        if v is None:
            return 1 if info.field_name == "payment_due_day" else 5
        return v  # type: ignore[return-value]

    @field_validator("calendar_data", "late_fee_policy", mode="before")
    @classmethod
    def coerce_json_dict(cls, v: object) -> dict | None:
        if isinstance(v, dict):
            return v
        return None

    @field_validator(
        "base_price",
        "price_per_sqft",
        "monthly_rent",
        "daily_rate",
        "security_deposit",
        "maintenance_charges",
        "setup_cost",
        "other_charges",
        mode="before",
    )
    @classmethod
    def coerce_decimal(cls, v: object) -> float | None:
        if v is None:
            return None
        return float(v)  # type: ignore[arg-type]


class PropertyAgent(BaseModel):
    """The 360 Ghar agent who looks after the listing owner. Public fields only."""

    id: int
    name: str
    contact_number: str | None = None
    avatar_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class Property(PropertyInDB):
    # attach_owner_agents sets this, and masking reads it to show the agent's number to
    # non-owners. exclude=True keeps it off list, search, recommendation and write responses.
    # PropertyDetail shows it, because only the detail screen reads it.
    agent: PropertyAgent | None = Field(default=None, exclude=True)
    # images holds the photos. floor_plans holds the floor_plan category rows. The
    # split happens in _split_floor_plans, so both lists come from one relationship.
    images: list[PropertyImage] | None = None
    floor_plans: list[PropertyImage] | None = None
    # Read from the ORM relationship (`property_amenities`) and from a cached dump (`amenities`).
    amenities: list[PropertyAmenityResponse] | None = Field(
        None, validation_alias=AliasChoices("property_amenities", "amenities")
    )
    distance_km: float | None = None  # For location-based searches
    liked: bool | None = None  # For swipe history - indicates if user liked this property
    compatibility_score: float | None = None  # Auth-aware score vs current user

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _split_floor_plans(self):
        if self.images:
            plans = [i for i in self.images if i.image_category == ImageCategory.floor_plan]
            if plans:
                self.floor_plans = plans + (self.floor_plans or [])
                self.images = [
                    i for i in self.images if i.image_category != ImageCategory.floor_plan
                ]
        return self

    def cache_payload(self) -> dict[str, Any]:
        """The cached form of this listing. It keeps the agent, which read-time masking
        needs to show the agent's number on a cache hit. The wire dump drops it."""
        data = self.model_dump(mode="json")
        data["agent"] = self.agent.model_dump(mode="json") if self.agent else None
        return data


class PropertyDetail(Property):
    """GET /properties/{id} response. The viewer's own visit fields exist only here.

    They describe the requesting user's visits, not the listing, so list and search
    responses do not carry them. The agent is shown here only, because the detail
    screen reads it.
    """

    agent: PropertyAgent | None = None
    user_has_scheduled_visit: bool | None = None
    user_scheduled_visit_count: int | None = None
    user_next_visit_date: UtcDateTime | None = None


class PropertySwipe(BaseModel):
    property_id: int
    is_liked: bool


class SortBy(str, Enum):
    distance = "distance"
    price_low = "price_low"
    price_high = "price_high"
    newest = "newest"
    popular = "popular"
    relevance = "relevance"


class UnifiedPropertyFilter(BaseModel):
    """Search filters for GET /properties and the swipe feed. Every field here
    changes the result set, so every field is part of the cursor binding."""

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: int = Field(default=5, ge=1, le=100)

    # Text search field
    search_query: str | None = None

    property_ids: list[int] | None = None
    property_type: list[PropertyType] | None = None
    purpose: PropertyPurpose | None = None
    status: PropertyStatus | None = None
    price_min: float | None = Field(default=None, ge=0, le=BASE_PRICE_MAX)
    price_max: float | None = Field(default=None, ge=0, le=BASE_PRICE_MAX)
    bedrooms_min: int | None = Field(default=None, ge=0, le=50)
    bedrooms_max: int | None = Field(default=None, ge=0, le=50)
    bathrooms_min: int | None = Field(default=None, ge=0, le=50)
    bathrooms_max: int | None = Field(default=None, ge=0, le=50)
    area_min: float | None = Field(default=None, ge=0, le=1_000_000)
    area_max: float | None = Field(default=None, ge=0, le=1_000_000)
    parking_spaces_min: int | None = Field(default=None, ge=0, le=100)
    floor_number_min: int | None = Field(default=None, ge=-5, le=200)
    floor_number_max: int | None = Field(default=None, ge=-5, le=200)
    age_max: int | None = Field(default=None, ge=0, le=500)

    city: str | None = None
    # Exact match, case-insensitive. Substring match is only in search_query.
    locality: str | None = None
    sub_locality: str | None = None
    pincode: str | None = None
    society_type: str | None = None
    society_vibe_tags: list[str] | None = None
    amenities: list[str] | None = None
    features: list[str] | None = None
    furnishing: list[FurnishingLevel] | None = None
    kitchen_type: list[KitchenType] | None = None
    ventilation_type: list[VentilationType] | None = None
    windows_min: int | None = Field(default=None, ge=0, le=100)
    has_lift: bool | None = None
    gender_preference: ListingGenderPreference | None = None
    sharing_type: ListingSharingType | None = None

    available_from: date | None = None
    move_in: MoveInTimeline | None = None
    # ISO dates (YYYY-MM-DD). The filter builder parses them and gives 422 when they are invalid.
    check_in_date: str | None = None
    check_out_date: str | None = None
    guests: int | None = Field(default=None, ge=1, le=20)

    sort_by: SortBy | None = SortBy.distance
    include_unavailable: bool = False
    # Authentication-aware filters
    # When true and user is authenticated, excludes properties the user has already swiped
    exclude_swiped: bool = False
    semantic_search: bool = False

    @model_validator(mode="after")
    def validate_range_consistency(self):
        """Ensure min values do not exceed max values for paired range fields."""
        _RANGE_PAIRS = [
            ("price_min", "price_max"),
            ("bedrooms_min", "bedrooms_max"),
            ("bathrooms_min", "bathrooms_max"),
            ("area_min", "area_max"),
            ("floor_number_min", "floor_number_max"),
        ]
        for min_field, max_field in _RANGE_PAIRS:
            min_val = getattr(self, min_field)
            max_val = getattr(self, max_field)
            if min_val is not None and max_val is not None and min_val > max_val:
                raise ValueError(f"{min_field} ({min_val}) must not exceed {max_field} ({max_val})")
        return self


class NLSearchRequest(WriteModel):
    """Body of POST /properties/nl-search."""

    q: str = Field(..., min_length=1, max_length=300, description="The search, in the visitor's own words")

    @field_validator("q")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("q must not be blank")
        return value


class NLSearchResponse(BaseModel):
    """Filters for GET /properties and one sentence saying what was searched."""

    filters: dict[str, Any] = Field(description="Query parameters of GET /properties, as sent")
    explanation: str
