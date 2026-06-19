from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.services.oauth_token_store import oauth_token_store

from .helpers import (
    OAUTH_ACCESS_TOKEN_LIFETIME,
    OAUTH_REFRESH_TOKEN_LIFETIME,
    generate_access_token,
    generate_refresh_token,
    validate_client,
)
from .pkce import verify_pkce

logger = get_logger(__name__)

token_router = APIRouter()


@token_router.post("/mcp/oauth/token", summary="OAuth token endpoint")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    client_id: str | None = Form(None),
    refresh_token: str | None = Form(None),
    code_verifier: str | None = Form(None),
    resource: str | None = Form(None),
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

            if not client_id:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_request",
                        "error_description": "Missing client_id",
                    },
                )

            client = await validate_client(client_id)
            if not client:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_client",
                        "error_description": "Invalid client_id",
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

            logger.debug(
                "OAuth token - auth code valid", extra={"user_id": auth_data.get("user_id")}
            )

            if auth_data.get("code_challenge"):
                pkce_valid = verify_pkce(
                    auth_data["code_challenge"],
                    code_verifier,
                    auth_data.get("code_challenge_method"),
                )
                logger.debug(
                    "OAuth token - PKCE verification",
                    extra={"result": "success" if pkce_valid else "failed"},
                )
                if not pkce_valid:
                    logger.warning("OAuth token - PKCE verification failed")
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_grant",
                            "error_description": "Invalid PKCE verifier",
                        },
                    )

            if client_id != auth_data["client_id"]:
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

            await oauth_token_store.store_oauth_tokens(
                access_token=access_token,
                refresh_token=refresh_tok,
                user_id=auth_data["user_id"],
                scope=auth_data["scope"],
                client_id=auth_data["client_id"],
                resource=auth_data.get("resource"),
                access_token_expires_in=OAUTH_ACCESS_TOKEN_LIFETIME,
                refresh_token_expires_in=OAUTH_REFRESH_TOKEN_LIFETIME,
            )

            logger.info(
                "OAuth tokens issued",
                extra={
                    "user_id": auth_data["user_id"],
                    "grant_type": "authorization_code",
                    "scope": auth_data["scope"],
                },
            )

            response = {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_TOKEN_LIFETIME,
                "refresh_token": refresh_tok,
                "scope": auth_data["scope"],
            }
            # Echo resource per RFC 8707 for audience binding
            if auth_data.get("resource"):
                response["resource"] = auth_data["resource"]
            return response

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

            token_client_id = refresh_data.get("client_id")
            if token_client_id:
                if not client_id:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_request",
                            "error_description": "Missing client_id",
                        },
                    )
                if client_id != token_client_id:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_client",
                            "error_description": "Invalid client_id",
                        },
                    )
                client = await validate_client(client_id)
                if not client:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_client",
                            "error_description": "Invalid client_id",
                        },
                    )

            if resource and refresh_data.get("resource"):
                if resource != refresh_data["resource"]:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "invalid_target",
                            "error_description": "Resource mismatch",
                        },
                    )

            new_access_token = generate_access_token()
            new_refresh_token = generate_refresh_token()

            await oauth_token_store.store_oauth_tokens(
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                user_id=refresh_data["user_id"],
                scope=refresh_data["scope"],
                client_id=token_client_id or client_id,
                resource=refresh_data.get("resource"),
                access_token_expires_in=OAUTH_ACCESS_TOKEN_LIFETIME,
                refresh_token_expires_in=OAUTH_REFRESH_TOKEN_LIFETIME,
            )
            await oauth_token_store.revoke_refresh_token(refresh_token)

            response = {
                "access_token": new_access_token,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_TOKEN_LIFETIME,
                "refresh_token": new_refresh_token,
                "scope": refresh_data["scope"],
            }
            # Echo resource per RFC 8707 for audience binding
            if refresh_data.get("resource"):
                response["resource"] = refresh_data["resource"]
            return response

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
        ) from None


@token_router.post("/mcp/oauth/revoke", summary="Revoke OAuth token")
async def revoke_token(
    token: str = Form(...),
    token_type_hint: str | None = Form(None),
    client_id: str | None = Form(None),
):
    """RFC 7009 OAuth token revocation endpoint."""
    try:
        if token_type_hint not in {None, "access_token", "refresh_token"}:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "unsupported_token_type",
                    "error_description": "token_type_hint must be access_token or refresh_token",
                },
            )

        async def _validate_client_binding(token_data: dict[str, Any] | None) -> bool:
            if not token_data:
                return True
            token_client_id = token_data.get("client_id")
            if not token_client_id:
                return True
            return bool(client_id == token_client_id)

        if token_type_hint == "refresh_token":
            refresh_data = await oauth_token_store.get_refresh_token(token)
            if not await _validate_client_binding(refresh_data):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_client",
                        "error_description": "Invalid client_id",
                    },
                )
            if refresh_data:
                await oauth_token_store.revoke_refresh_token(token)
            return JSONResponse(status_code=200, content={})

        if token_type_hint == "access_token":
            access_data = await oauth_token_store.get_access_token(token)
            if not await _validate_client_binding(access_data):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_client",
                        "error_description": "Invalid client_id",
                    },
                )
            if access_data:
                await oauth_token_store.revoke_token_pair(access_token=token)
            return JSONResponse(status_code=200, content={})

        # No hint: try both types, but keep response idempotent and opaque.
        access_data = await oauth_token_store.get_access_token(token)
        if access_data:
            if not await _validate_client_binding(access_data):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_client",
                        "error_description": "Invalid client_id",
                    },
                )
            await oauth_token_store.revoke_token_pair(access_token=token)
            return JSONResponse(status_code=200, content={})

        refresh_data = await oauth_token_store.get_refresh_token(token)
        if refresh_data:
            if not await _validate_client_binding(refresh_data):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "invalid_client",
                        "error_description": "Invalid client_id",
                    },
                )
            await oauth_token_store.revoke_refresh_token(token)

        return JSONResponse(status_code=200, content={})
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("OAuth revoke error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "server_error",
                "error_description": "Internal server error",
            },
        ) from None
