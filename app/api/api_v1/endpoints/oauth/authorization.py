from __future__ import annotations

import secrets
from urllib.parse import urlencode

import anyio
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import admin_find_user_by_phone, get_supabase_auth_client, verify_supabase_token
from app.core.database import get_db
from app.core.logging import get_logger
from app.services.oauth_token_store import oauth_token_store
from app.services.user import get_or_create_user_from_supabase

from .helpers import (
    CHATGPT_REDIRECT_URIS,
    OAUTH_AUTHORIZATION_CODE_LIFETIME,
    generate_auth_code,
    is_redirect_uri_allowed_for_client,
    render_consent_html,
    validate_client,
)

logger = get_logger(__name__)

auth_router = APIRouter()


@auth_router.get("/mcp/oauth/authorize", summary="OAuth authorize")
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str | None = None,
    scope: str | None = None,
    state: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
    resource: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """OAuth 2.1 Authorization Endpoint."""
    logger.info(
        "OAuth authorize request",
        extra={
            "client_id": client_id,
            "response_type": response_type,
            "has_pkce": bool(code_challenge),
            "resource": resource,
            "redirect_uri": redirect_uri,
        },
    )
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

    if not redirect_uri:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "error_description": "redirect_uri is required",
            },
        )
    if not is_redirect_uri_allowed_for_client(client, redirect_uri):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "error_description": "redirect_uri not allowed for this client",
            },
        )

    session_id = secrets.token_urlsafe(16)

    allowed_resources = {
        f"{base_url}/mcp",
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


@auth_router.get("/mcp/oauth/consent", response_class=HTMLResponse, summary="OAuth consent page")
async def consent_page(
    request: Request,
    session: str,
    db: AsyncSession = Depends(get_db),
):
    """OAuth consent and login page."""
    oauth_session = await oauth_token_store.get_oauth_session(session)
    if not oauth_session:
        return HTMLResponse(
            content=render_consent_html(
                session_id=session,
                oauth_session=None,
                error_message="This login session is invalid or expired. Please restart authorization.",
            ),
            status_code=400,
        )

    return HTMLResponse(
        content=render_consent_html(session_id=session, oauth_session=oauth_session)
    )


@auth_router.post("/mcp/oauth/consent", summary="Process OAuth consent")
async def process_consent(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    session: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Process OAuth consent and login."""
    # Auto-prepend +91 if user entered just 10 digits
    phone = phone.strip()
    if phone.isdigit() and len(phone) == 10:
        phone = f"+91{phone}"

    logger.info(
        "OAuth login attempt",
        extra={"phone_prefix": phone[:4] + "****" if len(phone) > 4 else "****"},
    )
    oauth_session = await oauth_token_store.get_oauth_session(session)
    if not oauth_session:
        logger.warning(
            "OAuth consent - invalid session",
            extra={"session_prefix": session[:8] if session else None},
        )
        raise HTTPException(status_code=400, detail="Invalid or expired session")

    try:
        supabase = get_supabase_auth_client()

        auth_data = await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_in_with_password(
                {
                    "phone": phone,
                    "password": password,
                }
            )
        )

        if not auth_data.session or not auth_data.session.access_token:
            logger.warning(
                "OAuth login failed - Supabase auth failed",
                extra={"phone_prefix": phone[:4] + "****" if len(phone) > 4 else "****"},
            )
            user_exists = await admin_find_user_by_phone(phone)
            error_msg = "Invalid phone or password" if user_exists else "User not found"

            return HTMLResponse(
                render_consent_html(
                    session_id=session,
                    oauth_session=oauth_session,
                    error_message=f"Authentication failed: {error_msg}",
                ),
                status_code=401,
            )

        supabase_user_data = await verify_supabase_token(auth_data.session.access_token)
        if not supabase_user_data:
            logger.warning("OAuth login failed - token verification failed")
            raise HTTPException(status_code=401, detail="Authentication failed")

        logger.info(
            "OAuth login - Supabase auth successful",
            extra={"supabase_id": supabase_user_data.get("id")},
        )
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

        logger.info(
            "OAuth auth code generated",
            extra={
                "user_id": db_user.id,
                "client_id": oauth_session["client_id"],
                "has_resource": bool(oauth_session.get("resource")),
            },
        )

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
        logger.warning("OAuth consent error: %s", exc, exc_info=True)
        return HTMLResponse(
            render_consent_html(
                session_id=session,
                oauth_session=oauth_session,
                error_message="Authentication failed",
            ),
            status_code=500,
        )


@auth_router.get("/mcp/oauth/callback", summary="OAuth callback")
async def oauth_callback(
    request: Request,
    code: str,
    state: str | None = None,
    iss: str | None = None,
):
    """Handle OAuth callback for MCP clients."""
    return JSONResponse(
        {
            "status": "success",
            "message": "Authorization complete. You can close this window.",
            "code_received": True,
        }
    )
