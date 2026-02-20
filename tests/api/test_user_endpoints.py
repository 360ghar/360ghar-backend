"""
Tests for user endpoints.

These tests verify the user-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.enums import UserRole
from app.schemas.user import User as UserSchema


def create_mock_user(
    user_id: int = 1,
    full_name: str = "Test User",
    email: str = "test@example.com",
    phone: str = "+919876543210",
) -> UserSchema:
    """Create a mock user schema object."""
    return UserSchema(
        id=user_id,
        phone=phone,
        email=email,
        full_name=full_name,
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
        supabase_user_id="test-supabase-uid",
        created_at=datetime.now(timezone.utc),
        updated_at=None,
    )


class TestGetUserProfileEndpoint:
    """Tests for GET /api/v1/users/profile/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_user_profile(self, authenticated_client: AsyncClient):
        """Test getting current user profile."""
        response = await authenticated_client.get("/api/v1/users/profile/")

        assert response.status_code == 200
        data = response.json()
        assert "id" in data or "phone" in data

    @pytest.mark.asyncio
    async def test_get_user_profile_unauthorized(self, client: AsyncClient):
        """Test getting user profile without auth."""
        response = await client.get("/api/v1/users/profile/")

        assert response.status_code == 401


class TestUpdateUserProfileEndpoint:
    """Tests for PUT /api/v1/users/profile/ endpoint."""

    @pytest.mark.asyncio
    async def test_update_user_profile(self, authenticated_client: AsyncClient):
        """Test updating user profile."""
        with patch(
            "app.api.api_v1.endpoints.users.update_user",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = create_mock_user(
                user_id=1, full_name="Updated Name"
            )

            response = await authenticated_client.put(
                "/api/v1/users/profile/",
                json={"full_name": "Updated Name"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["full_name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_user_email(self, authenticated_client: AsyncClient):
        """Test updating user email."""
        with patch(
            "app.api.api_v1.endpoints.users.update_user",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = create_mock_user(
                user_id=1, email="newemail@example.com"
            )

            response = await authenticated_client.put(
                "/api/v1/users/profile/",
                json={"email": "newemail@example.com"},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_user_profile_unauthorized(self, client: AsyncClient):
        """Test profile update requires auth."""
        response = await client.put(
            "/api/v1/users/profile/",
            json={"full_name": "Updated Name"},
        )

        assert response.status_code == 401


class TestUpdatePreferencesEndpoint:
    """Tests for PUT /api/v1/users/preferences/ endpoint."""

    @pytest.mark.asyncio
    async def test_update_preferences(self, authenticated_client: AsyncClient):
        """Test updating user preferences."""
        with patch(
            "app.api.api_v1.endpoints.users.update_user_preferences",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = True

            response = await authenticated_client.put(
                "/api/v1/users/preferences/",
                json={},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_preferences_with_typed_values(
        self, authenticated_client: AsyncClient
    ):
        """Test updating preferences with strict enum values."""
        with patch(
            "app.api.api_v1.endpoints.users.update_user_preferences",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = True

            response = await authenticated_client.put(
                "/api/v1/users/preferences/",
                json={
                    "property_type": ["condo", "studio"],
                    "purpose": "short_stay",
                    "budget_min": 10000,
                    "budget_max": 50000,
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_preferences_rejects_invalid_enum(
        self, authenticated_client: AsyncClient
    ):
        """Test invalid enum values are rejected."""
        response = await authenticated_client.put(
            "/api/v1/users/preferences/",
            json={"purpose": "investment"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_preferences_unauthorized(self, client: AsyncClient):
        """Test preferences update requires auth."""
        response = await client.put(
            "/api/v1/users/preferences/",
            json={},
        )

        assert response.status_code == 401


class TestUpdateLocationEndpoint:
    """Tests for PUT /api/v1/users/location/ endpoint."""

    @pytest.mark.asyncio
    async def test_update_location(self, authenticated_client: AsyncClient):
        """Test updating user location."""
        with patch(
            "app.api.api_v1.endpoints.users.update_user_location",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = True

            response = await authenticated_client.put(
                "/api/v1/users/location/",
                json={"latitude": 19.0760, "longitude": 72.8777},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_location_unauthorized(self, client: AsyncClient):
        """Test location update requires auth."""
        response = await client.put(
            "/api/v1/users/location/",
            json={"latitude": 19.0760, "longitude": 72.8777},
        )

        assert response.status_code == 401


class TestNotificationSettingsEndpoint:
    """Tests for notification settings endpoints."""

    @pytest.mark.asyncio
    async def test_get_notification_settings(self, authenticated_client: AsyncClient):
        """Test getting notification settings."""
        with patch(
            "app.api.api_v1.endpoints.users.get_user_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_user = create_mock_user()
            mock_user_model = type(
                "MockUserModel",
                (),
                {"notification_settings": {"push_enabled": True}},
            )()
            mock_get.return_value = mock_user_model

            response = await authenticated_client.get(
                "/api/v1/users/notification-settings"
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_notification_settings(
        self, authenticated_client: AsyncClient
    ):
        """Test updating notification settings."""
        with patch(
            "app.api.api_v1.endpoints.users.update_user_notification_settings",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = True

            response = await authenticated_client.put(
                "/api/v1/users/notification-settings",
                json={},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_notification_settings_unauthorized(self, client: AsyncClient):
        """Test notification settings requires auth."""
        response = await client.get("/api/v1/users/notification-settings")

        assert response.status_code == 401


class TestPrivacySettingsEndpoint:
    """Tests for privacy settings endpoints."""

    @pytest.mark.asyncio
    async def test_get_privacy_settings(self, authenticated_client: AsyncClient):
        """Test getting privacy settings."""
        with patch(
            "app.api.api_v1.endpoints.users.get_user_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_user_model = type(
                "MockUserModel",
                (),
                {"privacy_settings": {}},
            )()
            mock_get.return_value = mock_user_model

            response = await authenticated_client.get(
                "/api/v1/users/privacy-settings"
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_privacy_settings(self, authenticated_client: AsyncClient):
        """Test updating privacy settings."""
        with patch(
            "app.api.api_v1.endpoints.users.update_user_privacy_settings",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = True

            response = await authenticated_client.put(
                "/api/v1/users/privacy-settings",
                json={},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_privacy_settings_unauthorized(self, client: AsyncClient):
        """Test privacy settings requires auth."""
        response = await client.get("/api/v1/users/privacy-settings")

        assert response.status_code == 401


class TestListUsersEndpoint:
    """Tests for GET /api/v1/users/ endpoint (admin/agent only)."""

    @pytest.mark.asyncio
    async def test_list_users_admin(self, admin_authenticated_client: AsyncClient):
        """Test listing users as admin."""
        with patch(
            "app.api.api_v1.endpoints.users.get_all_users",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], 0)

            response = await admin_authenticated_client.get("/api/v1/users/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data

    @pytest.mark.asyncio
    async def test_list_users_unauthorized(self, client: AsyncClient):
        """Test listing users requires auth."""
        response = await client.get("/api/v1/users/")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_users_forbidden_for_regular_user(
        self, authenticated_client: AsyncClient
    ):
        """Test regular user cannot list all users."""
        response = await authenticated_client.get("/api/v1/users/")

        assert response.status_code == 403


class TestGetUserByIdEndpoint:
    """Tests for GET /api/v1/users/{user_id}/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_user_by_id_admin(self, admin_authenticated_client: AsyncClient):
        """Test getting user by ID as admin."""
        with patch(
            "app.api.api_v1.endpoints.users.get_user_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_user = create_mock_user(user_id=42)
            # Create a mock that has model_validate compatible structure
            mock_user_model = type(
                "MockUserModel",
                (),
                {
                    "id": 42,
                    "phone": "+919876543210",
                    "email": "test@example.com",
                    "full_name": "Test User",
                    "role": UserRole.user.value,
                    "is_active": True,
                    "is_verified": True,
                    "supabase_user_id": "test-uid",
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": None,
                    "notification_settings": None,
                    "privacy_settings": None,
                },
            )()
            mock_get.return_value = mock_user_model

            response = await admin_authenticated_client.get("/api/v1/users/42/")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, admin_authenticated_client: AsyncClient):
        """Test getting non-existent user."""
        with patch(
            "app.api.api_v1.endpoints.users.get_user_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await admin_authenticated_client.get("/api/v1/users/99999/")

            assert response.status_code == 404
