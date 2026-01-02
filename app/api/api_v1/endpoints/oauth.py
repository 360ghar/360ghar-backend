from __future__ import annotations

import secrets
import time
import anyio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, status, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, HttpUrl
import httpx
import base64
import hashlib
import string

from app.core.database import get_db
from app.core.auth import get_supabase_auth_client, admin_find_user_by_phone, verify_supabase_token
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.user import UserLogin, User as UserSchema
from app.services.user import get_or_create_user_from_supabase
from app.services.oauth_token_store import oauth_token_store

logger = get_logger(__name__)
router = APIRouter()

# OAuth configuration
OAUTH_AUTHORIZATION_CODE_LIFETIME = 600  # 10 minutes
OAUTH_ACCESS_TOKEN_LIFETIME = 3600  # 1 hour
OAUTH_REFRESH_TOKEN_LIFETIME = 86400 * 30  # 30 days

class OAuthAuthorizeRequest(BaseModel):
    response_type: str
    client_id: str
    redirect_uri: Optional[HttpUrl] = None
    scope: Optional[str] = None
    state: Optional[str] = None
    code_challenge: Optional[str] = None  # PKCE
    code_challenge_method: Optional[str] = None  # PKCE

class OAuthTokenRequest(BaseModel):
    grant_type: str
    code: Optional[str] = None
    redirect_uri: Optional[HttpUrl] = None
    client_id: Optional[str] = None
    refresh_token: Optional[str] = None
    code_verifier: Optional[str] = None  # PKCE

def generate_auth_code() -> str:
    """Generate a secure authorization code"""
    return secrets.token_urlsafe(32)

def generate_access_token() -> str:
    """Generate a secure access token"""
    return secrets.token_urlsafe(32)

def generate_refresh_token() -> str:
    """Generate a secure refresh token"""
    return secrets.token_urlsafe(32)

def verify_pkce(code_challenge: Optional[str], code_verifier: Optional[str], method: Optional[str]) -> bool:
    """Verify PKCE code challenge"""
    if not code_challenge or not code_verifier:
        return False
    
    if method == "S256":
        # SHA256 method
        hash_obj = hashlib.sha256(code_verifier.encode('ascii')).digest()
        encoded = base64.urlsafe_b64encode(hash_obj).decode('ascii').rstrip('=')
        return secrets.compare_digest(encoded, code_challenge)
    elif method == "plain":
        # Plain method (less secure)
        return secrets.compare_digest(code_verifier, code_challenge)
    
    return False

@router.get("/mcp/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: Optional[str] = None,
    scope: Optional[str] = None,
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """OAuth 2.1 Authorization Endpoint"""
    
    # Validate required parameters
    if response_type != "code":
        raise HTTPException(
            status_code=400,
            detail={"error": "unsupported_response_type", "error_description": "Only authorization code flow is supported"}
        )
    
    if client_id != "ghar360-mcp" and not client_id.startswith("mcp-client-"):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_client", "error_description": "Invalid client_id"}
        )
    
    # Generate session ID for this authorization flow
    session_id = secrets.token_urlsafe(16)
    
    # Store authorization request
    await oauth_token_store.store_oauth_session(
        session_id=session_id,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope or "mcp:read mcp:write",
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_in=1800  # 30 minutes
    )
    
    # Build consent/login page URL
    login_url = f"{request.base_url}mcp/oauth/consent?session={session_id}"
    
    # Redirect to login/consent page
    return RedirectResponse(url=login_url)

@router.get("/mcp/oauth/consent", response_class=HTMLResponse)
async def consent_page(
    request: Request,
    session: str,
    db: AsyncSession = Depends(get_db)
):
    """OAuth consent and login page"""
    
    # Validate session
    oauth_session = await oauth_token_store.get_oauth_session(session)
    if not oauth_session:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired session"
        )
    
    # Generate HTML for consent/login page
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
async def process_consent(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    session: str = Form(...),
    action: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Process OAuth consent and login"""
    
    # Validate session
    oauth_session = await oauth_token_store.get_oauth_session(session)
    if not oauth_session:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired session"
        )
    
    try:
        # Authenticate with Supabase
        supabase = get_supabase_auth_client()
        
        # Try to sign in with phone/password
        auth_data = await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_in_with_password({
                "phone": phone,
                "password": password
            })
        )
        
        if not auth_data.session or not auth_data.session.access_token:
            # Check if user exists
            user_exists = await admin_find_user_by_phone(phone)
            error_msg = "Invalid phone or password" if user_exists else "User not found"
            
            return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <body>
                    <div class="container">
                        <div class="error">Authentication failed: {error_msg}</div>
                        <a href="/mcp/oauth/consent?session={session}">Try again</a>
                    </div>
                </body>
                </html>
            """)
        
        # Verify the token and get user
        supabase_user_data = await verify_supabase_token(auth_data.session.access_token)
        if not supabase_user_data:
            raise HTTPException(status_code=401, detail="Authentication failed")
        
        # Get or create user in database
        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
        
        # Generate authorization code
        auth_code = generate_auth_code()
        
        # Store authorization code
        await oauth_token_store.store_auth_code(
            code=auth_code,
            user_id=str(db_user.id),
            client_id=oauth_session["client_id"],
            redirect_uri=oauth_session["redirect_uri"],
            scope=oauth_session["scope"],
            code_challenge=oauth_session["code_challenge"],
            code_challenge_method=oauth_session["code_challenge_method"],
            expires_in=OAUTH_AUTHORIZATION_CODE_LIFETIME
        )
        
        # Clean up session
        await oauth_token_store.delete_session(session)
        
        # Build redirect URL with authorization code
        redirect_uri = oauth_session.get("redirect_uri", f"{request.base_url}mcp/oauth/callback")
        base_url = str(request.base_url).rstrip("/")
        issuer = f"{base_url}/mcp/oauth"
        params = {"code": auth_code, "iss": issuer}
        
        if oauth_session.get("state"):
            params["state"] = oauth_session["state"]
        
        redirect_url = f"{redirect_uri}?{urlencode(params)}"
        
        # Use 303 so the redirect switches to GET (OAuth callback expects GET).
        return RedirectResponse(url=redirect_url, status_code=303)
        
    except Exception as e:
        logger.error(f"OAuth consent error: {e}")
        return HTMLResponse(f"""
            <!DOCTYPE html>
            <html>
            <body>
                <div class="container">
                    <div class="error">Authentication failed: {str(e)}</div>
                    <a href="/mcp/oauth/consent?session={session}">Try again</a>
                </div>
            </body>
            </html>
        """)

@router.post("/mcp/oauth/token")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """OAuth 2.1 Token Endpoint"""
    
    try:
        if grant_type == "authorization_code":
            # Authorization Code Grant
            if not code:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "invalid_request", "error_description": "Missing authorization code"}
                )
            
            # Validate authorization code
            auth_data = await oauth_token_store.get_auth_code(code)
            if not auth_data:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "invalid_grant", "error_description": "Invalid or expired authorization code"}
                )
            
            # Verify PKCE if present
            if auth_data.get("code_challenge"):
                if not verify_pkce(
                    auth_data["code_challenge"],
                    code_verifier,
                    auth_data.get("code_challenge_method")
                ):
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "invalid_grant", "error_description": "Invalid PKCE verifier"}
                    )
            
            # Verify client_id
            if client_id and client_id != auth_data["client_id"]:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "invalid_client", "error_description": "Invalid client_id"}
                )
            
            # Generate tokens
            access_token = generate_access_token()
            refresh_tok = generate_refresh_token()
            
            # Store OAuth tokens
            await oauth_token_store.store_oauth_tokens(
                access_token=access_token,
                refresh_token=refresh_tok,
                user_id=auth_data["user_id"],
                scope=auth_data["scope"],
                access_token_expires_in=OAUTH_ACCESS_TOKEN_LIFETIME,
                refresh_token_expires_in=OAUTH_REFRESH_TOKEN_LIFETIME
            )
            
            return {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_TOKEN_LIFETIME,
                "refresh_token": refresh_tok,
                "scope": auth_data["scope"]
            }
            
        elif grant_type == "refresh_token":
            # Refresh Token Grant
            if not refresh_token:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "invalid_request", "error_description": "Missing refresh token"}
                )
            
            # Validate refresh token
            refresh_data = await oauth_token_store.get_refresh_token(refresh_token)
            if not refresh_data:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "invalid_grant", "error_description": "Invalid or expired refresh token"}
                )
            
            # Generate new access token
            new_access_token = generate_access_token()
            
            # Store new access token linked to the same user
            await oauth_token_store.store_oauth_tokens(
                access_token=new_access_token,
                refresh_token=refresh_token,  # Keep same refresh token
                user_id=refresh_data["user_id"],
                scope=refresh_data["scope"],
                access_token_expires_in=OAUTH_ACCESS_TOKEN_LIFETIME,
                refresh_token_expires_in=OAUTH_REFRESH_TOKEN_LIFETIME
            )
            
            return {
                "access_token": new_access_token,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_TOKEN_LIFETIME,
                "scope": refresh_data["scope"]
            }
            
        else:
            raise HTTPException(
                status_code=400,
                detail={"error": "unsupported_grant_type", "error_description": "Unsupported grant type"}
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth token error: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": "server_error", "error_description": "Internal server error"}
        )


# ============================================================================
# RFC 7591 Dynamic Client Registration
# ============================================================================

# In-memory store for dynamically registered clients (use Redis/DB in production)
_registered_clients: Dict[str, Dict[str, Any]] = {
    # Pre-registered default client
    "ghar360-mcp": {
        "client_id": "ghar360-mcp",
        "client_name": "360Ghar MCP Client",
        "redirect_uris": [],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "mcp:read mcp:write",
    }
}


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 Client Registration Request"""
    client_name: Optional[str] = None
    redirect_uris: Optional[list[str]] = None
    grant_types: Optional[list[str]] = None
    response_types: Optional[list[str]] = None
    token_endpoint_auth_method: Optional[str] = None
    scope: Optional[str] = None
    contacts: Optional[list[str]] = None
    logo_uri: Optional[str] = None
    client_uri: Optional[str] = None
    policy_uri: Optional[str] = None
    tos_uri: Optional[str] = None


@router.post("/mcp/oauth/register")
async def register_client(
    request: Request,
    registration: ClientRegistrationRequest = None
):
    """
    RFC 7591 Dynamic Client Registration Endpoint.
    
    This allows MCP clients (like ChatGPT) to dynamically register
    and obtain client credentials.
    """
    try:
        # Parse body if not already parsed by Pydantic
        if registration is None:
            body = await request.json()
            registration = ClientRegistrationRequest(**body)
    except Exception:
        # If no body or invalid body, use defaults
        registration = ClientRegistrationRequest()
    
    # Generate a unique client_id
    client_id = f"mcp-client-{secrets.token_hex(8)}"
    
    # For public clients (MCP), we don't issue a client_secret
    # as they use PKCE for security
    
    # Build client metadata
    client_metadata = {
        "client_id": client_id,
        "client_name": registration.client_name or f"MCP Client {client_id[-8:]}",
        "redirect_uris": registration.redirect_uris or [],
        "grant_types": registration.grant_types or ["authorization_code", "refresh_token"],
        "response_types": registration.response_types or ["code"],
        "token_endpoint_auth_method": registration.token_endpoint_auth_method or "none",
        "scope": registration.scope or "mcp:read mcp:write",
        "client_id_issued_at": int(time.time()),
    }
    
    # Store the registered client
    _registered_clients[client_id] = client_metadata
    
    logger.info(f"Registered new MCP client: {client_id}")
    
    # Return client registration response (RFC 7591)
    return JSONResponse(
        status_code=201,
        content=client_metadata
    )


@router.get("/mcp/oauth/register/{client_id}")
async def get_client_registration(client_id: str):
    """Get client registration details (RFC 7592)"""
    if client_id not in _registered_clients:
        raise HTTPException(
            status_code=404,
            detail={"error": "invalid_client", "error_description": "Client not found"}
        )
    return _registered_clients[client_id]

def _build_oauth_metadata(base_url: str, issuer_path: str) -> Dict[str, Any]:
    issuer_path = issuer_path.rstrip("/")
    issuer = f"{base_url}{issuer_path}" if issuer_path else base_url
    oauth_base = f"{base_url}/mcp/oauth"
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{oauth_base}/authorize",
        "token_endpoint": f"{oauth_base}/token",
        "registration_endpoint": f"{oauth_base}/register",  # RFC 7591 Dynamic Client Registration
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
        # Public clients (no client secret) – MCP clients authenticate via PKCE
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{base_url}/docs",
        "ui_locales_supported": ["en"],
        "op_policy_uri": f"{base_url}/privacy",
        "op_tos_uri": f"{base_url}/terms",
    }


@router.get("/.well-known/oauth-authorization-server/mcp/oauth")
async def authorization_server_metadata(request: Request):
    """OAuth 2.1 Authorization Server Metadata for the MCP OAuth issuer.

    This endpoint is discovered by MCP clients based on the issuer URL
    advertised in the protected resource metadata for `/mcp`. The issuer
    URL is path-aware as per RFC 8414 and matches:
        {scheme}://{host}/mcp/oauth
    """
    base_url = str(request.base_url).rstrip("/")
    return _build_oauth_metadata(base_url, "/mcp/oauth")


# Compatibility endpoints for clients that probe alternate well-known paths.
@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
@router.get("/mcp/.well-known/oauth-authorization-server")
async def authorization_server_metadata_compat(request: Request):
    base_url = str(request.base_url).rstrip("/")
    path = request.url.path
    if path.endswith("/mcp"):
        issuer_path = "/mcp"
    else:
        issuer_path = ""
    return _build_oauth_metadata(base_url, issuer_path)


@router.get("/.well-known/openid-configuration")
@router.get("/.well-known/openid-configuration/mcp")
@router.get("/mcp/.well-known/openid-configuration")
async def openid_configuration_compat(request: Request):
    base_url = str(request.base_url).rstrip("/")
    path = request.url.path
    if path.endswith("/mcp"):
        issuer_path = "/mcp"
    else:
        issuer_path = ""
    return _build_oauth_metadata(base_url, issuer_path)


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource_metadata(request: Request):
    base_url = str(request.base_url).rstrip("/")
    return {
        "resource": f"{base_url}/mcp",
        "authorization_servers": [f"{base_url}/mcp/oauth"],
        "scopes_supported": ["mcp:read", "mcp:write"],
        "resource_name": "360Ghar MCP API",
        "resource_documentation": f"{base_url}/docs",
        "bearer_methods_supported": ["header"],
    }

