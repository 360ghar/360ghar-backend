"""
Trailing slash normalization middleware.

This middleware handles two cases:
1. MCP mount paths: Adds trailing slashes (Starlette Mount requires them)
2. API routes: Strips trailing slashes to prevent 307 redirects that lose
   Authorization headers

Mount points that need trailing slash:
- /mcp -> /mcp/
- /mcp-admin -> /mcp-admin/

API routes that need trailing slash stripped:
- /api/v1/tours/ -> /api/v1/tours
- /api/v1/users/profile/ -> /api/v1/users/profile
"""

from starlette.types import ASGIApp, Receive, Scope, Send


# Exact mount paths that need trailing slash normalization
MCP_MOUNT_PATHS = {"/mcp", "/mcp-admin"}


class StripTrailingSlashMiddleware:
    """
    Pure ASGI middleware for path normalization.

    - Adds trailing slashes to MCP mount paths (prevents Starlette Mount 307s)
    - Strips trailing slashes from API routes (prevents auth header loss on redirect)
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")

            # Add trailing slash for exact MCP mount paths
            if path in MCP_MOUNT_PATHS:
                scope = dict(scope)
                scope["path"] = path + "/"
            # Strip trailing slash from API routes (except root "/api/")
            elif path.startswith("/api/") and path.endswith("/") and len(path) > 5:
                scope = dict(scope)
                scope["path"] = path.rstrip("/")

        await self.app(scope, receive, send)
