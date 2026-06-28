"""
Tests for app.services.notification_config module.
"""

import pytest

from app.services.notification_config import (
    NOTIFICATION_TYPES,
    FrequencyCap,
    NotificationCategory,
    NotificationChannel,
    NotificationPriority,
    NotificationTypeConfig,
)


class TestNotificationChannel:
    def test_channel_values(self):
        assert NotificationChannel.IN_APP.value == "in_app"
        assert NotificationChannel.PUSH.value == "push"
        assert NotificationChannel.EMAIL.value == "email"
        assert NotificationChannel.SMS.value == "sms"


class TestNotificationCategory:
    def test_category_values(self):
        assert NotificationCategory.TRANSACTIONAL.value == "transactional"
        assert NotificationCategory.SYSTEM.value == "system"
        assert NotificationCategory.MARKETING.value == "marketing"


class TestNotificationPriority:
    def test_priority_values(self):
        assert NotificationPriority.LOW.value == "low"
        assert NotificationPriority.NORMAL.value == "normal"
        assert NotificationPriority.HIGH.value == "high"
        assert NotificationPriority.CRITICAL.value == "critical"


class TestFrequencyCap:
    def test_defaults_are_none(self):
        cap = FrequencyCap()
        assert cap.per_day is None
        assert cap.per_week is None

    def test_custom_values(self):
        cap = FrequencyCap(per_day=5, per_week=20)
        assert cap.per_day == 5
        assert cap.per_week == 20

    def test_frozen(self):
        cap = FrequencyCap(per_day=3)
        with pytest.raises(AttributeError):
            cap.per_day = 5


class TestNotificationTypeConfig:
    def test_basic_config(self):
        config = NotificationTypeConfig(
            key="test_type",
            category=NotificationCategory.TRANSACTIONAL,
            priority=NotificationPriority.HIGH,
        )
        assert config.key == "test_type"
        assert config.category == NotificationCategory.TRANSACTIONAL
        assert config.priority == NotificationPriority.HIGH

    def test_default_ttl(self):
        config = NotificationTypeConfig(
            key="test",
            category=NotificationCategory.SYSTEM,
            priority=NotificationPriority.NORMAL,
        )
        assert config.default_ttl_seconds == 24 * 3600

    def test_custom_channels(self):
        channels = {NotificationChannel.PUSH, NotificationChannel.EMAIL}
        config = NotificationTypeConfig(
            key="test",
            category=NotificationCategory.TRANSACTIONAL,
            priority=NotificationPriority.HIGH,
            allowed_channels=channels,
        )
        assert NotificationChannel.PUSH in config.allowed_channels

    def test_frozen(self):
        config = NotificationTypeConfig(
            key="test",
            category=NotificationCategory.SYSTEM,
            priority=NotificationPriority.NORMAL,
        )
        with pytest.raises(AttributeError):
            config.key = "modified"


class TestNotificationTypesRegistry:
    """Tests for the NOTIFICATION_TYPES registry."""

    def test_registry_is_populated(self):
        assert len(NOTIFICATION_TYPES) > 0

    def test_booking_confirmed_exists(self):
        assert "booking_confirmed" in NOTIFICATION_TYPES

    def test_payment_failed_is_critical(self):
        config = NOTIFICATION_TYPES["payment_failed"]
        assert config.priority == NotificationPriority.CRITICAL

    def test_transactional_types_have_high_priority(self):
        transactional = [
            v for v in NOTIFICATION_TYPES.values()
            if v.category == NotificationCategory.TRANSACTIONAL
        ]
        for t in transactional:
            assert t.priority in (NotificationPriority.HIGH, NotificationPriority.CRITICAL, NotificationPriority.NORMAL)

    def test_marketing_types_have_frequency_caps(self):
        marketing = [
            v for v in NOTIFICATION_TYPES.values()
            if v.category == NotificationCategory.MARKETING
        ]
        for m in marketing:
            assert m.frequency_cap is not None, f"Marketing type '{m.key}' missing frequency cap"

    def test_marketing_types_have_opt_in_key(self):
        marketing = [
            v for v in NOTIFICATION_TYPES.values()
            if v.category == NotificationCategory.MARKETING
        ]
        for m in marketing:
            assert m.marketing_opt_in_key is not None, f"Marketing type '{m.key}' missing opt-in key"

    def test_security_alert_uses_all_channels(self):
        config = NOTIFICATION_TYPES["security_alert"]
        assert NotificationChannel.PUSH in config.allowed_channels
        assert NotificationChannel.EMAIL in config.allowed_channels
        assert NotificationChannel.SMS in config.allowed_channels

    def test_chat_message_does_not_use_email(self):
        config = NOTIFICATION_TYPES["chat_message"]
        assert NotificationChannel.EMAIL not in config.allowed_channels
