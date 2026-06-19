from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from app.core.logging import get_logger
from app.services.oauth_token_store import oauth_token_store

logger = get_logger(__name__)

registration_router = APIRouter()


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 Dynamic Client Registration Request."""

    client_name: str
    redirect_uris: list[str]
    client_uri: str | None = None
    logo_uri: str | None = None
    contacts: list[str] | None = None
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    token_endpoint_auth_method: str | None = None
    scope: str | None = None

    @field_validator("redirect_uris")
    @classmethod
    def validate_redirect_uris(cls, v: list[str]) -> list[str]:
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

    @field_validator("client_uri", "logo_uri", "scope")
    @classmethod
    def normalize_empty_optional_strings(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        return v

    @field_validator("contacts", "grant_types", "response_types")
    @classmethod
    def normalize_empty_optional_lists(cls, v: list[str] | None) -> list[str] | None:
        if v is None or v == []:
            return None
        return v


@registration_router.post("/mcp/oauth/register", summary="Register OAuth client")
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
            "client_uri": registration.client_uri or "",
            "logo_uri": registration.logo_uri or "",
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
        ) from None
