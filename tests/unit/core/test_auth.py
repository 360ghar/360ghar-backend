"""Tests for app.core.auth module."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.auth import SupabaseClientManager
from app.config import settings


class TestGetSupabaseClients:
    """Tests for Supabase client creation helpers."""

    def test_get_supabase_auth_client_creates_singleton(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            mgr = SupabaseClientManager()
            client_one = mgr.get_auth_client()
            client_two = mgr.get_auth_client()

            assert mock_create.call_count == 1
            assert client_one is client_two
            assert mock_create.call_args.kwargs["options"].httpx_client is not None

    def test_get_supabase_auth_client_requires_publishable_key(self):
        from unittest.mock import PropertyMock

        mgr = SupabaseClientManager()
        with patch.object(type(settings), "SUPABASE_CLIENT_KEY", new_callable=PropertyMock, return_value=""):
            with pytest.raises(ValueError, match="Missing Supabase publishable key"):
                mgr.get_auth_client()

    def test_get_supabase_service_client_creates_singleton(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            mgr = SupabaseClientManager()
            client_one = mgr.get_service_client()
            client_two = mgr.get_service_client()

            assert mock_create.call_count == 1
            assert client_one is client_two
            assert mock_create.call_args.kwargs["options"].httpx_client is not None

    def test_get_supabase_storage_client_creates_singleton(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            mgr = SupabaseClientManager()
            client_one = mgr.get_storage_client()
            client_two = mgr.get_storage_client()

            assert mock_create.call_count == 1
            assert client_one is client_two
            assert mock_create.call_args.kwargs["options"].httpx_client is not None


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

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = supabase_response

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.verify_token("valid_jwt")

        assert result is not None
        assert result["id"] == user_id
        assert result["email"] == "test@example.com"
        assert result["phone"] == "+919876543210"
        assert result["email_verified"] is True

    @pytest.mark.asyncio
    async def test_verify_token_failure_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid token"

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.verify_token("invalid_jwt")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_missing_id_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"email": "x@example.com"}

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.verify_token("jwt_without_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_network_error_returns_none(self):
        mock_http_client = AsyncMock()
        mock_http_client.get.side_effect = Exception("connection refused")
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.verify_token("any_jwt")
        assert result is None


class TestAdminFindUserByPhone:
    """Tests for admin_find_user_by_phone function."""

    @pytest.mark.asyncio
    async def test_find_user_success(self):
        user_id = str(uuid.uuid4())
        phone = "+919876543210"

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

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.admin_find_user_by_phone(phone)

        assert result is not None
        assert result["id"] == user_id
        assert result["phone"] == phone

    @pytest.mark.asyncio
    async def test_find_user_not_found(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"users": []}

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.admin_find_user_by_phone("+919999999999")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_user_404_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.admin_find_user_by_phone("+919876543210")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_user_phone_mismatch(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "users": [{"id": str(uuid.uuid4()), "phone": "+919999999999"}]
        }

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.admin_find_user_by_phone("+919876543210")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_user_exception(self):
        mock_http_client = AsyncMock()
        mock_http_client.get.side_effect = Exception("Network error")
        mock_http_client.is_closed = False

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        result = await mgr.admin_find_user_by_phone("+919876543210")
        assert result is None


class TestSupabaseClientManagerClose:
    """Tests for SupabaseClientManager.close() lifecycle method."""

    @pytest.mark.asyncio
    async def test_close_closes_auth_http_client(self):
        mock_http_client = AsyncMock()
        mock_http_client.is_closed = False
        mock_http_client.aclose = AsyncMock()

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        await mgr.close()

        mock_http_client.aclose.assert_awaited_once()
        assert mgr._auth_http_client is None

    @pytest.mark.asyncio
    async def test_close_noop_when_client_is_none(self):
        mgr = SupabaseClientManager()
        mgr._auth_http_client = None
        # Should not raise
        await mgr.close()
        assert mgr._auth_http_client is None

    @pytest.mark.asyncio
    async def test_close_noop_when_client_already_closed(self):
        mock_http_client = AsyncMock()
        mock_http_client.is_closed = True
        mock_http_client.aclose = AsyncMock()

        mgr = SupabaseClientManager()
        mgr._auth_http_client = mock_http_client

        await mgr.close()

        mock_http_client.aclose.assert_not_awaited()
        # _auth_http_client remains since is_closed was True at entry
        assert mgr._auth_http_client is mock_http_client


class TestModuleLevelWrappers:
    """Tests that module-level convenience wrappers delegate to the singleton."""

    def test_get_supabase_auth_client_delegates(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            import app.core.auth as auth_module

            # Reset singleton for clean test
            auth_module._manager = SupabaseClientManager()
            client = auth_module.get_supabase_auth_client()
            assert mock_create.call_count == 1
            assert client is auth_module._manager._auth_client

    def test_get_supabase_service_client_delegates(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            import app.core.auth as auth_module

            auth_module._manager = SupabaseClientManager()
            client = auth_module.get_supabase_service_client()
            assert mock_create.call_count == 1
            assert client is auth_module._manager._service_client

    def test_get_supabase_storage_client_delegates(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            import app.core.auth as auth_module

            auth_module._manager = SupabaseClientManager()
            client = auth_module.get_supabase_storage_client()
            assert mock_create.call_count == 1
            assert client is auth_module._manager._storage_client

    @pytest.mark.asyncio
    async def test_close_supabase_clients_delegates(self):
        import app.core.auth as auth_module

        auth_module._manager = SupabaseClientManager()
        mock_http_client = AsyncMock()
        mock_http_client.is_closed = False
        mock_http_client.aclose = AsyncMock()
        auth_module._manager._auth_http_client = mock_http_client

        await auth_module.close_supabase_clients()
        mock_http_client.aclose.assert_awaited_once()

    def test_close_supabase_auth_http_client_is_alias(self):
        import app.core.auth as auth_module

        assert auth_module.close_supabase_auth_http_client is auth_module.close_supabase_clients
