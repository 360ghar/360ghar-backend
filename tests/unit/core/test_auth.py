"""Tests for app.core.auth module."""

from __future__ import annotations

import socket
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.core.auth import (
    AuthFailureReason,
    SupabaseClientManager,
    _is_failure,
    _make_failure,
)
from app.core.http import get_supabase_auth_http_client


def _mock_supabase_user(
    *,
    user_id: str | None = None,
    email: str = "test@example.com",
    phone: str = "+919876543210",
    email_confirmed_at: str | None = None,
    phone_confirmed_at: str | None = None,
    app_metadata: dict | None = None,
    user_metadata: dict | None = None,
) -> dict:
    return {
        "id": user_id or str(uuid.uuid4()),
        "email": email,
        "phone": phone,
        "user_metadata": user_metadata or {"full_name": "Test User"},
        "app_metadata": app_metadata or {"provider": "phone", "providers": ["phone"]},
        "email_confirmed_at": email_confirmed_at,
        "phone_confirmed_at": phone_confirmed_at,
    }


def _ok_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.text = ""
    return resp


def _status_response(status: int, body: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    return resp


class TestGetSupabaseClients:
    """Tests for Supabase client creation helpers."""

    def test_get_supabase_auth_http_client_creates_singleton(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()

            mgr = SupabaseClientManager()
            client_one = mgr.get_auth_client()
            client_two = mgr.get_auth_client()

            assert mock_create.call_count == 1
            assert client_one is client_two
            assert mock_create.call_args.kwargs["options"].httpx_client is not None

    def test_get_supabase_auth_http_client_requires_publishable_key(self):
        from unittest.mock import PropertyMock

        mgr = SupabaseClientManager()
        with patch.object(
            type(settings),
            "SUPABASE_CLIENT_KEY",
            new_callable=PropertyMock,
            return_value="",
        ):
            with pytest.raises(ValueError, match="Missing Supabase publishable key"):
                mgr.get_auth_client()

    def test_get_supabase_service_client_creates_singleton(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()

            mgr = SupabaseClientManager()
            client_one = mgr.get_service_client()
            client_two = mgr.get_service_client()

            assert mock_create.call_count == 1
            assert client_one is client_two


class TestVerifySupabaseToken:
    """Tests for verify_supabase_token via Supabase API."""

    @pytest.mark.asyncio
    async def test_verify_token_success(self):
        user_id = str(uuid.uuid4())
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response(
            _mock_supabase_user(
                user_id=user_id,
                phone_confirmed_at="2025-01-01T00:00:00Z",
            )
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("valid_jwt")

        assert result is not None
        assert not _is_failure(result)
        assert result["id"] == user_id
        assert result["email"] == "test@example.com"
        assert result["phone"] == "+919876543210"
        # email_verified tracks EMAIL confirmation only; here only the phone is
        # confirmed, so email_verified is False and phone_verified is True.
        assert result["email_verified"] is False
        assert result["phone_verified"] is True
        assert result["app_metadata"] == {"provider": "phone", "providers": ["phone"]}
        assert result["email_confirmed_at"] is None
        assert result["phone_confirmed_at"] == "2025-01-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_verify_token_email_only_confirmed(self):
        """email confirmed but phone not → email_verified True, phone_verified False."""
        user_id = str(uuid.uuid4())
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response(
            _mock_supabase_user(
                user_id=user_id,
                email="verified@example.com",
                phone=None,
                app_metadata={"providers": ["email", "google"]},
                email_confirmed_at="2025-02-02T00:00:00Z",
            )
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("valid_jwt")

        assert result is not None
        assert result["email_verified"] is True
        assert result["phone_verified"] is False
        assert result["email_confirmed_at"] == "2025-02-02T00:00:00Z"
        assert result["phone_confirmed_at"] is None
        assert result["app_metadata"] == {"providers": ["email", "google"]}

    @pytest.mark.asyncio
    async def test_verify_token_unverified_defaults_metadata(self):
        """No confirmations and missing app_metadata → flags False, app_metadata {}."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response(
            {
                "id": str(uuid.uuid4()),
                "email": "unverified@example.com",
                "phone": "+910000000000",
                "user_metadata": {},
                "email_confirmed_at": None,
                "phone_confirmed_at": None,
            }
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("valid_jwt")

        assert result is not None
        assert result["email_verified"] is False
        assert result["phone_verified"] is False
        assert result["app_metadata"] == {}

    @pytest.mark.asyncio
    async def test_verify_token_401_returns_none(self):
        """Non-200 (e.g. 401) is treated as invalid_token, returns None."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _status_response(401, "Invalid token")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("invalid_jwt")

        assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_missing_id_returns_none(self):
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response({"email": "x@example.com"})

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("jwt_without_id")

        assert result is None

    @pytest.mark.asyncio
    async def test_verify_token_connect_error_returns_tagged_failure(self):
        """Two ConnectError attempts → tagged provider_unreachable failure."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError(
            "[Errno 8] nodename nor servname provided, or not known"
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("any_jwt")

        assert _is_failure(result)
        assert result["reason"] == AuthFailureReason.PROVIDER_UNREACHABLE.value
        assert "nodename" in result["error"]

    @pytest.mark.asyncio
    async def test_verify_token_gaierror_returns_tagged_failure(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = socket.gaierror("Name or service not known")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("any_jwt")

        assert _is_failure(result)
        assert result["reason"] == AuthFailureReason.PROVIDER_UNREACHABLE.value

    @pytest.mark.asyncio
    async def test_verify_token_retries_then_succeeds(self):
        """One transient failure, then a 200 — the call succeeds after retry."""
        ok = _ok_response(_mock_supabase_user(phone_confirmed_at="2025-01-01T00:00:00Z"))
        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            httpx.ConnectError("transient"),
            ok,
        ]

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("valid_jwt")

        assert not _is_failure(result)
        assert result is not None
        assert mock_client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_verify_token_retry_exhausted_returns_tagged_failure(self):
        """Both attempts raise ConnectError → tagged failure after exhausting retries."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("still down")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("any_jwt")

        assert _is_failure(result)
        assert result["reason"] == AuthFailureReason.PROVIDER_UNREACHABLE.value
        assert mock_client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_verify_token_non_retryable_error_returns_tagged_provider_error(self):
        """Non-retryable exception → tagged provider_error (not provider_unreachable)."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = ValueError("something unexpected")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.verify_token("any_jwt")

        assert _is_failure(result)
        assert result["reason"] == AuthFailureReason.PROVIDER_ERROR.value


class TestAdminFindUserByPhone:
    """Tests for admin_find_user_by_phone function."""

    @pytest.mark.asyncio
    async def test_find_user_success(self):
        user_id = str(uuid.uuid4())
        phone = "+919876543210"
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response(
            {"users": [{"id": user_id, "email": "test@example.com", "phone": phone}]}
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_find_user_by_phone(phone)

        assert result is not None
        assert not _is_failure(result)
        assert result["id"] == user_id
        assert result["phone"] == phone

    @pytest.mark.asyncio
    async def test_find_user_surfaces_confirmed_at_and_app_metadata(self):
        user_id = str(uuid.uuid4())
        phone = "+919876543210"
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response(
            {
                "users": [
                    {
                        "id": user_id,
                        "email": "test@example.com",
                        "phone": phone,
                        "user_metadata": {"name": "Test"},
                        "app_metadata": {"providers": ["phone"]},
                        "email_confirmed_at": None,
                        "phone_confirmed_at": "2025-03-03T00:00:00Z",
                    }
                ]
            }
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_find_user_by_phone(phone)

        assert result is not None
        assert result["phone_confirmed_at"] == "2025-03-03T00:00:00Z"
        assert result["email_confirmed_at"] is None
        assert result["app_metadata"] == {"providers": ["phone"]}

    @pytest.mark.asyncio
    async def test_find_user_not_found(self):
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response({"users": []})

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_find_user_by_phone("+919999999999")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_user_404_response(self):
        mock_client = AsyncMock()
        mock_client.get.return_value = _status_response(404)

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_find_user_by_phone("+919876543210")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_user_phone_mismatch(self):
        mock_client = AsyncMock()
        mock_client.get.return_value = _ok_response(
            {"users": [{"id": str(uuid.uuid4()), "phone": "+919999999999"}]}
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_find_user_by_phone("+919876543210")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_user_connect_error_returns_tagged_failure(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("DNS fail")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_find_user_by_phone("+919876543210")

        assert _is_failure(result)
        assert result["reason"] == AuthFailureReason.PROVIDER_UNREACHABLE.value


class TestAdminCreateUser:
    @pytest.mark.asyncio
    async def test_create_user_success(self):
        user_id = str(uuid.uuid4())
        mock_client = AsyncMock()
        mock_client.post.return_value = _ok_response(
            {"id": user_id, "email": "new@example.com"}
        )

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_create_user("new@example.com", "p@ssw0rd!")

        assert result == {"id": user_id, "email": "new@example.com"}

    @pytest.mark.asyncio
    async def test_create_user_409_returns_none(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = _status_response(409, "duplicate")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_create_user("dup@example.com", "p@ssw0rd!")

        assert result is None

    @pytest.mark.asyncio
    async def test_create_user_connect_error_returns_tagged_failure(self):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("DNS fail")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_create_user("new@example.com", "p@ssw0rd!")

        assert _is_failure(result)
        assert result["reason"] == AuthFailureReason.PROVIDER_UNREACHABLE.value


class TestAdminLinkIdentity:
    @pytest.mark.asyncio
    async def test_link_success(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = _ok_response({"identity_id": "abc"})

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_link_identity("user-1", "google", "id-tok")

        assert result is True

    @pytest.mark.asyncio
    async def test_link_failure_returns_false(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = _status_response(400, "bad")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_link_identity("user-1", "google", "id-tok")

        assert result is False

    @pytest.mark.asyncio
    async def test_link_connect_error_returns_tagged_failure(self):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("DNS fail")

        with patch(
            "app.core.auth.get_supabase_auth_http_client", return_value=mock_client
        ):
            mgr = SupabaseClientManager()
            result = await mgr.admin_link_identity("user-1", "google", "id-tok")

        assert _is_failure(result)
        assert result["reason"] == AuthFailureReason.PROVIDER_UNREACHABLE.value


class TestSupabaseClientManagerClose:
    """Tests for SupabaseClientManager.close() lifecycle method."""

    @pytest.mark.asyncio
    async def test_close_releases_sync_clients(self):
        mgr = SupabaseClientManager()
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            mgr.get_auth_client()
            mgr.get_service_client()
            assert mgr._auth_client is not None
            assert mgr._service_client is not None

        await mgr.close()

        assert mgr._auth_client is None
        assert mgr._service_client is None

    @pytest.mark.asyncio
    async def test_close_noop_when_clients_are_none(self):
        mgr = SupabaseClientManager()
        await mgr.close()
        assert mgr._auth_client is None
        assert mgr._service_client is None


class TestModuleLevelWrappers:
    """Tests that module-level convenience wrappers delegate to the singleton."""

    def test_get_supabase_auth_client_delegates(self):
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            import app.core.auth as auth_module

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

    @pytest.mark.asyncio
    async def test_close_supabase_clients_releases_manager_state(self):
        import app.core.auth as auth_module

        auth_module._manager = SupabaseClientManager()
        with patch("app.core.auth.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            auth_module._manager.get_auth_client()
            assert auth_module._manager._auth_client is not None

        await auth_module.close_supabase_clients()
        assert auth_module._manager._auth_client is None

    def test_close_supabase_auth_http_client_is_alias(self):
        import app.core.auth as auth_module

        assert auth_module.close_supabase_auth_http_client is auth_module.close_supabase_clients

    def test_get_supabase_auth_http_client_uses_shared_registry(self):
        """The auth code should pull from the shared http client registry."""
        from app.core import http as http_module

        # Reset shared client to ensure a clean call
        http_module._supabase_auth_client = None

        mgr = SupabaseClientManager()
        # The auth manager no longer exposes get_auth_http_client; verify
        # call sites use the shared client accessor.
        assert not hasattr(mgr, "get_auth_http_client")
        # And the module-level accessor is the shared one.
        assert get_supabase_auth_http_client is http_module.get_supabase_auth_http_client
        # Sanity: calling the shared accessor creates the client.
        client = get_supabase_auth_http_client()
        assert isinstance(client, httpx.AsyncClient)
        # cleanup
        async def _cleanup() -> None:
            await http_module.close_all_clients()
        # schedule cleanup via the loop if running, else leave to GC
        try:
            import asyncio
            asyncio.get_event_loop().run_until_complete(_cleanup())
        except RuntimeError:
            pass


class TestFailureTagging:
    """Tests for the failure-tagging helpers."""

    def test_make_failure_and_is_failure_roundtrip(self):
        result = _make_failure(AuthFailureReason.PROVIDER_UNREACHABLE, "boom")
        assert _is_failure(result)
        assert result["reason"] == "provider_unreachable"
        assert result["error"] == "boom"

    def test_plain_dict_is_not_failure(self):
        assert not _is_failure({"id": "abc", "email": "x@y.z"})
        assert not _is_failure(None)
        assert not _is_failure({"__auth_failure__": False})
