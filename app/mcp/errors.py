"""
Error response schemas and utilities for MCP tools.

Provides standardized error handling and response formats for all MCP tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.exceptions import BaseAPIException


class MCPErrorCode(str, Enum):
    """Standard error codes for MCP tools."""

    # Authentication & Authorization
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"

    # Input Validation
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_PARAMETER = "INVALID_PARAMETER"

    # Resource Errors
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    CONFLICT = "CONFLICT"

    # Business Logic Errors
    UNAVAILABLE = "UNAVAILABLE"
    OPERATION_FAILED = "OPERATION_FAILED"
    BOOKING_CONFLICT = "BOOKING_CONFLICT"
    INVALID_DATE_RANGE = "INVALID_DATE_RANGE"

    # System Errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"

    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"


class MCPError(BaseModel):
    """Structured error response for MCP tools."""

    code: MCPErrorCode
    message: str
    details: dict[str, Any] | None = None

    model_config = ConfigDict(use_enum_values=True)


class MCPResponse(BaseModel):
    """Standardized response format for MCP tools."""

    ok: bool
    data: dict[str, Any] | None = None
    error: MCPError | None = None

    @classmethod
    def success(cls, data: dict[str, Any]) -> MCPResponse:
        """Create a success response."""
        return cls(ok=True, data=data, error=None)

    @classmethod
    def failure(
        cls,
        code: MCPErrorCode,
        message: str,
        details: dict[str, Any] | None = None
    ) -> MCPResponse:
        """Create an error response."""
        return cls(
            ok=False,
            data=None,
            error=MCPError(code=code, message=message, details=details)
        )

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:
        """Override model_dump to exclude None values.

        For failure responses, includes a top-level ``message`` key for
        backward compatibility with clients that check ``response["message"]``.
        """
        d = super().model_dump(*args, **kwargs)
        result = {k: v for k, v in d.items() if v is not None}
        if not self.ok and self.error is not None:
            result["message"] = self.error.message
        return result


@dataclass(frozen=True)
class MappedMCPException:
    """Safe error representation derived from an exception."""

    code: MCPErrorCode
    message: str
    details: dict[str, Any] | None = None


_BASE_API_ERROR_CODE_MAP: dict[str, MCPErrorCode] = {
    "UNAUTHORIZED": MCPErrorCode.UNAUTHORIZED,
    "INVALID_TOKEN": MCPErrorCode.INVALID_TOKEN,
    "TOKEN_EXPIRED": MCPErrorCode.TOKEN_EXPIRED,
    "FORBIDDEN": MCPErrorCode.INSUFFICIENT_PERMISSIONS,
    "INSUFFICIENT_PERMISSIONS": MCPErrorCode.INSUFFICIENT_PERMISSIONS,
    "PROPERTY_OWNERSHIP_REQUIRED": MCPErrorCode.INSUFFICIENT_PERMISSIONS,
    "VALIDATION_ERROR": MCPErrorCode.INVALID_INPUT,
    "BAD_REQUEST": MCPErrorCode.INVALID_INPUT,
    "INVALID_CURSOR": MCPErrorCode.INVALID_INPUT,
    "INVALID_FILE": MCPErrorCode.INVALID_INPUT,
    "NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "PROPERTY_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "USER_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "AGENT_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "BOOKING_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "VISIT_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "TOUR_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "SCENE_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "HOTSPOT_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "BLOG_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "CATEGORY_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "TAG_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "LEASE_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "MAINTENANCE_REQUEST_NOT_FOUND": MCPErrorCode.NOT_FOUND,
    "CONFLICT": MCPErrorCode.CONFLICT,
    "BOOKING_CONFLICT": MCPErrorCode.BOOKING_CONFLICT,
    "DUPLICATE_SWIPE": MCPErrorCode.CONFLICT,
    "RATE_LIMIT_EXCEEDED": MCPErrorCode.RATE_LIMIT_EXCEEDED,
    "SERVICE_UNAVAILABLE": MCPErrorCode.UNAVAILABLE,
    "EXTERNAL_SERVICE_ERROR": MCPErrorCode.EXTERNAL_SERVICE_ERROR,
}


def map_mcp_exception(
    exc: Exception,
    *,
    fallback_message: str = "Internal server error",
) -> MappedMCPException:
    """Map an exception to a safe MCP error.

    Raw exception strings are intentionally not exposed for generic exceptions.
    Domain ``BaseAPIException`` details are treated as client-safe because those
    exceptions already back public API responses.
    """
    if isinstance(exc, BaseAPIException):
        code = _BASE_API_ERROR_CODE_MAP.get(exc.error_code, MCPErrorCode.INTERNAL_ERROR)
        message = str(exc.detail or fallback_message)
        return MappedMCPException(
            code=code,
            message=message,
            details=exc.details or None,
        )

    if isinstance(exc, (ValueError, TypeError)):
        return MappedMCPException(
            code=MCPErrorCode.INVALID_INPUT,
            message="Invalid input.",
        )

    return MappedMCPException(
        code=MCPErrorCode.INTERNAL_ERROR,
        message=fallback_message,
    )


def log_mcp_exception(
    exc: Exception,
    *,
    logger: Any,
    tool_name: str,
) -> None:
    """Log the raw exception server-side without shaping client output."""
    logger.error(
        "Unhandled MCP tool exception",
        extra={
            "tool": tool_name,
            "exception_type": exc.__class__.__name__,
            "error": str(exc),
        },
        exc_info=True,
    )


def mcp_exception_response(
    exc: Exception,
    *,
    logger: Any,
    tool_name: str,
    fallback_message: str = "Internal server error",
) -> dict[str, Any]:
    """Log and convert an exception to the standard MCP response envelope."""
    log_mcp_exception(exc, logger=logger, tool_name=tool_name)
    mapped = map_mcp_exception(exc, fallback_message=fallback_message)
    return MCPResponse.failure(
        code=mapped.code,
        message=mapped.message,
        details=mapped.details,
    ).model_dump()


def mcp_exception_payload(
    exc: Exception,
    *,
    logger: Any,
    tool_name: str,
    fallback_message: str = "Internal server error",
) -> dict[str, Any]:
    """Log and convert an exception to a ChatGPT Apps-style error payload."""
    log_mcp_exception(exc, logger=logger, tool_name=tool_name)
    mapped = map_mcp_exception(exc, fallback_message=fallback_message)
    payload: dict[str, Any] = {
        "error": True,
        "code": mapped.code.value,
        "message": mapped.message,
    }
    if mapped.details:
        payload["details"] = mapped.details
    return payload


def invalid_input_response(
    message: str,
    details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Helper to create invalid input response."""
    return MCPResponse.failure(
        code=MCPErrorCode.INVALID_INPUT,
        message=message,
        details=details
    ).model_dump()


def not_found_response(
    resource: str,
    resource_id: str | int | None = None
) -> dict[str, Any]:
    """Helper to create not found response."""
    message = f"{resource} not found"
    if resource_id:
        message += f" (id: {resource_id})"

    return MCPResponse.failure(
        code=MCPErrorCode.NOT_FOUND,
        message=message
    ).model_dump()


def internal_error_response(message: str = "Internal server error") -> dict[str, Any]:
    """Helper to create internal error response."""
    return MCPResponse.failure(
        code=MCPErrorCode.INTERNAL_ERROR,
        message=message
    ).model_dump()
