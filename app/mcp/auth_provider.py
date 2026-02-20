from __future__ import annotations

import time
from typing import Optional, Sequence

import fastmcp
from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier

from app.core.config import settings
from app.core.logging import get_logger


logger = get_logger(__name__)


def get_public_base_url() -> str:
    """Return the public base URL (scheme+host) for OAuth metadata and resource binding."""
    public_base_url = getattr(settings, "PUBLIC_BASE_URL", None)
    if public_base_url:
        return public_base_url.rstrip("/")

    if settings.ENVIRONMENT == "production":
        return "https://api.360ghar.com"

    return "http://localhost:8000"


class SupabaseTokenVerifier(TokenVerifier):
    """
    Token verifier that validates both Supabase JWT access tokens and
    first‑party OAuth access tokens issued by this backend.

    It returns a FastMCP `AccessToken` with rich `claims` that downstream
    MCP tools can use to resolve the current user.

    Implements audience validation per RFC 8707 to prevent token passthrough attacks.
    """

    def __init__(
        self,
        required_scopes: Optional[list[str]] | None = None,
        expected_resource: Optional[str] = None,
        expected_resources: Optional[Sequence[str]] = None,
    ):
        super().__init__(base_url=None, required_scopes=required_scopes)
        allowed: list[str] = []
        if expected_resource:
            allowed.append(expected_resource)
        if expected_resources:
            allowed.extend([r for r in expected_resources if r])

        self.expected_resources = {r.rstrip("/") for r in allowed if isinstance(r, str) and r.strip()}

    async def verify_token(self, token: str) -> AccessToken | None:
        """
        Verify the provided bearer token.

        Only first-party OAuth access tokens from our token store are accepted.
        Supabase JWT tokens are no longer supported in MCP endpoints.
        """
        logger.debug("Verifying OAuth token", extra={"token_len": len(token) if token else 0})
        scopes = self.required_scopes or ["mcp:read", "mcp:write"]

        # OAuth access token verification
        try:
            # Our OAuth access tokens are long, random strings without dots
            if len(token) > 40 and "." not in token:
                from app.services.oauth_token_store import oauth_token_store

                logger.debug("Looking up token in OAuth store")
                token_data = await oauth_token_store.get_access_token(token)
                if token_data:
                    user_id = token_data["user_id"]
                    expires_at_raw = token_data.get("expires_at")
                    expires_at = int(expires_at_raw) if expires_at_raw else None
                    token_resource = token_data.get("resource")
                    logger.debug("Token found in store", extra={"user_id": user_id, "resource": token_resource})

                    # Expiration check
                    if expires_at and time.time() > expires_at:
                        logger.warning(
                            "Token has expired",
                            extra={"user_id": user_id, "expires_at": expires_at}
                        )
                        return None

                    # Audience validation (RFC 8707)
                    # If the token was issued for a specific resource, validate it
                    if token_resource and self.expected_resources:
                        normalized = str(token_resource).rstrip("/")
                        if normalized not in self.expected_resources:
                            logger.warning(
                                "Token audience mismatch",
                                extra={
                                    "expected": sorted(self.expected_resources),
                                    "got": token_resource,
                                    "user_id": user_id,
                                }
                            )
                            return None

                    claims = {
                        "sub": user_id,
                        "auth_method": "oauth",
                        "scope": token_data.get("scope", "mcp:read mcp:write"),
                        "resource": token_resource,
                    }

                    if "email" in token_data:
                        claims["email"] = token_data["email"]
                    if "phone" in token_data:
                        claims["phone"] = token_data["phone"]

                    token_scopes = claims["scope"].split()

                    # Scope validation
                    if self.required_scopes:
                        missing_scopes = set(self.required_scopes) - set(token_scopes)
                        if missing_scopes:
                            logger.warning(
                                "Token missing required scopes",
                                extra={
                                    "user_id": user_id,
                                    "required": self.required_scopes,
                                    "got": token_scopes,
                                    "missing": list(missing_scopes),
                                }
                            )
                            return None

                    logger.info("OAuth token verified", extra={"user_id": user_id, "scope": claims["scope"]})

                    return AccessToken(
                        token=token,
                        client_id=token_data.get("client_id", "ghar360-mcp"),
                        scopes=token_scopes,
                        expires_at=expires_at,
                        resource=token_resource,
                        claims=claims,
                    )
                else:
                    logger.debug("Token not found in OAuth store")
            else:
                logger.debug("Token format not recognized as OAuth token", extra={"has_dots": "." in token})
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error verifying OAuth token", extra={"error": str(exc)}, exc_info=True)

        logger.debug("Token verification failed")
        return None


class SupabaseAuthProvider(RemoteAuthProvider):
    """
    RemoteAuthProvider that validates first-party OAuth access tokens
    for MCP HTTP endpoints.

    It exposes protected resource metadata for the MCP endpoints and
    advertises the backend's OAuth authorization server located under
    `/mcp/oauth/*`.

    Note: Supabase JWT authentication is no longer supported in MCP endpoints.
    All MCP clients must use OAuth 2.1 authorization code flow.
    """

    def __init__(self) -> None:
        """
        Initialize the auth provider using backend configuration.

        FastMCP may instantiate this class without arguments based on the
        `FASTMCP_SERVER_AUTH` setting. We derive the public base URL from
        configuration so that MCP HTTP auth works in both local and production
        environments.
        """
        public_base_url = get_public_base_url()

        # Resource server base URL (used to build the protected `/mcp` URL)
        resource_base_url = public_base_url
        expected_resource = f"{public_base_url}/mcp"

        # OAuth authorization server issuer URL (path-aware as per RFC 8414)
        # This will result in metadata being discovered at:
        #   {scheme}://{host}/.well-known/oauth-authorization-server/mcp/oauth
        auth_server_url = f"{public_base_url}/mcp/oauth"

        # Initialize token verifier with required scopes and expected resource for audience validation
        required_scopes = ["mcp:read", "mcp:write"]
        token_verifier = SupabaseTokenVerifier(
            required_scopes=required_scopes,
            expected_resource=expected_resource,
        )

        super().__init__(
            token_verifier=token_verifier,
            authorization_servers=[auth_server_url],
            base_url=resource_base_url,
            resource_name="360Ghar MCP API",
            resource_documentation=f"{public_base_url}/docs",
        )


def configure_fastmcp_auth() -> None:
    """
    Configure the global FastMCP `server_auth` setting so that any FastMCP
    server created in this process automatically uses SupabaseAuthProvider
    for HTTP auth.

    This is designed to be called exactly once on startup.
    """
    if fastmcp.settings.server_auth is None:
        fastmcp.settings.server_auth = "app.mcp.auth_provider.SupabaseAuthProvider"
        logger.info("FastMCP auth configured", extra={"provider": "SupabaseAuthProvider"})
    else:
        logger.debug("FastMCP auth already configured", extra={"provider": fastmcp.settings.server_auth})
