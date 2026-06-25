from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.enums import PropertyPurpose, PropertyType
from app.services.flatmates.moderation import (
    STALE_LISTING_PAUSE_REASON,
    apply_stale_listing_pause,
)
from app.services.property.crud import _owner_moderation_status_toggle


def _listing(**overrides):
    now = datetime(2026, 5, 7, tzinfo=timezone.utc)
    defaults = {
        "property_type": PropertyType.flatmate,
        "purpose": PropertyPurpose.rent,
        "updated_at": now - timedelta(days=61),
        "created_at": now - timedelta(days=120),
        "is_available": True,
        "listing_preferences": {"moderation_status": "live"},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_stale_listing_pauses_live_listing():
    now = datetime(2026, 5, 7, 12, tzinfo=timezone.utc)
    listing = _listing(updated_at=now - timedelta(days=61))

    paused = apply_stale_listing_pause(listing, now=now)

    assert paused is True
    assert listing.is_available is False
    assert listing.listing_preferences["moderation_status"] == "paused"
    assert listing.listing_preferences["auto_paused_reason"] == STALE_LISTING_PAUSE_REASON
    assert listing.listing_preferences["room_poster_review_required"] is True
    assert listing.listing_preferences["previous_moderation_status"] == "live"


def test_stale_listing_repauses_attempted_resume():
    now = datetime(2026, 5, 7, 12, tzinfo=timezone.utc)
    listing = _listing(
        updated_at=now - timedelta(days=61),
        is_available=True,
        listing_preferences={
            "moderation_status": "live",
            "auto_paused_reason": STALE_LISTING_PAUSE_REASON,
        },
    )

    paused = apply_stale_listing_pause(listing, now=now)

    assert paused is True
    assert listing.is_available is False
    assert listing.listing_preferences["moderation_status"] == "paused"


def test_fresh_listing_stays_available():
    now = datetime(2026, 5, 7, 12, tzinfo=timezone.utc)
    listing = _listing(updated_at=now - timedelta(days=10))

    paused = apply_stale_listing_pause(listing, now=now)

    assert paused is False
    assert listing.is_available is True
    assert listing.listing_preferences["moderation_status"] == "live"


def test_stale_listing_ignores_non_live_listing():
    now = datetime(2026, 5, 7, 12, tzinfo=timezone.utc)
    listing = _listing(
        updated_at=now - timedelta(days=61),
        is_available=False,
        listing_preferences={"moderation_status": "pending_review"},
    )

    paused = apply_stale_listing_pause(listing, now=now)

    assert paused is False
    assert listing.listing_preferences["moderation_status"] == "pending_review"


def test_stale_listing_only_applies_to_flatmate_inventory():
    now = datetime(2026, 5, 7, 12, tzinfo=timezone.utc)
    listing = _listing(
        property_type=PropertyType.apartment,
        updated_at=now - timedelta(days=61),
    )

    paused = apply_stale_listing_pause(listing, now=now)

    assert paused is False
    assert listing.is_available is True


def test_stale_listing_uses_created_at_fallback():
    """When updated_at is None, fall back to created_at."""
    now = datetime(2026, 5, 7, 12, tzinfo=timezone.utc)
    listing = _listing(
        updated_at=None,
        created_at=now - timedelta(days=90),
    )

    paused = apply_stale_listing_pause(listing, now=now)

    assert paused is True
    assert listing.is_available is False
    assert listing.listing_preferences["moderation_status"] == "paused"


def test_owner_moderation_status_toggle_accepts_exact_pause_resume_payload():
    assert (
        _owner_moderation_status_toggle({"listing_preferences": {"moderation_status": "paused"}})
        == "paused"
    )
    assert (
        _owner_moderation_status_toggle({"listing_preferences": {"moderation_status": "live"}})
        == "live"
    )


def test_owner_moderation_status_toggle_rejects_content_update_payloads():
    assert (
        _owner_moderation_status_toggle(
            {
                "title": "Updated listing",
                "listing_preferences": {"moderation_status": "paused"},
            }
        )
        is None
    )
    assert (
        _owner_moderation_status_toggle(
            {"listing_preferences": {"moderation_status": "pending_review"}}
        )
        is None
    )
