"""
Tests for app.mcp.errors module — MCPErrorCode, MCPResponse, helper functions.
"""


from app.mcp.errors import (
    MCPError,
    MCPErrorCode,
    MCPResponse,
    internal_error_response,
    invalid_input_response,
    not_found_response,
)


class TestMCPErrorCode:
    """Tests for MCPErrorCode enum."""

    def test_auth_error_codes(self):
        assert MCPErrorCode.UNAUTHORIZED.value == "UNAUTHORIZED"
        assert MCPErrorCode.INVALID_TOKEN.value == "INVALID_TOKEN"
        assert MCPErrorCode.TOKEN_EXPIRED.value == "TOKEN_EXPIRED"
        assert MCPErrorCode.INSUFFICIENT_PERMISSIONS.value == "INSUFFICIENT_PERMISSIONS"

    def test_validation_error_codes(self):
        assert MCPErrorCode.INVALID_INPUT.value == "INVALID_INPUT"
        assert MCPErrorCode.MISSING_REQUIRED_FIELD.value == "MISSING_REQUIRED_FIELD"
        assert MCPErrorCode.INVALID_PARAMETER.value == "INVALID_PARAMETER"

    def test_resource_error_codes(self):
        assert MCPErrorCode.NOT_FOUND.value == "NOT_FOUND"
        assert MCPErrorCode.ALREADY_EXISTS.value == "ALREADY_EXISTS"
        assert MCPErrorCode.CONFLICT.value == "CONFLICT"

    def test_system_error_codes(self):
        assert MCPErrorCode.INTERNAL_ERROR.value == "INTERNAL_ERROR"
        assert MCPErrorCode.DATABASE_ERROR.value == "DATABASE_ERROR"
        assert MCPErrorCode.EXTERNAL_SERVICE_ERROR.value == "EXTERNAL_SERVICE_ERROR"


class TestMCPError:
    """Tests for MCPError model."""

    def test_create_error(self):
        error = MCPError(
            code=MCPErrorCode.NOT_FOUND,
            message="Property not found",
        )
        assert error.message == "Property not found"

    def test_error_with_details(self):
        error = MCPError(
            code=MCPErrorCode.INVALID_INPUT,
            message="Invalid parameter",
            details={"field": "property_id"},
        )
        assert error.details == {"field": "property_id"}


class TestMCPResponse:
    """Tests for MCPResponse model."""

    def test_success_response(self):
        response = MCPResponse.success(data={"properties": []})
        assert response.ok is True
        assert response.data == {"properties": []}
        assert response.error is None

    def test_failure_response(self):
        response = MCPResponse.failure(
            code=MCPErrorCode.NOT_FOUND,
            message="Not found",
        )
        assert response.ok is False
        assert response.data is None
        assert response.error is not None
        assert response.error.code == MCPErrorCode.NOT_FOUND.value

    def test_model_dump_excludes_none(self):
        response = MCPResponse.success(data={"id": 1})
        dumped = response.model_dump()
        assert "error" not in dumped

    def test_failure_model_dump(self):
        response = MCPResponse.failure(
            code=MCPErrorCode.UNAUTHORIZED,
            message="Auth required",
        )
        dumped = response.model_dump()
        assert dumped["ok"] is False
        assert "error" in dumped


class TestHelperFunctions:
    """Tests for convenience helper functions."""

    def test_invalid_input_response(self):
        result = invalid_input_response("Missing field")
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value

    def test_invalid_input_with_details(self):
        result = invalid_input_response("Bad value", details={"field": "price"})
        assert result["error"]["details"] == {"field": "price"}

    def test_not_found_response(self):
        result = not_found_response("Property", resource_id=42)
        assert result["ok"] is False
        assert "Property not found" in result["error"]["message"]
        assert "42" in result["error"]["message"]

    def test_not_found_without_id(self):
        result = not_found_response("User")
        assert result["ok"] is False
        assert "User not found" in result["error"]["message"]

    def test_internal_error_response(self):
        result = internal_error_response()
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INTERNAL_ERROR.value

    def test_internal_error_custom_message(self):
        result = internal_error_response("Database timeout")
        assert result["error"]["message"] == "Database timeout"
