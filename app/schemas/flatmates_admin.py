"""Admin flatmates response models and serialization helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    ListingModerationStatus,
    ReportAction,
    UserReportReason,
    UserReportStatus,
)
from app.models.properties import Property
from app.models.social import UserReport
from app.models.users import User
from app.schemas.base import Money, UtcDateTime
from app.services.flatmates.helpers import age_bucket_for_age, resolve_profile_age


class FlatmateAdminUser(BaseModel):
    id: int
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    profile_image_url: str | None = None
    flatmates_smoking: str | None = None
    flatmates_drinking: str | None = None
    native_place: str | None = None
    linkedin_url: str | None = None
    age_bucket: str | None = None


class FlatmateAdminImage(BaseModel):
    id: int
    image_url: str
    caption: str | None = None
    display_order: int | None = None
    is_main_image: bool | None = None


class FlatmateListingAdmin(BaseModel):
    id: int
    title: str | None = None
    description: str | None = None
    property_type: str | None = None
    purpose: str | None = None
    property_status: str | None = None
    # The queue filters on these values, so every row carries one of the four enum values.
    moderation_status: ListingModerationStatus
    status: ListingModerationStatus
    monthly_rent: Money | None = None
    security_deposit: Money | None = None
    maintenance_charges: Money | None = None
    area_sqft: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    features: list[str] = Field(default_factory=list)
    images: list[FlatmateAdminImage] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    city: str | None = None
    locality: str | None = None
    sub_locality: str | None = None
    main_image_url: str | None = None
    owner_id: int | None = None
    owner: FlatmateAdminUser | None = None
    is_available: bool | None = None
    tags: list[str] = Field(default_factory=list)
    gender_preference: str | None = None
    sharing_type: str | None = None
    available_from: UtcDateTime | None = None
    listing_preferences: dict[str, Any] = Field(default_factory=dict)
    ai_prescreen_result: str | None = None
    ai_prescreen_flags: list[dict[str, Any]] = Field(default_factory=list)
    ai_flag_reason: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None


class FlatmateReportAdmin(BaseModel):
    id: int
    reporter_user_id: int
    reported_user_id: int
    conversation_id: int | None = None
    property_id: int | None = None
    reason: UserReportReason
    status: UserReportStatus
    # Reporter's text. Moderator output is in moderator_notes.
    notes: str | None = None
    moderator_notes: str | None = None
    moderated_by: int | None = None
    moderated_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None
    reporter: FlatmateAdminUser | None = None
    reported_user: FlatmateAdminUser | None = None


class ListingModerationResult(BaseModel):
    listing_id: int
    action: str
    status: str
    reason: str | None = None


class ReportModerationResult(BaseModel):
    report_id: int
    action: ReportAction
    status: UserReportStatus
    moderator_notes: str | None = None


class ListingPrescreenResult(BaseModel):
    listing_id: int
    prescreen_result: str
    flags: list[dict[str, Any]] = Field(default_factory=list)
    flagged: bool
    flag_reason: str | None = None
    photo_count: int
    prescreened_at: UtcDateTime


def serialize_user_summary(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "profile_image_url": user.profile_image_url,
        "flatmates_smoking": getattr(user, "flatmates_smoking", None),
        "flatmates_drinking": getattr(user, "flatmates_drinking", None),
        "native_place": getattr(user, "native_place", None),
        "linkedin_url": getattr(user, "linkedin_url", None),
        "age_bucket": age_bucket_for_age(resolve_profile_age(user)),
    }


def serialize_flatmate_listing(listing: Property) -> dict[str, Any]:
    preferences = (
        dict(listing.listing_preferences) if isinstance(listing.listing_preferences, dict) else {}
    )
    moderation_status = preferences.get("moderation_status", "pending_review")
    raw_images = listing.__dict__.get("images") or []
    sorted_images = sorted(
        raw_images,
        key=lambda image: (
            getattr(image, "display_order", 0) or 0,
            getattr(image, "id", 0) or 0,
        ),
    )
    images = [
        {
            "id": image.id,
            "image_url": image.image_url,
            "caption": image.caption,
            "display_order": image.display_order,
            "is_main_image": image.is_main_image,
        }
        for image in sorted_images
        if image.image_url
    ]
    image_urls = []
    seen_image_urls: set[str] = set()
    for raw_url in [listing.main_image_url, *(image["image_url"] for image in images)]:
        if not raw_url or raw_url in seen_image_urls:
            continue
        seen_image_urls.add(raw_url)
        image_urls.append(raw_url)
    raw_features: Any = listing.features or []
    if isinstance(raw_features, list):
        features = [str(feature) for feature in raw_features]
    elif isinstance(raw_features, dict):
        features = [str(key) for key, value in raw_features.items() if value]
    else:
        features = []
    return {
        "id": listing.id,
        "title": listing.title,
        "description": listing.description,
        "property_type": listing.property_type,
        "purpose": listing.purpose,
        "property_status": listing.status,
        "moderation_status": moderation_status,
        "status": moderation_status,
        "monthly_rent": listing.monthly_rent,
        "security_deposit": listing.security_deposit,
        "maintenance_charges": listing.maintenance_charges,
        "area_sqft": listing.area_sqft,
        "bedrooms": listing.bedrooms,
        "bathrooms": listing.bathrooms,
        "features": features,
        "images": images,
        "image_urls": image_urls,
        "city": listing.city,
        "locality": listing.locality,
        "sub_locality": listing.sub_locality,
        "main_image_url": listing.main_image_url,
        "owner_id": listing.owner_id,
        "owner": serialize_user_summary(listing.__dict__.get("owner")),
        "is_available": listing.is_available,
        "tags": [str(tag) for tag in (listing.tags or [])],
        "gender_preference": preferences.get("gender_preference"),
        "sharing_type": preferences.get("sharing_type"),
        "available_from": listing.available_from,
        "listing_preferences": preferences,
        "ai_prescreen_result": preferences.get("ai_prescreen_result"),
        "ai_prescreen_flags": preferences.get("ai_prescreen_flags") or [],
        "ai_flag_reason": preferences.get("ai_prescreen_reason"),
        "created_at": listing.created_at,
        "updated_at": listing.updated_at,
    }


def serialize_report(
    report: UserReport,
    user_map: dict[int, User] | None = None,
) -> dict[str, Any]:
    user_map = user_map or {}
    return {
        "id": report.id,
        "reporter_user_id": report.reporter_user_id,
        "reported_user_id": report.reported_user_id,
        "conversation_id": report.conversation_id,
        "property_id": report.property_id,
        "reason": report.reason,
        "status": report.status,
        "notes": report.notes,
        "moderator_notes": getattr(report, "moderator_notes", None),
        "moderated_by": getattr(report, "moderated_by", None),
        "moderated_at": getattr(report, "moderated_at", None),
        "created_at": report.created_at,
        "updated_at": report.updated_at,
        "reporter": serialize_user_summary(user_map.get(report.reporter_user_id)),
        "reported_user": serialize_user_summary(user_map.get(report.reported_user_id)),
    }
