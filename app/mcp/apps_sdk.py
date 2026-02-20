"""
Apps SDK / ChatGPT-oriented MCP helpers.

This module bridges FastMCP's ToolResult model with ChatGPT Apps expectations:
- Tool responses must support result-level `_meta` (widget-only) and `isError`.
- Auth-required tool calls should return `_meta["mcp/www_authenticate"]` to trigger
  ChatGPT's OAuth linking UI (per Apps SDK docs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import fastmcp.server.context
from fastmcp import FastMCP
from fastmcp.exceptions import DisabledError, NotFoundError, ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools.tool import ToolResult
from mcp import types as mcp_types

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


MCP_SECURITY_SCHEMES_MIXED: list[dict[str, Any]] = [
    {"type": "noauth"},
    {"type": "oauth2", "scopes": ["mcp:read", "mcp:write"]},
]

MCP_SECURITY_SCHEMES_OAUTH2_ONLY: list[dict[str, Any]] = [
    {"type": "oauth2", "scopes": ["mcp:read", "mcp:write"]},
]


class AppsSDKToolResult(ToolResult):
    """ToolResult that also carries MCP result-level meta and isError."""

    def __init__(
        self,
        *,
        content: Any | None = None,
        structured_content: Dict[str, Any] | None = None,
        result_meta: Optional[Dict[str, Any]] = None,
        is_error: bool = False,
    ) -> None:
        super().__init__(content=content, structured_content=structured_content)
        self.result_meta = result_meta
        self.is_error = is_error


class AuthRequiredError(ToolError):
    """
    Raised by tool handlers to signal OAuth is required.

    The MCP server wrapper converts this into a CallToolResult with:
    - isError=true
    - _meta["mcp/www_authenticate"] set to a WWW-Authenticate challenge string
    """

    def __init__(
        self,
        message: str,
        www_authenticate: str,
        structured_content: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.www_authenticate = www_authenticate
        self.structured_content = structured_content


def _public_base_url() -> str:
    """Return the public base URL (scheme+host) for discovery metadata."""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")
    # Fallback: best-effort from request context, else localhost.
    try:
        request = get_http_request()
        return str(request.base_url).rstrip("/")
    except Exception:
        return "http://localhost:8000"


def _resource_metadata_url_for_current_request() -> str:
    """
    Determine the correct protected-resource metadata URL for this request.

    We key off the mount root_path so mounted servers emit the correct
    protected-resource metadata URL.
    """
    base_url = _public_base_url()
    try:
        request = get_http_request()
        root_path = (request.scope or {}).get("root_path") or ""
    except Exception:
        root_path = ""

    if root_path.startswith("/mcp-admin"):
        return f"{base_url}/.well-known/oauth-protected-resource/mcp-admin"
    # Default to /mcp
    return f"{base_url}/.well-known/oauth-protected-resource/mcp"


def build_www_authenticate(
    *,
    error: str,
    error_description: str,
    scope: str = "mcp:read mcp:write",
    resource_metadata_url: Optional[str] = None,
) -> str:
    """Build a Bearer WWW-Authenticate challenge string for Apps SDK."""
    resource_metadata_url = resource_metadata_url or _resource_metadata_url_for_current_request()
    # Per Apps SDK docs, include resource_metadata plus error + description.
    return (
        'Bearer '
        f'resource_metadata="{resource_metadata_url}", '
        f'error="{error}", '
        f'error_description="{error_description}", '
        f'scope="{scope}"'
    )


def build_widget_tool_meta(
    *,
    widget_uri: str,
    invoking: str,
    invoked: str,
    visibility: str = "host",
    widget_accessible: bool = True,
) -> Dict[str, Any]:
    """
    Build tool-level metadata that is standards-first and ChatGPT-compatible.

    Standards keys (`ui.*`) are primary. OpenAI keys are kept as aliases to
    preserve existing ChatGPT behavior.
    """
    return {
        "ui": {
            "resourceUri": widget_uri,
            "visibility": visibility,
        },
        "ui/resourceUri": widget_uri,
        "ui/visibility": visibility,
        "openai/outputTemplate": widget_uri,
        "openai/widgetAccessible": widget_accessible,
        "openai/toolInvocation/invoking": invoking,
        "openai/toolInvocation/invoked": invoked,
    }


def raise_auth_required(
    *,
    message: str,
    error_description: str,
    scope: str = "mcp:read mcp:write",
    structured_content: Optional[Dict[str, Any]] = None,
) -> None:
    """Convenience helper to raise an AuthRequiredError with correct metadata."""
    www_authenticate = build_www_authenticate(
        error="insufficient_scope",
        error_description=error_description,
        scope=scope,
    )
    raise AuthRequiredError(
        message=message,
        www_authenticate=www_authenticate,
        structured_content=structured_content,
    )


def success_response(
    *,
    data: Dict[str, Any],
    summary: str,
    meta: Optional[Dict[str, Any]] = None,
) -> AppsSDKToolResult:
    """
    Create a successful ChatGPT Apps SDK compatible tool response.

    Args:
        data: Structured JSON data for the model and widget.
        summary: Human-readable text summary for the model.
        meta: Optional result-level metadata (widget-only data).

    Returns:
        AppsSDKToolResult with content, structuredContent, and optional _meta.
    """
    return AppsSDKToolResult(
        content=summary,
        structured_content=data,
        result_meta=meta,
        is_error=False,
    )


def error_response(
    *,
    message: str,
    error_code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AppsSDKToolResult:
    """
    Create an error ChatGPT Apps SDK compatible tool response.

    Args:
        message: Human-readable error message.
        error_code: Optional error code (e.g., 'not_found', 'unauthorized').
        details: Optional additional error details.

    Returns:
        AppsSDKToolResult with isError=True.
    """
    error_data: Dict[str, Any] = {
        "error": True,
        "message": message,
    }
    if error_code:
        error_data["error_code"] = error_code
    if details:
        error_data["details"] = details

    return AppsSDKToolResult(
        content=message,
        structured_content=error_data,
        result_meta=None,
        is_error=True,
    )


class AppsSDKFastMCP(FastMCP):
    """
    FastMCP server variant that can emit CallToolResult with result-level `_meta`.

    Supports both ChatGPT Apps (OpenAI) and MCP Apps (SEP-1865) from a single
    server URL by advertising the ``io.modelcontextprotocol/ui`` extension
    capability and emitting standard + OpenAI-compatible metadata.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Advertise MCP Apps UI extension so Claude, VS Code, MCPJam, etc.
        # know this server can return interactive HTML resources.
        original_create_init = self._mcp_server.create_initialization_options
        def _patched_create_init(
            notification_options: Any = None,
            experimental_capabilities: Optional[Dict[str, Any]] = None,
        ) -> Any:
            caps = experimental_capabilities or {}
            caps["io.modelcontextprotocol/ui"] = {}
            return original_create_init(
                notification_options=notification_options,
                experimental_capabilities=caps,
            )
        self._mcp_server.create_initialization_options = _patched_create_init

    async def _mcp_call_tool(  # type: ignore[override]
        self, key: str, arguments: dict[str, Any]
    ) -> mcp_types.CallToolResult:
        logger.info("MCP tool invoked", extra={"tool": key, "args_keys": list(arguments.keys())})
        async with fastmcp.server.context.Context(fastmcp=self):
            try:
                result = await self._call_tool(key, arguments)

                result_meta: Optional[Dict[str, Any]] = None
                is_error = False
                if isinstance(result, AppsSDKToolResult):
                    result_meta = result.result_meta
                    is_error = result.is_error

                logger.debug("MCP tool completed", extra={"tool": key, "is_error": is_error})
                return mcp_types.CallToolResult(
                    content=result.content,
                    structuredContent=result.structured_content,
                    isError=is_error,
                    _meta=result_meta,
                )
            except AuthRequiredError as exc:
                logger.info("MCP tool requires auth", extra={"tool": key, "auth_message": exc.message})
                return mcp_types.CallToolResult(
                    content=[
                        mcp_types.TextContent(
                            type="text",
                            text=exc.message,
                        )
                    ],
                    structuredContent=exc.structured_content,
                    isError=True,
                    _meta={
                        "mcp/www_authenticate": [exc.www_authenticate],
                    },
                )
            except DisabledError:
                logger.warning("MCP tool disabled", extra={"tool": key})
                raise NotFoundError(f"Unknown tool: {key}")
            except NotFoundError:
                logger.warning("MCP tool not found", extra={"tool": key})
                raise NotFoundError(f"Unknown tool: {key}")
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.error("MCP tool failed", extra={"tool": key, "error": str(exc)}, exc_info=True)
                return mcp_types.CallToolResult(
                    content=[mcp_types.TextContent(type="text", text=str(exc))],
                    isError=True,
                )
