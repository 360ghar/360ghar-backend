"""Admin flatmates response serialization helpers."""

from typing import Any

from app.models.properties import Property
from app.models.social import UserReport
from app.models.users import User


def serialize_user_summary(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "profile_image_url": user.profile_image_url,
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
        "description": report.notes,
        "admin_notes": report.notes,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
        "reporter": serialize_user_summary(user_map.get(report.reporter_user_id)),
        "reported_user": serialize_user_summary(user_map.get(report.reported_user_id)),
    }
