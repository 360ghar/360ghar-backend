"""
Trailing slash normalization middleware for MCP/SSE endpoints.

Starlette's Mount requires trailing slashes for proper routing.
This middleware adds trailing slashes to MCP mount points to prevent
307 redirects.

Mount points:
- /mcp -> /mcp/
- /mcp-admin -> /mcp-admin/
- /sse -> /sse/

Note: Paths like /mcp/oauth/authorize should NOT be modified as they are
regular FastAPI routes, not mounted app endpoints.
"""

from starlette.types import ASGIApp, Receive, Scope, Send


# Exact mount paths that need trailing slash normalization
MCP_MOUNT_PATHS = {"/mcp", "/mcp-admin", "/sse"}


class StripTrailingSlashMiddleware:
    """
    Pure ASGI middleware to add trailing slashes for MCP mount paths.

    This prevents Starlette's Mount from issuing 307 redirects when
    clients POST to /mcp instead of /mcp/.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")

            # Add trailing slash for exact mount paths
            if path in MCP_MOUNT_PATHS:
                scope = dict(scope)
                scope["path"] = path + "/"

        await self.app(scope, receive, send)
