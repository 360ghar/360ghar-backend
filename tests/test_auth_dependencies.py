"""
Tests for authentication dependencies module.

Tests cover:
- Bearer token parsing
- User authentication flow
- Role-based access control (agent, admin)
- Optional authentication
- Error handling and edge cases
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.api.api_v1.dependencies.auth import (
    _parse_bearer_token,
    get_current_user,
    get_current_active_user,
    get_current_user_optional,
    get_current_agent,
    get_current_admin,
)
from app.models.enums import UserRole


class TestParseBearerToken:
    """Tests for _parse_bearer_token helper function."""

    def test_parse_valid_bearer_token(self) -> None:
        """Valid Bearer token should be extracted correctly."""
        token = _parse_bearer_token("Bearer abc123token")
        assert token == "abc123token"

    def test_parse_bearer_token_case_insensitive(self) -> None:
        """Bearer scheme should be case-insensitive."""
        assert _parse_bearer_token("bearer mytoken") == "mytoken"
        assert _parse_bearer_token("BEARER mytoken") == "mytoken"
        assert _parse_bearer_token("BeArEr mytoken") == "mytoken"

    def test_parse_bearer_token_missing_header(self) -> None:
        """Missing authorization header should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            _parse_bearer_token(None)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "AUTH_HEADER_MISSING"

    def test_parse_bearer_token_empty_string(self) -> None:
        """Empty authorization header should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            _parse_bearer_token("")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "AUTH_HEADER_MISSING"

    def test_parse_bearer_token_invalid_format_no_space(self) -> None:
        """Authorization header without space should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            _parse_bearer_token("Bearertoken")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "INVALID_AUTH_HEADER"

    def test_parse_bearer_token_wrong_scheme(self) -> None:
        """Non-Bearer scheme should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            _parse_bearer_token("Basic abc123")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "INVALID_AUTH_SCHEME"

    def test_parse_bearer_token_multiple_spaces(self) -> None:
        """Token with extra spaces should raise error."""
        with pytest.raises(HTTPException) as exc_info:
            _parse_bearer_token("Bearer token with spaces")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "INVALID_AUTH_HEADER"


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_get_current_user_success(self) -> None:
        """Valid token should return authenticated user."""
        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = 123
        mock_user.is_active = True

        with patch(
            "app.api.api_v1.dependencies.auth.verify_supabase_token",
            new_callable=AsyncMock,
        ) as mock_verify, patch(
            "app.api.api_v1.dependencies.auth.get_or_create_user_from_supabase",
            new_callable=AsyncMock,
        ) as mock_get_user:
            mock_verify.return_value = {"id": "supabase-id", "email": "test@test.com"}
            mock_get_user.return_value = mock_user

            result = await get_current_user(mock_request, "Bearer valid_token", mock_db)

            assert result == mock_user
            assert mock_request.state.user_id == 123
            mock_verify.assert_called_once_with("valid_token")

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self) -> None:
        """Invalid token should raise 401."""
        mock_request = MagicMock()
        mock_db = AsyncMock()

        with patch(
            "app.api.api_v1.dependencies.auth.verify_supabase_token",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(mock_request, "Bearer invalid_token", mock_db)

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail["code"] == "TOKEN_INVALID"

    @pytest.mark.asyncio
    async def test_get_current_user_verification_exception(self) -> None:
        """Exception during verification should raise 401."""
        mock_request = MagicMock()
        mock_db = AsyncMock()

        with patch(
            "app.api.api_v1.dependencies.auth.verify_supabase_token",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.side_effect = Exception("Network error")

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(mock_request, "Bearer token", mock_db)

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail["code"] == "AUTHENTICATION_FAILED"


class TestGetCurrentActiveUser:
    """Tests for get_current_active_user dependency."""

    @pytest.mark.asyncio
    async def test_active_user_passes(self) -> None:
        """Active user should pass through."""
        mock_user = MagicMock()
        mock_user.is_active = True

        result = await get_current_active_user(mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_inactive_user_raises_403(self) -> None:
        """Inactive user should raise 403."""
        mock_user = MagicMock()
        mock_user.is_active = False

        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(mock_user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "USER_INACTIVE"

    @pytest.mark.asyncio
    async def test_user_without_is_active_attribute_raises_403(self) -> None:
        """User without is_active attribute should raise 403."""
        mock_user = MagicMock(spec=[])

        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(mock_user)

        assert exc_info.value.status_code == 403


class TestGetCurrentUserOptional:
    """Tests for get_current_user_optional dependency."""

    @pytest.mark.asyncio
    async def test_no_authorization_returns_none(self) -> None:
        """Missing authorization should return None."""
        mock_request = MagicMock()
        mock_db = AsyncMock()

        result = await get_current_user_optional(mock_request, None, mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self) -> None:
        """Valid token should return user."""
        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = 456

        with patch(
            "app.api.api_v1.dependencies.auth.verify_supabase_token",
            new_callable=AsyncMock,
        ) as mock_verify, patch(
            "app.api.api_v1.dependencies.auth.get_or_create_user_from_supabase",
            new_callable=AsyncMock,
        ) as mock_get_user:
            mock_verify.return_value = {"id": "supabase-id"}
            mock_get_user.return_value = mock_user

            result = await get_current_user_optional(
                mock_request, "Bearer valid_token", mock_db
            )

            assert result == mock_user
            assert mock_request.state.user_id == 456

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self) -> None:
        """Invalid token should return None (not raise)."""
        mock_request = MagicMock()
        mock_db = AsyncMock()

        with patch(
            "app.api.api_v1.dependencies.auth.verify_supabase_token",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = None

            result = await get_current_user_optional(
                mock_request, "Bearer invalid", mock_db
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self) -> None:
        """Exception during verification should return None."""
        mock_request = MagicMock()
        mock_db = AsyncMock()

        with patch(
            "app.api.api_v1.dependencies.auth._parse_bearer_token",
        ) as mock_parse:
            mock_parse.side_effect = Exception("Parse error")

            result = await get_current_user_optional(
                mock_request, "Bearer token", mock_db
            )

            assert result is None


class TestGetCurrentAgent:
    """Tests for get_current_agent dependency."""

    @pytest.mark.asyncio
    async def test_agent_role_passes(self) -> None:
        """User with agent role should pass."""
        mock_user = MagicMock()
        mock_user.role = UserRole.agent.value

        result = await get_current_agent(mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_user_role_raises_403(self) -> None:
        """User with user role should raise 403."""
        mock_user = MagicMock()
        mock_user.role = UserRole.user.value

        with pytest.raises(HTTPException) as exc_info:
            await get_current_agent(mock_user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "AGENT_REQUIRED"

    @pytest.mark.asyncio
    async def test_admin_role_raises_403(self) -> None:
        """Admin role should also raise 403 (not an agent)."""
        mock_user = MagicMock()
        mock_user.role = UserRole.admin.value

        with pytest.raises(HTTPException) as exc_info:
            await get_current_agent(mock_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_role_raises_403(self) -> None:
        """User without role attribute should raise 403."""
        mock_user = MagicMock(spec=[])

        with pytest.raises(HTTPException) as exc_info:
            await get_current_agent(mock_user)

        assert exc_info.value.status_code == 403


class TestGetCurrentAdmin:
    """Tests for get_current_admin dependency."""

    @pytest.mark.asyncio
    async def test_admin_role_passes(self) -> None:
        """User with admin role should pass."""
        mock_user = MagicMock()
        mock_user.role = UserRole.admin.value

        result = await get_current_admin(mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_user_role_raises_403(self) -> None:
        """User with user role should raise 403."""
        mock_user = MagicMock()
        mock_user.role = UserRole.user.value

        with pytest.raises(HTTPException) as exc_info:
            await get_current_admin(mock_user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_agent_role_raises_403(self) -> None:
        """Agent role should also raise 403 (not an admin)."""
        mock_user = MagicMock()
        mock_user.role = UserRole.agent.value

        with pytest.raises(HTTPException) as exc_info:
            await get_current_admin(mock_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_role_raises_403(self) -> None:
        """User without role attribute should raise 403."""
        mock_user = MagicMock(spec=[])

        with pytest.raises(HTTPException) as exc_info:
            await get_current_admin(mock_user)

        assert exc_info.value.status_code == 403
