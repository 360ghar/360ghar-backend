"""Application exception handler registration."""

from __future__ import annotations

from typing import Any

import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.exceptions import BaseAPIException
from app.core.logging import get_logger

logger = get_logger(__name__)

ERROR_CODE_BY_STATUS = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Register API and MCP exception handlers."""

    @app.exception_handler(401)
    async def mcp_unauthorized_handler(request, exc):
        """Add WWW-Authenticate header for MCP 401 responses."""
        path = str(request.url.path)
        if _is_mcp_tool_route(path):
            base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
            if path.startswith("/mcp-admin"):
                resource_metadata = f"{base_url}/.well-known/oauth-protected-resource/mcp-admin"
            else:
                resource_metadata = f"{base_url}/.well-known/oauth-protected-resource/mcp"
            headers = {
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{resource_metadata}", scope="mcp:read mcp:write"'
                )
            }
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "error_description": "Authentication required"},
                headers=headers,
            )
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": str(exc.detail) if hasattr(exc, "detail") else "Unauthorized",
                }
            },
        )

    @app.exception_handler(403)
    async def mcp_forbidden_handler(request, exc):
        """Add WWW-Authenticate header for MCP 403 responses."""
        path = str(request.url.path)
        if _is_mcp_tool_route(path):
            headers = {
                "WWW-Authenticate": (
                    'Bearer error="insufficient_scope", scope="mcp:read mcp:write"'
                )
            }
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "error_description": "Insufficient scope"},
                headers=headers,
            )
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "FORBIDDEN",
                    "message": str(exc.detail) if hasattr(exc, "detail") else "Forbidden",
                }
            },
        )

    @app.exception_handler(BaseAPIException)
    async def base_api_exception_handler(request, exc: BaseAPIException):
        """Handle custom API exceptions with standardized error format."""
        content: dict[str, Any] = {
            "error": {
                "code": exc.error_code,
                "message": exc.detail,
            }
        }
        if exc.details:
            content["error"]["details"] = exc.details

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        """Handle FastAPI HTTPExceptions with standardized error format."""
        path = str(request.url.path)
        detail = exc.detail

        if _is_oauth_route(path) and isinstance(detail, dict) and "error" in detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=detail,
                headers=exc.headers,
            )
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": detail},
            )

        error_code = ERROR_CODE_BY_STATUS.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = str(detail) if detail else f"HTTP {exc.status_code} error"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": error_code,
                    "message": message,
                }
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request, exc: ValueError):
        """Handle validation errors with standardized error format."""
        logger.warning("Validation error: %s - %s %s", exc, request.method, request.url.path)
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(exc),
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc: Exception):
        """Handle unexpected exceptions and hide details unless DEBUG is on."""
        logger.error(
            "Unexpected error: %s - %s %s", exc, request.method, request.url.path, exc_info=True
        )
        sentry_sdk.capture_exception(exc)

        # Only leak the exception string in DEBUG mode (development). In every
        # other environment clients get a generic message; full details remain
        # in the server logs above.
        message = str(exc) if settings.DEBUG else "An unexpected error occurred"

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": message,
                }
            },
        )


def _is_mcp_tool_route(path: str) -> bool:
    return (
        (path.startswith("/mcp") and not path.startswith("/mcp/oauth"))
        or (path.startswith("/mcp-admin") and not path.startswith("/mcp-admin/oauth"))
    )


def _is_oauth_route(path: str) -> bool:
    return (
        path.startswith("/mcp/oauth")
        or path.startswith("/api/v1/mcp/oauth")
        or path.startswith("/.well-known/oauth-")
        or path.startswith("/.well-known/openid-configuration")
    )
