"""
Error response schemas and utilities for MCP tools.

Provides standardized error handling and response formats for all MCP tools.
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


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
    def success(cls, data: dict[str, Any]) -> "MCPResponse":
        """Create a success response."""
        return cls(ok=True, data=data, error=None)

    @classmethod
    def failure(
        cls,
        code: MCPErrorCode,
        message: str,
        details: dict[str, Any] | None = None
    ) -> "MCPResponse":
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
