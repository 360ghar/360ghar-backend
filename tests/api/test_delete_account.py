"""
Tests for account deletion endpoints.

Covers both routes:
  - DELETE /api/v1/users/me  (returns 200 + MessageResponse)
  - POST  /api/v1/auth/delete-account  (returns 204 No Content)

Both call the shared ``delete_user_account`` service which:
  1. Hard-deletes the Supabase Auth user via admin_delete_user
  2. Anonymizes PII + soft-deletes the local row
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.exceptions import ServiceUnavailableException

# =============================================================================
# DELETE /api/v1/users/me
# =============================================================================


class TestDeleteAccountViaUsersMe:
    """DELETE /api/v1/users/me — canonical route, returns 200 + JSON message."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        response = await client.delete("/api/v1/users/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_successful_deletion(self, user_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.users.delete_user_account",
            new_callable=AsyncMock,
        ) as mock_delete:
            response = await user_client.delete("/api/v1/users/me")

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Account deleted successfully"
        mock_delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_supabase_unavailable_returns_503(self, user_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.users.delete_user_account",
            new_callable=AsyncMock,
            side_effect=ServiceUnavailableException(
                detail="Identity provider is temporarily unavailable, please retry",
                headers={"Retry-After": "30"},
            ),
        ):
            response = await user_client.delete("/api/v1/users/me")

        assert response.status_code == 503
        assert response.headers.get("retry-after") == "30"

    @pytest.mark.asyncio
    async def test_supabase_error_returns_500(self, user_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.users.delete_user_account",
            new_callable=AsyncMock,
            side_effect=Exception("Unexpected error"),
        ):
            response = await user_client.delete("/api/v1/users/me")

        assert response.status_code == 500


# =============================================================================
# POST /api/v1/auth/delete-account
# =============================================================================


class TestDeleteAccountViaAuthRoute:
    """POST /api/v1/auth/delete-account — alternate route, returns 204."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/delete-account")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_successful_deletion_returns_204(self, user_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.auth.delete_user_account",
            new_callable=AsyncMock,
        ) as mock_delete:
            response = await user_client.post("/api/v1/auth/delete-account")

        assert response.status_code == 204
        assert response.content == b""  # No Content
        mock_delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_supabase_unavailable_returns_503(self, user_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.auth.delete_user_account",
            new_callable=AsyncMock,
            side_effect=ServiceUnavailableException(
                detail="Identity provider is temporarily unavailable, please retry",
                headers={"Retry-After": "30"},
            ),
        ):
            response = await user_client.post("/api/v1/auth/delete-account")

        assert response.status_code == 503


# =============================================================================
# Service-level tests for delete_user_account
# =============================================================================


class TestDeleteUserService:
    """Unit tests for the delete_user_account service function.

    These test the PII anonymization logic by directly calling the service
    with a real SQLAlchemy ORM instance and mocking only the Supabase call.
    """

    @pytest.mark.asyncio
    async def test_pii_fields_anonymized(self, db_session, test_user):
        from app.services.user import delete_user_account

        with patch(
            "app.services.user.admin_delete_user",
            new=AsyncMock(return_value=True),
        ):
            await delete_user_account(db_session, test_user)

        assert test_user.is_active is False
        assert test_user.supabase_user_id == f"__deleted__{test_user.id}"
        # Identity & contact PII
        assert test_user.email is None
        assert test_user.phone is None
        assert test_user.full_name is None
        assert test_user.profile_image_url is None
        assert test_user.date_of_birth is None
        assert test_user.email_verified is False
        assert test_user.phone_verified is False
        # Location PII
        assert test_user.current_latitude is None
        assert test_user.current_longitude is None
        # Preference payloads
        assert test_user.preferences is None
        assert test_user.notification_settings is None
        assert test_user.privacy_settings is None

    @pytest.mark.asyncio
    async def test_flatmates_pii_anonymized(self, db_session, test_user):
        from app.services.user import delete_user_account

        with patch(
            "app.services.user.admin_delete_user",
            new=AsyncMock(return_value=True),
        ):
            await delete_user_account(db_session, test_user)

        assert test_user.flatmates_mode is None
        assert test_user.flatmates_bio is None
        assert test_user.flatmates_city is None
        assert test_user.flatmates_locality is None
        assert test_user.flatmates_budget_min is None
        assert test_user.flatmates_budget_max is None
        assert test_user.flatmates_move_in_timeline is None
        assert test_user.flatmates_sleep_schedule is None
        assert test_user.flatmates_cleanliness is None
        assert test_user.flatmates_food_habits is None
        assert test_user.flatmates_smoking_drinking is None
        assert test_user.flatmates_guests_policy is None
        assert test_user.flatmates_work_style is None

    @pytest.mark.asyncio
    async def test_status_and_metadata_fields_reset(self, db_session, test_user):
        from app.services.user import delete_user_account

        with patch(
            "app.services.user.admin_delete_user",
            new=AsyncMock(return_value=True),
        ):
            await delete_user_account(db_session, test_user)

        # Verification & status
        assert test_user.is_verified is False
        assert test_user.flatmates_profile_status is None
        assert test_user.flatmates_onboarding_completed is False
        assert test_user.flatmates_last_active_at is None
        # Auth metadata
        assert test_user.last_auth_method is None
        assert test_user.last_auth_method_at is None
        # Cross-app onboarding
        assert test_user.stays_onboarding_completed is False
        assert test_user.estate_onboarding_completed is False
        assert test_user.ghar360_onboarding_completed is False

    @pytest.mark.asyncio
    async def test_supabase_unavailable_does_not_touch_local_row(
        self, db_session, test_user
    ):
        from app.services.user import delete_user_account

        original_email = test_user.email
        original_active = test_user.is_active

        with patch(
            "app.services.user.admin_delete_user",
            new=AsyncMock(
                return_value={"__auth_failure__": True, "reason": "PROVIDER_UNREACHABLE", "error": "Connection refused"}
            ),
        ):
            with pytest.raises(ServiceUnavailableException):
                await delete_user_account(db_session, test_user)

        # Local row must be untouched
        assert test_user.is_active == original_active
        assert test_user.email == original_email

    @pytest.mark.asyncio
    async def test_supabase_error_does_not_touch_local_row(
        self, db_session, test_user
    ):
        from app.core.exceptions import BaseAPIException
        from app.services.user import delete_user_account

        original_email = test_user.email

        with patch(
            "app.services.user.admin_delete_user",
            new=AsyncMock(return_value=False),
        ):
            with pytest.raises(BaseAPIException):
                await delete_user_account(db_session, test_user)

        # Local row must be untouched
        assert test_user.email == original_email
        assert test_user.is_active is True

    @pytest.mark.asyncio
    async def test_supabase_404_treated_as_success(self, db_session, test_user):
        """404 from Supabase (already deleted) should be treated as success."""
        from app.services.user import delete_user_account

        with patch(
            "app.services.user.admin_delete_user",
            new=AsyncMock(return_value=True),  # 404 → True in admin_delete_user
        ):
            await delete_user_account(db_session, test_user)

        assert test_user.is_active is False
        assert test_user.supabase_user_id == f"__deleted__{test_user.id}"
