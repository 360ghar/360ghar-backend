"""
Tests for app.mcp.apps_sdk module — AppsSDKFastMCP, build_widget_tool_meta, security schemes.
"""


from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    MCP_SECURITY_SCHEMES_OAUTH2_ONLY,
    RESOURCE_MIME_TYPE,
    AppsSDKToolResult,
    build_widget_tool_meta,
)


class TestResourceMimeType:
    def test_mime_type_format(self):
        assert RESOURCE_MIME_TYPE == "text/html;profile=mcp-app"

    def test_mime_type_contains_html(self):
        assert "text/html" in RESOURCE_MIME_TYPE

    def test_mime_type_contains_profile(self):
        assert "profile=mcp-app" in RESOURCE_MIME_TYPE


class TestSecuritySchemes:
    def test_mixed_schemes_includes_noauth(self):
        types = [s["type"] for s in MCP_SECURITY_SCHEMES_MIXED]
        assert "noauth" in types

    def test_mixed_schemes_includes_oauth2(self):
        types = [s["type"] for s in MCP_SECURITY_SCHEMES_MIXED]
        assert "oauth2" in types

    def test_oauth2_only_has_no_noauth(self):
        types = [s["type"] for s in MCP_SECURITY_SCHEMES_OAUTH2_ONLY]
        assert "noauth" not in types

    def test_oauth2_only_has_oauth2(self):
        types = [s["type"] for s in MCP_SECURITY_SCHEMES_OAUTH2_ONLY]
        assert "oauth2" in types

    def test_oauth2_scopes_present(self):
        for scheme in MCP_SECURITY_SCHEMES_OAUTH2_ONLY:
            if scheme["type"] == "oauth2":
                assert "scopes" in scheme
                assert "mcp:read" in scheme["scopes"]
                assert "mcp:write" in scheme["scopes"]


class TestAppsSDKToolResult:
    def test_default_not_error(self):
        result = AppsSDKToolResult(content="Hello")
        assert result.is_error is False

    def test_error_result(self):
        result = AppsSDKToolResult(content="Error occurred", is_error=True)
        assert result.is_error is True

    def test_structured_content(self):
        result = AppsSDKToolResult(
            content="Summary",
            structured_content={"key": "value"},
        )
        assert result.structured_content == {"key": "value"}

    def test_meta_content(self):
        result = AppsSDKToolResult(
            content="Hello",
            result_meta={"ui": {"resourceUri": "widget://test"}},
        )
        assert result.meta is not None


class TestBuildWidgetToolMeta:
    def test_returns_dict(self):
        result = build_widget_tool_meta(
            widget_uri="https://example.com/widget.html",
            invoking="discovery_search",
            invoked="discovery_property_get",
        )
        assert isinstance(result, dict)

    def test_includes_ui_resource_uri(self):
        result = build_widget_tool_meta(
            widget_uri="https://example.com/widget.html",
            invoking="discovery_search",
            invoked="discovery_property_get",
        )
        assert "ui" in result
        assert result["ui"]["resourceUri"] == "https://example.com/widget.html"

    def test_includes_openai_compat_keys(self):
        result = build_widget_tool_meta(
            widget_uri="https://example.com/widget.html",
            invoking="discovery_search",
            invoked="discovery_property_get",
        )
        # Should include OpenAI-compatible aliases with "openai/" prefix
        openai_keys = [k for k in result.keys() if k.startswith("openai/")]
        assert len(openai_keys) >= 2, f"Expected OpenAI compat keys, got: {list(result.keys())}"

    def test_empty_widget_uri(self):
        result = build_widget_tool_meta(
            widget_uri=None,
            invoking="test",
            invoked="test",
        )
        assert isinstance(result, dict)

    def test_custom_visibility(self):
        result = build_widget_tool_meta(
            widget_uri="https://example.com/w.html",
            invoking="owner_list",
            invoked="owner_get",
            visibility="private",
        )
        assert result["ui"]["visibility"] == "private"
