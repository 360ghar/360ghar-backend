"""Tests for app.core.auth module."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetSupabaseClients:
    """Tests for Supabase client creation helpers."""

    def test_get_supabase_auth_client_creates_singleton(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            import app.core.auth as auth_module

            auth_module._supabase_client = None
            # SUPABASE_CLIENT_KEY is derived from SUPABASE_PUBLISHABLE_KEY which
            # is already set in env; just call directly.
            client_one = auth_module.get_supabase_auth_client()
            client_two = auth_module.get_supabase_auth_client()

            assert mock_create.call_count == 1
            assert client_one is client_two

    def test_get_supabase_auth_client_requires_publishable_key(self):
        import app.core.auth as auth_module
        from unittest.mock import PropertyMock

        auth_module._supabase_client = None
        with patch.object(type(auth_module.settings), "SUPABASE_CLIENT_KEY", new_callable=PropertyMock, return_value=""):
            with pytest.raises(ValueError, match="Missing Supabase publishable key"):
                auth_module.get_supabase_auth_client()

    def test_get_supabase_service_client_creates_singleton(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            import app.core.auth as auth_module

            auth_module._supabase_service_client = None
            client_one = auth_module.get_supabase_service_client()
            client_two = auth_module.get_supabase_service_client()

            assert mock_create.call_count == 1
            assert client_one is client_two


class TestVerifySupabaseToken:
    """Tests for verify_supabase_token via Supabase API."""

    @pytest.mark.asyncio
    async def test_verify_token_success(self):
        user_id = str(uuid.uuid4())
        supabase_response = {
            "id": user_id,
            "email": "test@example.com",
            "phone": "+919876543210",
            "user_metadata": {"full_name": "Test User"},
            "email_confirmed_at": None,
            "phone_confirmed_at": "2025-01-01T00:00:00Z",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = supabase_response

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import verify_supabase_token

            result = await verify_supabase_token("valid_jwt")

            assert result is not None
            assert result["id"] == user_id
            assert result["email"] == "test@example.com"
            assert result["phone"] == "+919876543210"
            assert result["email_verified"] is True

    @pytest.mark.asyncio
    async def test_verify_token_failure_returns_none(self):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = "Invalid token"

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import verify_supabase_token

            result = await verify_supabase_token("invalid_jwt")

            assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_missing_id_returns_none(self):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"email": "x@example.com"}

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import verify_supabase_token

            result = await verify_supabase_token("jwt_without_id")

            assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_network_error_returns_none(self):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import verify_supabase_token

            result = await verify_supabase_token("any_jwt")

            assert result is None


class TestAdminFindUserByPhone:
    """Tests for admin_find_user_by_phone function."""

    @pytest.mark.asyncio
    async def test_find_user_success(self):
        user_id = str(uuid.uuid4())
        phone = "+919876543210"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "users": [
                    {
                        "id": user_id,
                        "email": "test@example.com",
                        "phone": phone,
                        "user_metadata": {"name": "Test"},
                    }
                ]
            }

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import admin_find_user_by_phone

            result = await admin_find_user_by_phone(phone)

            assert result is not None
            assert result["id"] == user_id
            assert result["phone"] == phone

    @pytest.mark.asyncio
    async def test_find_user_not_found(self):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"users": []}

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import admin_find_user_by_phone

            result = await admin_find_user_by_phone("+919999999999")

            assert result is None

    @pytest.mark.asyncio
    async def test_find_user_404_response(self):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import admin_find_user_by_phone

            result = await admin_find_user_by_phone("+919876543210")

            assert result is None

    @pytest.mark.asyncio
    async def test_find_user_phone_mismatch(self):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "users": [{"id": str(uuid.uuid4()), "phone": "+919999999999"}]
            }

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import admin_find_user_by_phone

            result = await admin_find_user_by_phone("+919876543210")

            assert result is None

    @pytest.mark.asyncio
    async def test_find_user_exception(self):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Network error")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            from app.core.auth import admin_find_user_by_phone

            result = await admin_find_user_by_phone("+919876543210")

            assert result is None
