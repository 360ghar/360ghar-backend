"""
Tests for MCP protocol compliance with the Apps SDK specification.

These tests verify that all tools and widgets meet the OpenAI Apps SDK
and MCP protocol requirements without requiring a running server.
"""
import pytest

from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    RESOURCE_MIME_TYPE,
    build_widget_tool_meta,
    build_www_authenticate,
    error_response,
    success_response,
)
from app.mcp.chatgpt import WIDGETS, get_widget_for_tool
from app.mcp.chatgpt.response_formatter import format_auth_required_response


class TestResourceMimeType:
    """Verify RESOURCE_MIME_TYPE constant."""

    def test_mime_type_value(self):
        assert RESOURCE_MIME_TYPE == "text/html;profile=mcp-app"


class TestWidgetToolMetaBuilder:
    """Verify build_widget_tool_meta produces correct metadata."""

    def test_standard_ui_keys(self):
        meta = build_widget_tool_meta(
            widget_uri="ui://widget/test.html",
            invoking="Loading...",
            invoked="Done",
        )
        assert meta["ui"]["resourceUri"] == "ui://widget/test.html"
        assert meta["ui"]["visibility"] == "host"

    def test_openai_compatibility_keys(self):
        meta = build_widget_tool_meta(
            widget_uri="ui://widget/test.html",
            invoking="Loading...",
            invoked="Done",
        )
        assert meta["openai/outputTemplate"] == "ui://widget/test.html"
        assert meta["openai/widgetAccessible"] is True
        assert meta["openai/toolInvocation/invoking"] == "Loading..."
        assert meta["openai/toolInvocation/invoked"] == "Done"


class TestWidgetMapping:
    """Verify the WIDGETS mapping covers all expected tools and widgets."""

    EXPECTED_WIDGETS = [
        "PropertySearchWidget",
        "PropertyDetailsWidget",
        "PropertySwipeWidget",
        "VisitSchedulerWidget",
        "VisitListWidget",
        "LeaseDetailsWidget",
        "MaintenanceWidget",
        "OwnerDashboardWidget",
        "LeaseManagementWidget",
        "RentCollectionWidget",
        "TenantRentWidget",
    ]

    def test_all_widgets_defined(self):
        for widget_name in self.EXPECTED_WIDGETS:
            assert widget_name in WIDGETS, f"Missing widget: {widget_name}"

    def test_each_widget_has_tools(self):
        for widget_name, config in WIDGETS.items():
            assert "tools" in config, f"{widget_name} missing 'tools'"
            assert len(config["tools"]) > 0, f"{widget_name} has empty tools list"

    def test_get_widget_for_tool_returns_uri(self):
        # Test a known tool
        uri = get_widget_for_tool("discovery_search")
        assert uri is not None
        assert uri.startswith("ui://widget/")

    def test_get_widget_for_unknown_tool_returns_none(self):
        assert get_widget_for_tool("nonexistent_tool") is None


class TestSuccessResponse:
    """Verify success_response produces correct AppsSDKToolResult."""

    def test_basic_response(self):
        result = success_response(data={"key": "val"}, summary="Test summary")
        assert result.structured_content == {"key": "val"}
        assert result.is_error is False

    def test_response_with_widget_uri(self):
        result = success_response(
            data={"key": "val"},
            summary="Test",
            widget_uri="ui://widget/test.html",
        )
        assert result.meta is not None
        assert result.meta["ui"]["resourceUri"] == "ui://widget/test.html"


class TestErrorResponse:
    """Verify error_response produces correct AppsSDKToolResult."""

    def test_error_response(self):
        result = error_response(message="Something failed", error_code="not_found")
        assert result.is_error is True
        assert result.structured_content["error"] is True
        assert result.structured_content["error_code"] == "not_found"


class TestWwwAuthenticateChallenge:
    """Verify WWW-Authenticate challenge format."""

    def test_challenge_contains_resource_metadata(self):
        challenge = build_www_authenticate(
            error="insufficient_scope",
            error_description="Login required",
            resource_metadata_url="https://api.360ghar.com/.well-known/oauth-protected-resource/mcp",
        )
        assert "resource_metadata=" in challenge
        assert "Bearer " in challenge
        assert 'error="insufficient_scope"' in challenge
        assert 'error_description="Login required"' in challenge

    def test_challenge_includes_scope(self):
        challenge = build_www_authenticate(
            error="invalid_token",
            error_description="Token expired",
            scope="mcp:read mcp:write",
        )
        assert 'scope="mcp:read mcp:write"' in challenge


class TestAuthRequiredResponse:
    """Verify format_auth_required_response raises with correct challenge."""

    def test_raises_auth_required_error(self):
        from app.mcp.apps_sdk import AuthRequiredError
        with pytest.raises(AuthRequiredError) as exc_info:
            format_auth_required_response("swipe")
        assert "resource_metadata=" in exc_info.value.www_authenticate
        assert exc_info.value.structured_content["requires_auth"] is True
        assert exc_info.value.structured_content["action"] == "swipe"

    def test_custom_message(self):
        from app.mcp.apps_sdk import AuthRequiredError
        with pytest.raises(AuthRequiredError) as exc_info:
            format_auth_required_response("book", message="Custom auth message")
        assert exc_info.value.message == "Custom auth message"


class TestSecuritySchemes:
    """Verify security scheme constants are correctly defined."""

    def test_mixed_schemes(self):
        assert len(MCP_SECURITY_SCHEMES_MIXED) == 2
        types = [s["type"] for s in MCP_SECURITY_SCHEMES_MIXED]
        assert "noauth" in types
        assert "oauth2" in types

    def test_oauth_only_schemes(self):
        assert len(MCP_SECURITY_SCHEMES_OAUTH2_ONLY) == 1
        assert MCP_SECURITY_SCHEMES_OAUTH2_ONLY[0]["type"] == "oauth2"
