from __future__ import annotations

import base64
import hashlib
import ipaddress
import secrets
import socket
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse

import anyio
import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import admin_find_user_by_phone, get_supabase_auth_client, verify_supabase_token
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.services.oauth_token_store import oauth_token_store
from app.services.user import get_or_create_user_from_supabase

logger = get_logger(__name__)
router = APIRouter()

# Separate router for well-known endpoints that need to be mounted at root level.
# MCP clients expect these at /.well-known/... not /api/v1/.well-known/...
oauth_wellknown_router = APIRouter()

# Router for MCP OAuth endpoints at root level (/mcp/oauth/*).
oauth_mcp_router = APIRouter()

# OAuth configuration
OAUTH_AUTHORIZATION_CODE_LIFETIME = 600  # 10 minutes
OAUTH_ACCESS_TOKEN_LIFETIME = 3600  # 1 hour
OAUTH_REFRESH_TOKEN_LIFETIME = 86400 * 30  # 30 days

# ChatGPT redirect URIs per Apps SDK documentation
CHATGPT_REDIRECT_URIS = [
    "https://chatgpt.com/connector_platform_oauth_redirect",
    "https://platform.openai.com/apps-manage/oauth",
]


# =============================================================================
# Pydantic Schemas for OAuth
# =============================================================================

class OAuthAuthorizeRequest(BaseModel):
    response_type: str
    client_id: str
    redirect_uri: Optional[HttpUrl] = None
    scope: Optional[str] = None
    state: Optional[str] = None
    code_challenge: Optional[str] = None  # PKCE
    code_challenge_method: Optional[str] = None  # PKCE
    resource: Optional[str] = None


class OAuthTokenRequest(BaseModel):
    grant_type: str
    code: Optional[str] = None
    redirect_uri: Optional[HttpUrl] = None
    client_id: Optional[str] = None
    refresh_token: Optional[str] = None
    code_verifier: Optional[str] = None  # PKCE
    resource: Optional[str] = None


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 Dynamic Client Registration Request."""

    client_name: str
    redirect_uris: List[str]
    client_uri: Optional[str] = None
    logo_uri: Optional[str] = None
    contacts: Optional[List[str]] = None
    grant_types: Optional[List[str]] = None
    response_types: Optional[List[str]] = None
    token_endpoint_auth_method: Optional[str] = None
    scope: Optional[str] = None

    @field_validator("redirect_uris")
    @classmethod
    def validate_redirect_uris(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("At least one redirect_uri is required")
        for uri in v:
            if not (
                uri.startswith("http://127.0.0.1")
                or uri.startswith("http://localhost")
                or uri.startswith("https://")
            ):
                raise ValueError(f"redirect_uri must be localhost or HTTPS: {uri}")
        return v


# =============================================================================
# Helper Functions
# =============================================================================


def generate_auth_code() -> str:
    """Generate a secure authorization code."""
    return secrets.token_urlsafe(32)


def generate_access_token() -> str:
    """Generate a secure access token."""
    return secrets.token_urlsafe(32)


def generate_refresh_token() -> str:
    """Generate a secure refresh token."""
    return secrets.token_urlsafe(32)


def verify_pkce(
    code_challenge: Optional[str],
    code_verifier: Optional[str],
    method: Optional[str],
) -> bool:
    """Verify PKCE code challenge."""
    if not code_challenge or not code_verifier:
        return False

    if method == "S256":
        hash_obj = hashlib.sha256(code_verifier.encode("ascii")).digest()
        encoded = base64.urlsafe_b64encode(hash_obj).decode("ascii").rstrip("=")
        return secrets.compare_digest(encoded, code_challenge)
    if method == "plain":
        return secrets.compare_digest(code_verifier, code_challenge)

    return False


async def fetch_client_metadata(client_id: str) -> Optional[Dict[str, Any]]:
    """Fetch and validate Client ID Metadata Document for URL-based client_ids."""
    if not client_id.startswith("https://"):
        return None

    try:
        parsed = urlparse(client_id)
        if parsed.scheme != "https" or not parsed.hostname:
            return None

        if parsed.username or parsed.password:
            logger.warning("Rejected client_id with userinfo: %s", client_id)
            return None

        host = parsed.hostname
        if host.lower() in {"localhost"} or host.endswith(".local"):
            logger.warning("Rejected client_id pointing at localhost domain: %s", client_id)
            return None

        port = parsed.port or 443
        if port not in {443}:
            logger.warning("Rejected client_id with non-HTTPS port: %s", client_id)
            return None

        def _resolve_ips() -> list[str]:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            return [info[4][0] for info in infos if info and info[4]]

        try:
            ips = await anyio.to_thread.run_sync(_resolve_ips)
        except Exception as exc:
            logger.warning("Failed to resolve client_id host %s: %s", host, exc)
            return None

        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                logger.warning("Invalid IP for client_id host %s: %s", host, ip_str)
                return None

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                logger.warning("Rejected client_id resolving to non-public IP %s (%s)", ip_str, client_id)
                return None

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.get(client_id)
            if resp.status_code == 200:
                metadata = resp.json()
                if metadata.get("client_id") == client_id:
                    if "redirect_uris" in metadata and "client_name" in metadata:
                        logger.info("Fetched client metadata from %s", client_id)
                        return metadata
                    logger.warning("Client metadata missing required fields: %s", client_id)
                else:
                    logger.warning("Client ID mismatch in metadata document: %s", client_id)
    except Exception as exc:
        logger.warning("Failed to fetch client metadata from %s: %s", client_id, exc)

    return None


async def validate_client(client_id: str) -> Optional[Dict[str, Any]]:
    """Validate a client_id using first-party, DCR, or metadata discovery."""
    if client_id == "ghar360-mcp":
        return {
            "client_id": "ghar360-mcp",
            "client_name": "360Ghar MCP Client",
            "is_first_party": True,
            "redirect_uris": [],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }

    client = await oauth_token_store.get_client(client_id)
    if client:
        return client

    if client_id.startswith("https://"):
        metadata = await fetch_client_metadata(client_id)
        if metadata:
            return metadata

    return None


# =============================================================================
# Dynamic Client Registration (RFC 7591)
# =============================================================================


@router.post("/mcp/oauth/register")
@oauth_mcp_router.post("/mcp/oauth/register")
async def register_client(
    request: Request,
    registration: ClientRegistrationRequest,
):
    """RFC 7591 Dynamic Client Registration Endpoint."""
    try:
        client_id = f"dyn_{uuid.uuid4().hex[:16]}"

        client_metadata = {
            "client_id": client_id,
            "client_name": registration.client_name,
            "redirect_uris": registration.redirect_uris,
            "client_uri": registration.client_uri,
            "logo_uri": registration.logo_uri,
            "contacts": registration.contacts or [],
            "grant_types": registration.grant_types or ["authorization_code"],
            "response_types": registration.response_types or ["code"],
            "token_endpoint_auth_method": registration.token_endpoint_auth_method or "none",
            "scope": registration.scope or "mcp:read mcp:write",
        }

        success = await oauth_token_store.store_client(
            client_id=client_id,
            metadata=client_metadata,
            expires_in=None,
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "server_error",
                    "error_description": "Failed to store client registration",
                },
            )

        # Build response - omit client_secret fields for public clients (RFC 7591)
        response = {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            **client_metadata,
        }
        # Only include client_secret fields for confidential clients
        auth_method = client_metadata.get("token_endpoint_auth_method", "none")
        if auth_method != "none":
            # Confidential client - would need secret generation here
            response["client_secret"] = None
            response["client_secret_expires_at"] = 0

        logger.info("Registered new OAuth client: %s (%s)", client_id, registration.client_name)
        return JSONResponse(status_code=201, content=response)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Client registration error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "server_error",
                "error_description": "Internal server error during registration",
            },
        )


# =============================================================================
# OAuth 2.1 Authorization Endpoints
# =============================================================================


@router.get("/mcp/oauth/authorize")
@oauth_mcp_router.get("/mcp/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: Optional[str] = None,
    scope: Optional[str] = None,
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
    resource: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """OAuth 2.1 Authorization Endpoint."""
    logger.info("OAuth authorize request", extra={
        "client_id": client_id,
        "response_type": response_type,
        "has_pkce": bool(code_challenge),
        "resource": resource,
        "redirect_uri": redirect_uri,
    })
    base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")

    if response_type != "code":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_response_type",
                "error_description": "Only authorization code flow is supported",
            },
        )

    client = await validate_client(client_id)
    if not client:
        logger.warning("OAuth authorize - invalid client_id", extra={"client_id": client_id})
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_client",
                "error_description": "Invalid client_id. Register via /mcp/oauth/register or use a valid Client ID Metadata Document URL.",
            },
        )

    if not code_challenge or not code_challenge_method:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "error_description": "PKCE is required. Provide code_challenge and code_challenge_method parameters.",
            },
        )

    if code_challenge_method not in ["S256", "plain"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "error_description": "code_challenge_method must be 'S256' or 'plain'. S256 is recommended.",
            },
        )

    if client.get("redirect_uris"):
        if not redirect_uri:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_request",
                    "error_description": "redirect_uri is required for this client",
                },
            )
        is_chatgpt_uri = redirect_uri in CHATGPT_REDIRECT_URIS
        is_registered_uri = redirect_uri in client["redirect_uris"]
        if not is_chatgpt_uri and not is_registered_uri:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_request",
                    "error_description": "redirect_uri not registered for this client",
                },
            )

    session_id = secrets.token_urlsafe(16)

    allowed_resources = {
        f"{base_url}/mcp",
        f"{base_url}/sse",
        f"{base_url}/mcp-admin",
    }
    if resource and resource not in allowed_resources:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_target",
                "error_description": "Invalid resource value",
            },
        )

    effective_resource = resource or f"{base_url}/mcp"

    await oauth_token_store.store_oauth_session(
        session_id=session_id,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope or "mcp:read mcp:write",
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        resource=effective_resource,
        expires_in=1800,
    )

    login_url = f"{base_url}/mcp/oauth/consent?session={session_id}"
    return RedirectResponse(url=login_url)


@router.get("/mcp/oauth/consent", response_class=HTMLResponse)
@oauth_mcp_router.get("/mcp/oauth/consent", response_class=HTMLResponse)
async def consent_page(
    request: Request,
    session: str,
    db: AsyncSession = Depends(get_db),
):
    """OAuth consent and login page."""
    oauth_session = await oauth_token_store.get_oauth_session(session)
    if not oauth_session:
        raise HTTPException(status_code=400, detail="Invalid or expired session")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorize 360Ghar MCP Access</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 400px;
                margin: 100px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .logo {{
                text-align: center;
                margin-bottom: 30px;
                color: #333;
            }}
            .form-group {{
                margin-bottom: 20px;
            }}
            label {{
                display: block;
                margin-bottom: 5px;
                font-weight: 500;
            }}
            input {{
                width: 100%;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                box-sizing: border-box;
            }}
            button {{
                width: 100%;
                padding: 12px;
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
            }}
            button:hover {{
                background-color: #0056b3;
            }}
            .scopes {{
                background-color: #f8f9fa;
                padding: 15px;
                border-radius: 4px;
                margin-bottom: 20px;
            }}
            .error {{
                color: #dc3545;
                margin-bottom: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <h2>360Ghar</h2>
            </div>

            <h3>Authorize MCP Access</h3>
            <p>This application wants to access your 360Ghar account via MCP.</p>

            <div class="scopes">
                <strong>Requested permissions:</strong><br>
                {oauth_session.get('scope', 'mcp:read mcp:write').replace(' ', '<br>')}
            </div>

            <form id="loginForm" method="post">
                <div class="form-group">
                    <label for="phone">Phone Number:</label>
                    <input type="tel" id="phone" name="phone" required placeholder="+91XXXXXXXXXX">
                </div>

                <div class="form-group">
                    <label for="password">Password:</label>
                    <input type="password" id="password" name="password" required>
                </div>

                <input type="hidden" name="session" value="{session}">
                <input type="hidden" name="action" value="authorize">

                <button type="submit">Authorize Access</button>
            </form>

            <p style="text-align: center; margin-top: 20px; color: #666; font-size: 14px;">
                By authorizing, you allow this application to access your 360Ghar property data.
            </p>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=html_content)


@router.post("/mcp/oauth/consent")
@oauth_mcp_router.post("/mcp/oauth/consent")
async def process_consent(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    session: str = Form(...),
    action: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Process OAuth consent and login."""
    logger.info("OAuth login attempt", extra={"phone_prefix": phone[:4] + "****" if len(phone) > 4 else "****"})
    oauth_session = await oauth_token_store.get_oauth_session(session)
    if not oauth_session:
        logger.warning("OAuth consent - invalid session", extra={"session_prefix": session[:8] if session else None})
        raise HTTPException(status_code=400, detail="Invalid or expired session")

    try:
        supabase = get_supabase_auth_client()

        auth_data = await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_in_with_password({
                "phone": phone,
                "password": password,
            })
        )

        if not auth_data.session or not auth_data.session.access_token:
            logger.warning("OAuth login failed - Supabase auth failed", extra={"phone_prefix": phone[:4] + "****" if len(phone) > 4 else "****"})
            user_exists = await admin_find_user_by_phone(phone)
            error_msg = "Invalid phone or password" if user_exists else "User not found"

            return HTMLResponse(
                f"""
                <!DOCTYPE html>
                <html>
                <body>
                    <div class="container">
                        <div class="error">Authentication failed: {error_msg}</div>
                        <a href="/mcp/oauth/consent?session={session}">Try again</a>
                    </div>
                </body>
                </html>
            """
            )

        supabase_user_data = await verify_supabase_token(auth_data.session.access_token)
        if not supabase_user_data:
            logger.warning("OAuth login failed - token verification failed")
            raise HTTPException(status_code=401, detail="Authentication failed")

        logger.info("OAuth login - Supabase auth successful", extra={"supabase_id": supabase_user_data.get("sub")})
        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)

        auth_code = generate_auth_code()

        await oauth_token_store.store_auth_code(
            code=auth_code,
            user_id=str(db_user.id),
            client_id=oauth_session["client_id"],
            redirect_uri=oauth_session["redirect_uri"],
            scope=oauth_session["scope"],
            code_challenge=oauth_session["code_challenge"],
            code_challenge_method=oauth_session["code_challenge_method"],
            resource=oauth_session.get("resource"),
            expires_in=OAUTH_AUTHORIZATION_CODE_LIFETIME,
        )

        await oauth_token_store.delete_session(session)

        logger.info("OAuth auth code generated", extra={
            "user_id": db_user.id,
            "client_id": oauth_session["client_id"],
            "has_resource": bool(oauth_session.get("resource")),
        })

        base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
        redirect_uri = oauth_session.get("redirect_uri", f"{base_url}/mcp/oauth/callback")

        is_chatgpt_redirect = redirect_uri in CHATGPT_REDIRECT_URIS

        params = {"code": auth_code}
        if not is_chatgpt_redirect:
            params["iss"] = f"{base_url}/mcp/oauth"
        if oauth_session.get("state"):
            params["state"] = oauth_session["state"]

        redirect_url = f"{redirect_uri}?{urlencode(params)}"

        return RedirectResponse(url=redirect_url, status_code=303)

    except Exception as exc:
        logger.error("OAuth consent error: %s", exc)
        return HTMLResponse(
            f"""
            <!DOCTYPE html>
            <html>
            <body>
                <div class="container">
                    <div class="error">Authentication failed: {str(exc)}</div>
                    <a href="/mcp/oauth/consent?session={session}">Try again</a>
                </div>
            </body>
            </html>
        """
        )


@router.post("/mcp/oauth/token")
@oauth_mcp_router.post("/mcp/oauth/token")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    resource: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """OAuth 2.1 Token Endpoint."""
    logger.info("OAuth token request", extra={"grant_type": grant_type, "client_id": client_id})
    try:
        if grant_type == "authorization_code":
            if not code:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_request",
                        "error_description": "Missing authorization code",
                    },
                )

            auth_data = await oauth_token_store.get_auth_code(code)
            if not auth_data:
                logger.warning("OAuth token - invalid auth code")
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_grant",
                        "error_description": "Invalid or expired authorization code",
                    },
                )

            logger.debug("OAuth token - auth code valid", extra={"user_id": auth_data.get("user_id")})

            if auth_data.get("code_challenge"):
                pkce_valid = verify_pkce(
                    auth_data["code_challenge"],
                    code_verifier,
                    auth_data.get("code_challenge_method"),
                )
                logger.debug("OAuth token - PKCE verification", extra={"result": "success" if pkce_valid else "failed"})
                if not pkce_valid:
                    logger.warning("OAuth token - PKCE verification failed")
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_grant",
                            "error_description": "Invalid PKCE verifier",
                        },
                    )

            if client_id and client_id != auth_data["client_id"]:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_client",
                        "error_description": "Invalid client_id",
                    },
                )

            stored_redirect_uri = auth_data.get("redirect_uri")
            if stored_redirect_uri:
                if not redirect_uri:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_request",
                            "error_description": "Missing redirect_uri",
                        },
                    )
                if redirect_uri != stored_redirect_uri:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_grant",
                            "error_description": "redirect_uri mismatch",
                        },
                    )

            if resource and auth_data.get("resource"):
                if resource != auth_data["resource"]:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_target",
                            "error_description": "Resource mismatch",
                        },
                    )

            access_token = generate_access_token()
            refresh_tok = generate_refresh_token()

            # Delete auth code to prevent replay attacks (single-use code)
            await oauth_token_store.delete_auth_code(code)

            await oauth_token_store.store_oauth_tokens(
                access_token=access_token,
                refresh_token=refresh_tok,
                user_id=auth_data["user_id"],
                scope=auth_data["scope"],
                resource=auth_data.get("resource"),
                access_token_expires_in=OAUTH_ACCESS_TOKEN_LIFETIME,
                refresh_token_expires_in=OAUTH_REFRESH_TOKEN_LIFETIME,
            )

            logger.info("OAuth tokens issued", extra={
                "user_id": auth_data["user_id"],
                "grant_type": "authorization_code",
                "scope": auth_data["scope"],
            })

            return {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_TOKEN_LIFETIME,
                "refresh_token": refresh_tok,
                "scope": auth_data["scope"],
            }

        if grant_type == "refresh_token":
            if not refresh_token:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_request",
                        "error_description": "Missing refresh token",
                    },
                )

            refresh_data = await oauth_token_store.get_refresh_token(refresh_token)
            if not refresh_data:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_grant",
                        "error_description": "Invalid or expired refresh token",
                    },
                )

            new_access_token = generate_access_token()

            await oauth_token_store.store_oauth_tokens(
                access_token=new_access_token,
                refresh_token=refresh_token,
                user_id=refresh_data["user_id"],
                scope=refresh_data["scope"],
                resource=refresh_data.get("resource"),
                access_token_expires_in=OAUTH_ACCESS_TOKEN_LIFETIME,
                refresh_token_expires_in=OAUTH_REFRESH_TOKEN_LIFETIME,
            )

            return {
                "access_token": new_access_token,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_TOKEN_LIFETIME,
                "scope": refresh_data["scope"],
            }

        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_grant_type",
                "error_description": "Unsupported grant type",
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("OAuth token error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "server_error",
                "error_description": "Internal server error",
            },
        )


# =============================================================================
# OAuth Discovery Endpoints
# =============================================================================


@oauth_wellknown_router.get("/.well-known/oauth-protected-resource/mcp")
@oauth_wellknown_router.get("/.well-known/oauth-protected-resource")
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


@oauth_wellknown_router.get("/.well-known/oauth-protected-resource/sse")
async def protected_resource_metadata_sse(request: Request):
    """Protected resource metadata for the /sse endpoint."""
    base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")

    return {
        "resource": f"{base_url}/sse",
        "authorization_servers": [f"{base_url}/mcp/oauth"],
        "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base_url}{settings.API_V1_STR}/docs",
    }


@oauth_wellknown_router.get("/.well-known/oauth-protected-resource/mcp-admin")
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


@oauth_wellknown_router.get("/.well-known/oauth-authorization-server/mcp/oauth")
async def authorization_server_metadata(request: Request):
    """OAuth 2.1 Authorization Server Metadata for the MCP OAuth issuer."""
    logger.info("OAuth AS metadata requested", extra={"path": str(request.url.path)})
    base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    issuer = f"{base_url}/mcp/oauth"

    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
        "service_documentation": f"{base_url}{settings.API_V1_STR}/docs",
        "ui_locales_supported": ["en"],
        "op_policy_uri": f"{base_url}/privacy",
        "op_tos_uri": f"{base_url}/terms",
    }


@oauth_wellknown_router.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request):
    """OpenID Connect discovery endpoint (alias for OAuth AS metadata)."""
    return await authorization_server_metadata(request)


@oauth_wellknown_router.get("/.well-known/openid-configuration/mcp/oauth")
async def openid_configuration_alt(request: Request):
    """OpenID Connect discovery at alternative path format."""
    return await authorization_server_metadata(request)


@oauth_mcp_router.get("/mcp/oauth/.well-known/openid-configuration")
async def openid_configuration_issuer(request: Request):
    """OpenID Connect discovery at issuer-appended path."""
    return await authorization_server_metadata(request)


@router.get("/mcp/oauth/callback")
@oauth_mcp_router.get("/mcp/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str,
    state: Optional[str] = None,
    iss: Optional[str] = None,
):
    """Handle OAuth callback for MCP clients."""
    return JSONResponse(
        {
            "status": "success",
            "message": "Authorization complete. You can close this window.",
            "code_received": True,
        }
    )
