"""Consent gate and typed-settings contract for notifications.

Pure functions only. No database, no FCM.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models.enums import AppKey
from app.schemas.common import NotificationSettings, NotificationSettingsWrite
from app.services.notification_config import (
    NOTIFICATION_TYPES,
    NotificationCategory,
    NotificationChannel,
    NotificationTypeKey,
    app_key_for_type,
)
from app.services.notification_dispatcher import (
    _get_user_channels_from_settings,
    dispatch_notification_to_user,
)

MARKETING = NotificationCategory.MARKETING
TRANSACTIONAL = NotificationCategory.TRANSACTIONAL


def _channels(settings: dict | None, category) -> set[NotificationChannel]:
    return _get_user_channels_from_settings(settings_json=settings, category=category)


def test_marketing_missing_consent_is_opt_out():
    assert NotificationChannel.PUSH not in _channels({}, MARKETING)
    assert NotificationChannel.EMAIL not in _channels({}, MARKETING)


def test_categories_promotions_true_does_not_grant_marketing():
    """The old OR merge let categories.promotions override promotional_emails=false. It must not."""
    settings = {"promotional_emails": False, "categories": {"promotions": True}}
    assert NotificationChannel.PUSH not in _channels(settings, MARKETING)


def test_marketing_with_consent_is_allowed():
    settings = {"promotional_emails": True}
    assert NotificationChannel.PUSH in _channels(settings, MARKETING)


def test_marketing_needs_only_promotional_emails():
    """One marketing key. No other stored key gates marketing."""
    settings = {"promotional_emails": True, "push_notifications": True}
    assert NotificationChannel.PUSH in _channels(settings, MARKETING)
    # Stored keys that no longer exist do not change the gate.
    legacy = {"promotional_emails": True, "onboarding": False, "digest": False}
    assert NotificationChannel.PUSH in _channels(legacy, MARKETING)


def test_read_default_and_marketing_gate_agree():
    """GET returns promotional_emails=false when unset. The gate must block marketing for the same settings."""
    read_default = NotificationSettings().model_dump()
    assert read_default["promotional_emails"] is False
    assert NotificationChannel.PUSH not in _channels(read_default, MARKETING)
    assert NotificationChannel.EMAIL not in _channels(read_default, MARKETING)
    granted = {**read_default, "promotional_emails": True}
    assert NotificationChannel.PUSH in _channels(granted, MARKETING)


def test_transactional_ignores_marketing_consent():
    assert NotificationChannel.PUSH in _channels({"promotional_emails": False}, TRANSACTIONAL)


def test_push_switch_off_removes_push_for_transactional():
    assert NotificationChannel.PUSH not in _channels({"push_notifications": False}, TRANSACTIONAL)


def test_app_key_for_type_routes_flatmates_types_only():
    assert app_key_for_type("flatmate_new_match") is AppKey.flatmates
    assert app_key_for_type("booking_confirmed") is AppKey.ghar


def test_notification_type_key_is_the_registry():
    adapter = TypeAdapter(NotificationTypeKey)
    assert adapter.validate_python("booking_confirmed") == "booking_confirmed"
    with pytest.raises(ValidationError):
        adapter.validate_python("not_registered")
    assert set(NOTIFICATION_TYPES) >= {"admin_broadcast", "promotion_generic"}


def test_write_settings_reject_unknown_keys_and_read_tolerates_them():
    with pytest.raises(ValidationError):
        NotificationSettingsWrite.model_validate(
            {"promotional_emails": True, "marketing_emails": True}
        )
    read = NotificationSettings.model_validate(
        {"promotional_emails": True, "marketing_emails": True}
    )
    assert read.promotional_emails is True
    assert NotificationSettings().promotional_emails is False


@pytest.mark.asyncio
async def test_unknown_type_key_sends_nothing():
    """An unregistered key must not fall back to another type."""
    db = MagicMock()
    db.execute = AsyncMock()
    with patch(
        "app.services.notification_dispatcher.send_to_user", new_callable=AsyncMock
    ) as mock_send:
        result = await dispatch_notification_to_user(
            db,
            user_db_id=1,
            type_key="not_registered",
            title="T",
            body="B",
        )

    mock_send.assert_not_called()
    db.execute.assert_not_called()
    assert result["error"] == "unknown_type_key"
    assert result["channels"] == {}
