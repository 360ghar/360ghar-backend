"""
Tests for app.schemas.common module — NotificationSettings, PrivacySettings.
"""

from app.schemas.common import (
    NotificationSettings,
    PrivacySettings,
)


class TestNotificationSettings:
    """Tests for NotificationSettings schema."""

    def test_defaults(self):
        settings = NotificationSettings()
        assert settings.email_notifications is True
        assert settings.push_notifications is True
        assert settings.sms_notifications is False
        assert settings.promotional_emails is False

    def test_custom_values(self):
        settings = NotificationSettings(
            email_notifications=False,
            push_notifications=False,
            sms_notifications=True,
        )
        assert settings.email_notifications is False
        assert settings.sms_notifications is True

    def test_categories_default(self):
        settings = NotificationSettings()
        assert "promotions" in settings.categories
        assert "onboarding" in settings.categories


class TestPrivacySettings:
    """Tests for PrivacySettings schema."""

    def test_defaults(self):
        settings = PrivacySettings()
        assert settings.profile_visibility == "public"
        assert settings.location_sharing is True
        assert settings.contact_sharing is True

    def test_private_profile(self):
        settings = PrivacySettings(profile_visibility="private")
        assert settings.profile_visibility == "private"
