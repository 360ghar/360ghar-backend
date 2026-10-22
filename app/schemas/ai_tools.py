"""Bodies of the owner and tenant AI tools: listing draft, virtual staging, legal drafts."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.base import WriteModel

PhotoMime = Literal["image/jpeg", "image/png", "image/webp"]

# ── listing draft ───────────────────────────────────────────────────────────

RoomType = Literal[
    "living_room", "bedroom", "kitchen", "bathroom", "dining_room", "balcony", "exterior",
    "entrance", "study", "parking", "garden", "amenity", "floor_plan", "other",
]  # fmt: skip
FlagCode = Literal[
    "blurry", "dark", "people_visible", "text_or_watermark", "not_a_property", "duplicate_photo",
    "low_resolution", "few_photos", "no_exterior_or_entrance",
]  # fmt: skip


class PhotoIn(WriteModel):
    """One photo: a Cloudinary URL of this account, or base64 with its MIME type."""

    url: str | None = Field(default=None, max_length=600)
    base64: str | None = Field(default=None, max_length=4_200_000, description="Standard base64, up to 3 MB decoded")
    mime_type: PhotoMime | None = None

    @model_validator(mode="after")
    def _one_source(self) -> PhotoIn:
        if (self.url is None) == (self.base64 is None):
            raise ValueError("send exactly one of url or base64")
        return self


class ListingHints(WriteModel):
    """What the owner already knows. Each value is data for the writer, never an instruction."""

    property_type: PropertyType | None = None
    purpose: PropertyPurpose | None = None
    city: str | None = Field(default=None, max_length=100)
    locality: str | None = Field(default=None, max_length=100)
    bedrooms: int | None = Field(default=None, ge=0, le=50)
    bathrooms: int | None = Field(default=None, ge=0, le=50)
    area_sqft: float | None = Field(default=None, gt=0, le=1_000_000)
    furnishing: Literal["furnished", "semi_furnished", "unfurnished"] | None = None
    notes: str | None = Field(default=None, max_length=300)


class ListingDraftRequest(WriteModel):
    photos: list[PhotoIn] = Field(..., min_length=1, max_length=8)
    hints: ListingHints | None = None


class RoomTag(BaseModel):
    photo: int = Field(description="0-based index into the request's photos")
    room_type: RoomType
    label: str = Field(max_length=60)


class ListingFlag(BaseModel):
    code: FlagCode
    photo: int | None = Field(default=None, description="0-based photo index, or null for the whole set")
    note: str = Field(max_length=160)


class ListingDraftResponse(BaseModel):
    title: str
    description: str
    rooms: list[RoomTag]
    flags: list[ListingFlag]


# ── virtual staging ─────────────────────────────────────────────────────────

StageRoom = Literal["living_room", "bedroom", "dining_room", "kitchen", "study", "balcony"]
StageStyle = Literal["modern", "minimalist", "scandinavian", "traditional_indian", "contemporary"]
WATERMARK_TEXT = "Virtually staged"


class StageRequest(WriteModel):
    image: str = Field(..., max_length=7_000_000, description="Base64 of an empty-room photo, up to 5 MB decoded")
    mime_type: PhotoMime | None = None
    room_type: StageRoom = "living_room"
    style: StageStyle = "modern"


class StageResponse(BaseModel):
    image: str = Field(description="A JPEG data URL with the visible watermark")
    staged: Literal[True] = True
    watermark: str = WATERMARK_TEXT


# ── legal drafts ────────────────────────────────────────────────────────────

_FORBIDDEN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f<>{}]")


def _plain(value: str) -> str:
    if _FORBIDDEN.search(value):
        raise ValueError("contains characters that are not allowed")
    return " ".join(value.split())


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100), AfterValidator(_plain)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300), AfterValidator(_plain)]
Place = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100), AfterValidator(_plain)]


class RentAgreementFields(WriteModel):
    landlord_name: Name
    landlord_address: Address
    tenant_name: Name
    tenant_address: Address
    property_address: Address
    city: Place
    state: Place
    monthly_rent: int = Field(..., ge=1, le=10_000_000)
    security_deposit: int = Field(..., ge=0, le=100_000_000)
    start_date: date
    duration_months: int = Field(11, ge=1, le=60)
    rent_due_day: int = Field(5, ge=1, le=28)
    notice_period_days: int = Field(30, ge=7, le=180)
    lock_in_months: int = Field(0, ge=0, le=24)
    annual_increase_percent: int = Field(5, ge=0, le=25)
    furnished: bool = False
    maintenance_by: Literal["tenant", "landlord"] = "tenant"
    additional_terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500), AfterValidator(_plain)] | None = None

    @model_validator(mode="after")
    def _lock_in_within_term(self) -> RentAgreementFields:
        if self.lock_in_months > self.duration_months:
            raise ValueError("lock_in_months cannot be longer than duration_months")
        return self


NoticeType = Literal["rent_arrears", "vacate_premises", "security_deposit_refund", "breach_of_agreement"]


class LegalNoticeFields(WriteModel):
    notice_type: NoticeType
    sender_name: Name
    sender_address: Address
    recipient_name: Name
    recipient_address: Address
    property_address: Address
    agreement_date: date | None = None
    amount: int | None = Field(default=None, ge=1, le=100_000_000, description="Rupees. Needed for rent_arrears and security_deposit_refund")
    compliance_days: int = Field(15, ge=7, le=90)
    facts: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600), AfterValidator(_plain)] | None = None

    @model_validator(mode="after")
    def _amount_when_needed(self) -> LegalNoticeFields:
        if self.notice_type in ("rent_arrears", "security_deposit_refund") and self.amount is None:
            raise ValueError("amount is required for this notice_type")
        return self


class RentAgreementDraft(WriteModel):
    kind: Literal["rent_agreement"]
    fields: RentAgreementFields


class LegalNoticeDraft(WriteModel):
    kind: Literal["legal_notice"]
    fields: LegalNoticeFields


LegalDraftRequest = Annotated[RentAgreementDraft | LegalNoticeDraft, Field(discriminator="kind")]

DISCLAIMER = (
    "This is a draft for general information. It is not legal advice. "
    "Have a lawyer review it before you sign it or send it."
)


class LegalSection(BaseModel):
    heading: str
    body: str


class LegalDraftResponse(BaseModel):
    kind: Literal["rent_agreement", "legal_notice"]
    title: str
    sections: list[LegalSection]
    disclaimer: str = Field(default=DISCLAIMER, description="Fixed text. Show it with the draft.")
    narrative_source: Literal["model", "template"] = Field(
        description="model when the model reworded your free text, template when your text is used as written"
    )
