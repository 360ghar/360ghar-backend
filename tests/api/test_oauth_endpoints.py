"""
Tests for OAuth endpoints.

These tests verify the OAuth-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import base64
import hashlib

import pytest
from httpx import AsyncClient


# Helper to generate PKCE pair
def generate_pkce_pair():
    """Generate a valid PKCE code_verifier and code_challenge pair."""
    verifier = "test_verifier_12345678901234567890123456789012345678"
    hash_obj = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(hash_obj).decode("ascii").rstrip("=")
    return verifier, challenge


class TestOAuthAuthorizeEndpoint:
    """Tests for GET /api/v1/mcp/oauth/authorize endpoint."""

    @pytest.mark.asyncio
    async def test_authorize_success(self, client: AsyncClient):
        """Test OAuth authorize redirect with PKCE."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.store_oauth_session = AsyncMock()

            _, challenge = generate_pkce_pair()

            response = await client.get(
                "/api/v1/mcp/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": "ghar360-mcp",
                    "redirect_uri": "http://localhost:3000/callback",
                    "scope": "mcp:read mcp:write",
                    "state": "test_state",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                follow_redirects=False,
            )

            # Should redirect to consent page
            assert response.status_code in [302, 307]

    @pytest.mark.asyncio
    async def test_authorize_missing_pkce(self, client: AsyncClient):
        """Test authorize without PKCE returns error."""
        response = await client.get(
            "/api/v1/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "ghar360-mcp",
                "redirect_uri": "http://localhost:3000/callback",
                # Missing code_challenge and code_challenge_method
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_request"
        assert "PKCE" in data["error_description"]

    @pytest.mark.asyncio
    async def test_authorize_invalid_response_type(self, client: AsyncClient):
        """Test authorize with invalid response type."""
        _, challenge = generate_pkce_pair()

        response = await client.get(
            "/api/v1/mcp/oauth/authorize",
            params={
                "response_type": "token",  # Only "code" is supported
                "client_id": "ghar360-mcp",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_authorize_missing_client_id(self, client: AsyncClient):
        """Test authorize without client ID."""
        response = await client.get(
            "/api/v1/mcp/oauth/authorize",
            params={
                "response_type": "code",
            },
        )

        # Missing required parameter
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_authorize_invalid_client_id(self, client: AsyncClient):
        """Test authorize with invalid client ID."""
        _, challenge = generate_pkce_pair()

        response = await client.get(
            "/api/v1/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "invalid_client",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_client"


class TestOAuthTokenEndpoint:
    """Tests for POST /api/v1/mcp/oauth/token endpoint."""

    @pytest.mark.asyncio
    async def test_token_authorization_code_grant(self, client: AsyncClient):
        """Test token exchange with authorization code."""
        verifier, challenge = generate_pkce_pair()

        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_auth_code = AsyncMock(
                return_value={
                    "user_id": "1",
                    "client_id": "ghar360-mcp",
                    "redirect_uri": "http://localhost:3000/callback",
                    "scope": "mcp:read mcp:write",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "resource": "http://testserver/mcp",
                }
            )
            mock_store.store_oauth_tokens = AsyncMock()

            response = await client.post(
                "/api/v1/mcp/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "test_auth_code",
                    "client_id": "ghar360-mcp",
                    "redirect_uri": "http://localhost:3000/callback",
                    "code_verifier": verifier,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data
            assert data["token_type"] == "Bearer"

    @pytest.mark.asyncio
    async def test_token_missing_code(self, client: AsyncClient):
        """Test token exchange without authorization code."""
        response = await client.post(
            "/api/v1/mcp/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "ghar360-mcp",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_token_invalid_code(self, client: AsyncClient):
        """Test token exchange with invalid authorization code."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_auth_code = AsyncMock(return_value=None)

            response = await client.post(
                "/api/v1/mcp/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "invalid_code",
                    "client_id": "ghar360-mcp",
                },
            )

            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_token_refresh_grant(self, client: AsyncClient):
        """Test token refresh."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_refresh_token = AsyncMock(
                return_value={
                    "user_id": "1",
                    "scope": "mcp:read mcp:write",
                    "resource": "http://testserver/mcp",
                }
            )
            mock_store.store_oauth_tokens = AsyncMock()
            mock_store.revoke_refresh_token = AsyncMock()

            response = await client.post(
                "/api/v1/mcp/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": "test_refresh_token",
                    "client_id": "ghar360-mcp",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_token_invalid_refresh_token(self, client: AsyncClient):
        """Test token refresh with invalid refresh token."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_refresh_token = AsyncMock(return_value=None)

            response = await client.post(
                "/api/v1/mcp/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": "invalid_token",
                },
            )

            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_token_refresh_missing_client_id_for_bound_token(self, client: AsyncClient):
        """Refresh token bound to a client_id must include client_id in request."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_refresh_token = AsyncMock(
                return_value={
                    "user_id": "1",
                    "scope": "mcp:read mcp:write",
                    "resource": "http://testserver/mcp",
                    "client_id": "ghar360-mcp",
                }
            )

            response = await client.post(
                "/api/v1/mcp/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": "test_refresh_token",
                },
            )

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_token_refresh_invalid_client_id_for_bound_token(self, client: AsyncClient):
        """Refresh token should reject mismatched client_id."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_refresh_token = AsyncMock(
                return_value={
                    "user_id": "1",
                    "scope": "mcp:read mcp:write",
                    "resource": "http://testserver/mcp",
                    "client_id": "ghar360-mcp",
                }
            )

            response = await client.post(
                "/api/v1/mcp/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": "test_refresh_token",
                    "client_id": "not-ghar360-mcp",
                },
            )

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "invalid_client"

    @pytest.mark.asyncio
    async def test_token_unsupported_grant_type(self, client: AsyncClient):
        """Test token with unsupported grant type."""
        response = await client.post(
            "/api/v1/mcp/oauth/token",
            data={
                "grant_type": "client_credentials",
            },
        )

        assert response.status_code == 400


class TestOAuthConsentEndpoint:
    """Tests for /api/v1/mcp/oauth/consent endpoint."""

    @pytest.mark.asyncio
    async def test_consent_page_missing_session(self, client: AsyncClient):
        """Test consent page without session."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_oauth_session = AsyncMock(return_value=None)

            response = await client.get(
                "/api/v1/mcp/oauth/consent",
                params={"session": "invalid_session"},
            )

            assert response.status_code == 400


class TestDynamicClientRegistration:
    """Tests for Dynamic Client Registration (RFC 7591)."""

    @pytest.mark.asyncio
    async def test_register_client_success(self, client: AsyncClient):
        """Test successful client registration."""
        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.store_client = AsyncMock(return_value=True)

            response = await client.post(
                "/api/v1/mcp/oauth/register",
                json={
                    "client_name": "Test MCP Client",
                    "redirect_uris": ["http://localhost:3000/callback"],
                    "client_uri": "https://example.com",
                    "grant_types": ["authorization_code"],
                    "response_types": ["code"],
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert "client_id" in data
            assert data["client_name"] == "Test MCP Client"
            # Public client - client_secret should be omitted (not null)
            assert "client_secret" not in data
            assert "client_secret_expires_at" not in data
            assert "client_id_issued_at" in data

    @pytest.mark.asyncio
    async def test_register_client_missing_name(self, client: AsyncClient):
        """Test client registration without client_name."""
        response = await client.post(
            "/api/v1/mcp/oauth/register",
            json={
                "redirect_uris": ["http://localhost:3000/callback"],
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_client_missing_redirect_uris(self, client: AsyncClient):
        """Test client registration without redirect_uris."""
        response = await client.post(
            "/api/v1/mcp/oauth/register",
            json={
                "client_name": "Test Client",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_client_invalid_redirect_uri(self, client: AsyncClient):
        """Test client registration with invalid redirect_uri (must be localhost or HTTPS)."""
        response = await client.post(
            "/api/v1/mcp/oauth/register",
            json={
                "client_name": "Test Client",
                "redirect_uris": ["http://evil.com/callback"],  # HTTP non-localhost
            },
        )

        assert response.status_code == 422


class TestProtectedResourceMetadata:
    """Tests for Protected Resource Metadata (RFC 9728)."""

    @pytest.mark.asyncio
    async def test_protected_resource_metadata(self, client: AsyncClient):
        """Test protected resource metadata endpoint."""
        response = await client.get(
            "/.well-known/oauth-protected-resource/mcp"
        )

        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
        assert "authorization_servers" in data
        assert "scopes_supported" in data
        assert "bearer_methods_supported" in data
        assert "header" in data["bearer_methods_supported"]

    @pytest.mark.asyncio
    async def test_protected_resource_metadata_alt(self, client: AsyncClient):
        """Test protected resource metadata at alternative path."""
        response = await client.get(
            "/.well-known/oauth-protected-resource"
        )

        assert response.status_code == 200
        data = response.json()
        assert "resource" in data


class TestAuthorizationServerMetadata:
    """Tests for Authorization Server Metadata (RFC 8414)."""

    @pytest.mark.asyncio
    async def test_authorization_server_metadata(self, client: AsyncClient):
        """Test authorization server metadata endpoint."""
        response = await client.get(
            "/.well-known/oauth-authorization-server/mcp/oauth"
        )

        assert response.status_code == 200
        data = response.json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "revocation_endpoint" in data
        assert "registration_endpoint" in data
        assert "response_types_supported" in data
        assert "grant_types_supported" in data
        assert "code" in data["response_types_supported"]
        assert "authorization_code" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]
        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]
        assert data.get("client_id_metadata_document_supported") is True


class TestPKCEVerification:
    """Tests for PKCE verification logic."""

    def test_verify_pkce_s256(self):
        """Test PKCE S256 verification."""
        from app.api.api_v1.endpoints.oauth import verify_pkce

        # Generate valid PKCE pair
        verifier = "test_verifier_12345"
        hash_obj = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(hash_obj).decode("ascii").rstrip("=")

        assert verify_pkce(challenge, verifier, "S256") is True
        assert verify_pkce(challenge, "wrong_verifier", "S256") is False

    def test_verify_pkce_plain(self):
        """Test PKCE plain verification."""
        from app.api.api_v1.endpoints.oauth import verify_pkce

        challenge = "test_challenge"
        verifier = "test_challenge"

        assert verify_pkce(challenge, verifier, "plain") is True
        assert verify_pkce(challenge, "wrong", "plain") is False

    def test_verify_pkce_missing_values(self):
        """Test PKCE with missing values."""
        from app.api.api_v1.endpoints.oauth import verify_pkce

        assert verify_pkce(None, "verifier", "S256") is False
        assert verify_pkce("challenge", None, "S256") is False
        assert verify_pkce(None, None, "S256") is False


class TestClientValidation:
    """Tests for client validation logic."""

    @pytest.mark.asyncio
    async def test_validate_first_party_client(self):
        """Test validation of first-party client."""
        from app.api.api_v1.endpoints.oauth import validate_client

        client = await validate_client("ghar360-mcp")
        assert client is not None
        assert client["client_id"] == "ghar360-mcp"
        assert client.get("is_first_party") is True

    @pytest.mark.asyncio
    async def test_validate_invalid_client(self):
        """Test validation of invalid client."""
        from app.api.api_v1.endpoints.oauth import validate_client

        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_client = AsyncMock(return_value=None)

            client = await validate_client("invalid_client_id")
            assert client is None

    @pytest.mark.asyncio
    async def test_validate_dynamically_registered_client(self):
        """Test validation of dynamically registered client."""
        from app.api.api_v1.endpoints.oauth import validate_client

        with patch(
            "app.api.api_v1.endpoints.oauth.oauth_token_store"
        ) as mock_store:
            mock_store.get_client = AsyncMock(
                return_value={
                    "client_id": "dyn_12345",
                    "client_name": "Dynamic Client",
                    "redirect_uris": ["http://localhost:3000/callback"],
                }
            )

            client = await validate_client("dyn_12345")
            assert client is not None
            assert client["client_id"] == "dyn_12345"


class TestOAuthRevokeEndpoint:
    """Tests for POST /api/v1/mcp/oauth/revoke endpoint."""

    @pytest.mark.asyncio
    async def test_revoke_refresh_token_success(self, client: AsyncClient):
        with patch("app.api.api_v1.endpoints.oauth.oauth_token_store") as mock_store:
            mock_store.get_refresh_token = AsyncMock(
                return_value={"client_id": "ghar360-mcp", "access_token": "a1"}
            )
            mock_store.revoke_refresh_token = AsyncMock(return_value=True)

            response = await client.post(
                "/api/v1/mcp/oauth/revoke",
                data={
                    "token": "refresh_123",
                    "token_type_hint": "refresh_token",
                    "client_id": "ghar360-mcp",
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_revoke_invalid_client_binding(self, client: AsyncClient):
        with patch("app.api.api_v1.endpoints.oauth.oauth_token_store") as mock_store:
            mock_store.get_access_token = AsyncMock(return_value={"client_id": "ghar360-mcp"})
            mock_store.revoke_token_pair = AsyncMock(return_value=True)

            response = await client.post(
                "/api/v1/mcp/oauth/revoke",
                data={
                    "token": "access_123",
                    "token_type_hint": "access_token",
                    "client_id": "wrong-client",
                },
            )

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "invalid_client"
