from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

wellknown_router = APIRouter()
mcp_discovery_router = APIRouter()


@wellknown_router.get("/.well-known/oauth-protected-resource/mcp", summary="Get protected resource metadata")
@wellknown_router.get("/.well-known/oauth-protected-resource", summary="Get protected resource metadata")
async def protected_resource_metadata(request: Request):
    """OAuth 2.0 Protected Resource Metadata (RFC 9728)."""
    base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")

    return {
        "resource": f"{base_url}/mcp",
        "authorization_servers": [f"{base_url}/mcp/oauth"],
        "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base_url}{settings.API_V1_STR}/docs",
    }


@wellknown_router.get("/.well-known/oauth-protected-resource/mcp-admin", summary="Get admin protected resource metadata")
async def protected_resource_metadata_admin(request: Request):
    """Protected resource metadata for the /mcp-admin endpoint."""
    base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")

    return {
        "resource": f"{base_url}/mcp-admin",
        "authorization_servers": [f"{base_url}/mcp/oauth"],
        "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base_url}{settings.API_V1_STR}/docs",
    }


@wellknown_router.get("/.well-known/oauth-authorization-server/mcp/oauth", summary="Get authorization server metadata")
async def authorization_server_metadata(request: Request):
    """OAuth 2.1 Authorization Server Metadata for the MCP OAuth issuer."""
    logger.info("OAuth AS metadata requested", extra={"path": str(request.url.path)})
    base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    issuer = f"{base_url}/mcp/oauth"

    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "revocation_endpoint": f"{issuer}/revoke",
        "registration_endpoint": f"{issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
        "service_documentation": f"{base_url}{settings.API_V1_STR}/docs",
        "ui_locales_supported": ["en"],
        "op_policy_uri": f"{base_url}/privacy",
        "op_tos_uri": f"{base_url}/terms",
    }


@wellknown_router.get("/.well-known/oauth-authorization-server", summary="Get authorization server metadata")
async def authorization_server_metadata_root(request: Request):
    """OAuth AS metadata at root path (without issuer suffix) for broad client compatibility."""
    return await authorization_server_metadata(request)


@wellknown_router.get("/.well-known/openid-configuration", summary="Get OpenID configuration")
async def openid_configuration(request: Request):
    """OpenID Connect discovery endpoint (alias for OAuth AS metadata)."""
    return await authorization_server_metadata(request)


@wellknown_router.get("/.well-known/openid-configuration/mcp/oauth", summary="Get OpenID configuration")
async def openid_configuration_alt(request: Request):
    """OpenID Connect discovery at alternative path format."""
    return await authorization_server_metadata(request)


@mcp_discovery_router.get("/mcp/oauth/.well-known/openid-configuration", summary="Get OpenID configuration")
async def openid_configuration_issuer(request: Request):
    """OpenID Connect discovery at issuer-appended path."""
    return await authorization_server_metadata(request)
