"""Client gate for the notification settings contract (BE-notify, residual round 2).

Each body below is the body one client sends today. The source is named beside it.
The contract accepts four keys: push_notifications, email_notifications,
sms_notifications and promotional_emails. A body with any other key is rejected
with 422 for the whole request, so no field in it is applied.

The four-key bodies are the targets the clients move to. They must still succeed.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

CONTRACT_KEYS = {
    "push_notifications",
    "email_notifications",
    "sms_notifications",
    "promotional_emails",
}

# Flatmates app: settings_controller.dart _buildNotificationPayload and
# settings_repository.dart toJson. Sent on every switch save.
FLATMATES_APP_BODY = {
    "email_notifications": True,
    "push_notifications": True,
    "sms_notifications": False,
    "promotional_emails": False,
    "visit_reminders": True,
    "property_updates": True,
    "onboarding": True,
    "digest": True,
    "categories": {
        "visit_reminders": True,
        "property_updates": True,
        "promotions": False,
        "new_matches": True,
    },
}
FLATMATES_REMOVED = {"visit_reminders", "property_updates", "onboarding", "digest", "categories"}

# Ghar app: notification_settings_repository.dart toggles and save(). The
# property_updates switch sends the key with the four contract keys.
GHAR_APP_BODY = {
    "push_notifications": True,
    "email_notifications": True,
    "sms_notifications": False,
    "promotional_emails": False,
    "property_updates": True,
}

# Admin dashboard: UserPreferencesPage.tsx defaults, sent through PUT /users/{id}.
ADMIN_BODY = {
    "notification_settings": {
        "push_notifications": True,
        "email_notifications": True,
        "sms_notifications": False,
        "promotional_emails": False,
        "visit_reminders": True,
        "booking_updates": True,
        "price_alerts": False,
        "new_properties": True,
        "property_updates": True,
    }
}

# Tours web: SettingsPage.tsx, sent through PUT /users/me as notification_settings.
TOURS_WEB_BODY = {
    "full_name": "Renamed User",
    "notification_settings": {"email_notifications": True, "marketing_emails": True},
}

# Target body for the flatmates app and the other clients.
FOUR_KEY_BODY = {
    "push_notifications": True,
    "email_notifications": True,
    "sms_notifications": False,
    "promotional_emails": True,
}


def _error_fields(response) -> set[str]:
    return {item["field"] for item in response.json()["error"]["details"]["fields"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/users/notification-settings", "/api/v1/users/notifications"]
)
async def test_flatmates_app_body_is_rejected_for_the_whole_request(
    authenticated_client, path
) -> None:
    """The flatmates app sends five removed keys. The PUT fails and stores nothing."""
    with patch(
        "app.api.api_v1.endpoints.users.update_user_notification_settings",
        new_callable=AsyncMock,
    ) as mock_update:
        response = await authenticated_client.put(path, json=FLATMATES_APP_BODY)

    assert response.status_code == 422
    fields = _error_fields(response)
    for key in FLATMATES_REMOVED:
        assert f"body.{key}" in fields
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_ghar_app_property_updates_key_is_rejected(authenticated_client) -> None:
    """The ghar app sends property_updates on a toggle. That key is not in the contract."""
    with patch(
        "app.api.api_v1.endpoints.users.update_user_notification_settings",
        new_callable=AsyncMock,
    ) as mock_update:
        response = await authenticated_client.put(
            "/api/v1/users/notification-settings", json=GHAR_APP_BODY
        )

    assert response.status_code == 422
    assert "body.property_updates" in _error_fields(response)
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_four_key_body_is_accepted_and_returns_only_the_contract(
    authenticated_client,
) -> None:
    """The target body saves. The response has the four contract keys and no others."""
    stored = SimpleNamespace(notification_settings=dict(FOUR_KEY_BODY))
    with patch(
        "app.api.api_v1.endpoints.users.update_user_notification_settings",
        new_callable=AsyncMock,
        return_value=stored,
    ) as mock_update:
        response = await authenticated_client.put(
            "/api/v1/users/notification-settings", json=FOUR_KEY_BODY
        )

    assert response.status_code == 200
    assert set(response.json()) == CONTRACT_KEYS
    mock_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_tours_web_stale_key_fails_the_whole_profile_save(authenticated_client) -> None:
    """A marketing_emails key inside notification_settings returns 422 for PUT /users/me.

    The full_name in the same body is not applied.
    """
    with patch("app.api.api_v1.endpoints.users.update_user", new_callable=AsyncMock) as mock_update:
        response = await authenticated_client.put("/api/v1/users/me", json=TOURS_WEB_BODY)

    assert response.status_code == 422
    assert "body.notification_settings.marketing_emails" in _error_fields(response)
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_tours_web_promotional_emails_key_passes_validation(authenticated_client) -> None:
    """promotional_emails inside notification_settings is valid on PUT /users/me.

    The mock returns None, so the route answers 404 after validation. A 422 would
    mean validation failed.
    """
    body = {"notification_settings": {"email_notifications": True, "promotional_emails": True}}
    with patch(
        "app.api.api_v1.endpoints.users.update_user",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_update:
        response = await authenticated_client.put("/api/v1/users/me", json=body)

    assert response.status_code != 422
    mock_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_user_put_with_removed_keys_is_rejected(admin_authenticated_client) -> None:
    """The admin dashboard sends removed keys through PUT /users/{id}. The save fails."""
    with patch("app.api.api_v1.endpoints.users.update_user", new_callable=AsyncMock) as mock_update:
        response = await admin_authenticated_client.put("/api/v1/users/1", json=ADMIN_BODY)

    assert response.status_code == 422
    fields = _error_fields(response)
    assert "body.notification_settings.visit_reminders" in fields
    assert "body.notification_settings.property_updates" in fields
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_get_returns_only_the_contract_keys_for_a_stored_legacy_blob(
    authenticated_client,
) -> None:
    """A stored blob with removed keys reads as the four contract keys only."""
    legacy = {
        **FOUR_KEY_BODY,
        "frequency": "daily",
        "digest": True,
        "property_updates": True,
        "categories": {"promotions": True},
        "quiet_hours": {"start": "22:00"},
    }
    with patch(
        "app.api.api_v1.endpoints.users.get_user_by_id",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(notification_settings=legacy),
    ):
        response = await authenticated_client.get("/api/v1/users/notification-settings")

    assert response.status_code == 200
    assert set(response.json()) == CONTRACT_KEYS
    assert response.json()["promotional_emails"] is True
