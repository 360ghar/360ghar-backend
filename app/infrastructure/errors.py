"""Exception handler registration and the one error envelope.

Every non-2xx JSON response has this shape::

    {"error": {"code": str, "message": str, "details": object}}

``details`` is omitted when empty. Validation errors (422) carry
``details.fields`` as ``[{"field": "body.price", "msg": ..., "type": ...}]``.
Build every error body with ``error_body`` or ``error_response``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.core.db_resilience import is_retryable_read_db_error, read_db_error_code
from app.core.exceptions import ExternalServiceError, ServiceUnavailableException
from app.core.logging import get_logger

logger = get_logger(__name__)

ERROR_CODE_BY_STATUS = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

VALIDATION_MESSAGE = "Request validation failed"
INTERNAL_MESSAGE = "An unexpected error occurred"

# 5xx responses whose message is fixed text from this codebase, so the message is shown.
# Any other 5xx shows the status phrase, so dependency error text never reaches the client.
CURATED_5XX_TYPES = (ServiceUnavailableException, ExternalServiceError)
# Dict details from the auth dependency (raised as HTTPException, not a typed exception).
CURATED_5XX_CODES = frozenset({"AUTH_PROVIDER_UNREACHABLE", "AUTH_DB_UNAVAILABLE"})


class ErrorBody(BaseModel):
    """The ``error`` object of every non-2xx body."""

    code: str = Field(description="Stable machine-readable code, for example NOT_FOUND.")
    message: str = Field(description="Human-readable message.")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Extra data for the error. Absent when empty."
    )


class ErrorEnvelope(BaseModel):
    """Body of every non-2xx JSON response."""

    error: ErrorBody


class ValidationFieldError(BaseModel):
    field: str = Field(description='Source and path, for example "body.price" or "query.limit".')
    msg: str
    type: str = Field(description="Validation error type, for example greater_than.")


class ValidationErrorDetails(BaseModel):
    fields: list[ValidationFieldError]


class ValidationErrorBody(BaseModel):
    code: str = Field(description="VALIDATION_ERROR, or a 422 code such as INVALID_CURSOR.")
    message: str
    details: ValidationErrorDetails


class ValidationErrorEnvelope(BaseModel):
    """Body of every 422 response. ``details.fields`` is always present (it can be empty)."""

    error: ValidationErrorBody


class OAuthErrorResponse(BaseModel):
    """RFC 6749 error body. The OAuth routes can return it instead of the envelope."""

    error: str
    error_description: str | None = None


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the error envelope as a dict."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Return the error envelope as a JSON response."""
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, details),
        headers=dict(headers) if headers else None,
    )


def validation_details(errors: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Map pydantic or FastAPI error dicts to ``details.fields``."""
    fields = [
        {
            "field": ".".join(str(part) for part in err.get("loc", ())) or "body",
            "msg": str(err.get("msg", "")),
            "type": str(err.get("type", "")),
        }
        for err in errors
    ]
    return {"fields": fields}


def validation_response(errors: Sequence[Mapping[str, Any]]) -> JSONResponse:
    return error_response(
        422,
        "VALIDATION_ERROR",
        VALIDATION_MESSAGE,
        details=validation_details(errors),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register API and MCP exception handlers."""

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc: StarletteHTTPException):
        """MCP routes keep the RFC 6750 body and WWW-Authenticate; all other routes use the envelope."""
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
        return _http_error_response(request, exc)

    @app.exception_handler(403)
    async def forbidden_handler(request: Request, exc: StarletteHTTPException):
        """MCP routes keep the RFC 6750 body and WWW-Authenticate; all other routes use the envelope."""
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
        return _http_error_response(request, exc)

    # Starlette's class handler covers FastAPI's HTTPException, BaseAPIException and the
    # router's own 404 and 405 responses.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return _http_error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        return validation_response(exc.errors())

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """A pydantic ValidationError here is a server fault (a response or internal model
        failed), so it is a 500. Client input errors arrive as RequestValidationError or
        ValidationException. Other ValueErrors get a fixed 422 message."""
        if isinstance(exc, ValidationError):
            return await general_exception_handler(request, exc)
        logger.warning("Validation error: %s - %s %s", exc, request.method, request.url.path)
        return error_response(
            422, "VALIDATION_ERROR", "Invalid request", details={"fields": []}
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Hide exception text on 500s. Transient DB or pooler failures become 503 so clients retry.

        Transient DB / pooler failures (ECHECKOUTTIMEOUT, EDBHANDLEREXITED,
        statement timeouts) are mapped to 503 so clients retry instead of
        treating them as application bugs. That also avoids retry storms from
        hard-failing 500 responses during pool saturation.
        """
        if is_retryable_read_db_error(exc):
            error_code = read_db_error_code(exc)
            logger.error(
                "Transient DB failure: %s - %s %s",
                exc,
                request.method,
                request.url.path,
                exc_info=True,
                extra={
                    "endpoint": str(request.url.path),
                    "error_code": error_code,
                },
            )
            # Capture for capacity visibility. Test runs have SENTRY_DSN blanked
            # so this does not flood the project from intentional fixture errors.
            sentry_sdk.capture_exception(exc)
            return error_response(
                503,
                "SERVICE_UNAVAILABLE",
                "Service temporarily unavailable. Please retry.",
                details={"error_code": error_code, "endpoint": str(request.url.path)},
                headers={"Retry-After": "5"},
            )

        code = "INTERNAL_ERROR"
        if type(exc).__name__ == "DetachedInstanceError":
            code = "DETACHED_ORM_INSTANCE"
            logger.error(
                "Detached ORM instance: %s - %s %s",
                exc,
                request.method,
                request.url.path,
                exc_info=True,
                extra={"endpoint": str(request.url.path), "error_code": code},
            )
        else:
            logger.error(
                "Unexpected error: %s - %s %s", exc, request.method, request.url.path, exc_info=True
            )
        sentry_sdk.capture_exception(exc)
        return error_response(500, code, INTERNAL_MESSAGE)


def _http_error_response(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Build the envelope for any HTTP exception, forwarding its headers (Retry-After, WWW-Authenticate)."""
    detail = exc.detail
    if is_oauth_route(str(request.url.path)) and isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers)

    code = getattr(exc, "error_code", None) or ERROR_CODE_BY_STATUS.get(
        exc.status_code, f"HTTP_{exc.status_code}"
    )
    default_message = _default_message(exc.status_code)
    details: dict[str, Any] = dict(getattr(exc, "details", None) or {})
    if isinstance(detail, dict):
        code = str(detail.get("code", code))
        message = str(detail.get("message") or default_message)
        details.update({k: v for k, v in detail.items() if k not in ("code", "message")})
    else:
        message = str(detail) if detail else default_message
    if exc.status_code == 422:
        # Every 422 has the ValidationErrorEnvelope shape, so clients read details.fields.
        details.setdefault("fields", [])
    curated = isinstance(exc, CURATED_5XX_TYPES) or code in CURATED_5XX_CODES
    if exc.status_code >= 500 and not curated:
        message = default_message
    return error_response(
        exc.status_code,
        code,
        message,
        details=details or None,
        headers=exc.headers,
    )


def _default_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return f"HTTP {status_code} error"


def _is_mcp_tool_route(path: str) -> bool:
    return (path.startswith("/mcp") and not path.startswith("/mcp/oauth")) or (
        path.startswith("/mcp-admin") and not path.startswith("/mcp-admin/oauth")
    )


def is_oauth_route(path: str) -> bool:
    return (
        path.startswith("/mcp/oauth")
        or path.startswith("/api/v1/mcp/oauth")
        or path.startswith("/.well-known/oauth-")
        or path.startswith("/.well-known/openid-configuration")
    )
