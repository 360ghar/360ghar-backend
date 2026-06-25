"""MCP HTTP app construction for the application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def _optional_auth_middleware(expected_resources: list[str]) -> list[Any]:
    from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
    from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
    from starlette.middleware import Middleware
    from starlette.middleware.authentication import AuthenticationMiddleware

    from app.mcp.auth_provider import SupabaseTokenVerifier

    token_verifier = SupabaseTokenVerifier(
        required_scopes=["mcp:read", "mcp:write"],
        expected_resources=expected_resources,
    )
    return [
        Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(token_verifier)),
        Middleware(AuthContextMiddleware),
    ]


class LazyMCPHTTPApp:
    """ASGI proxy that builds the concrete MCP app on first request."""

    def __init__(self, server_name: str) -> None:
        self._server_name = server_name
        self._app: Any | None = None
        self._lifespan_cm: Any | None = None
        self._parent_app: Any | None = None
        self._lock = asyncio.Lock()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        app = await self._ensure_app()
        await app(scope, receive, send)
    @asynccontextmanager
    async def lifespan(self, app: Any):
        self._parent_app = app
        # Build the app NOW while parent_app is set, then start its lifespan
        inner_app = await self._ensure_app()
        if hasattr(inner_app, "lifespan"):
            self._lifespan_cm = inner_app.lifespan(app)
            await self._lifespan_cm.__aenter__()
        try:
            yield
        finally:
            if self._lifespan_cm is not None:
                await self._lifespan_cm.__aexit__(None, None, None)
                self._lifespan_cm = None
            self._app = None
            self._parent_app = None

    async def _ensure_app(self) -> Any:
        if self._app is not None:
            return self._app

        async with self._lock:
            if self._app is None:
                self._app = _build_mcp_http_app(self._server_name)
        return self._app


def _build_mcp_http_app(server_name: str) -> Any:
    from starlette.middleware import Middleware

    from app.mcp.admin import admin_mcp
    from app.mcp.auth_provider import get_public_base_url
    from app.mcp.chatgpt import register_chatgpt_widgets
    from app.mcp.user import user_mcp
    from app.middleware.security import RequestLoggingMiddleware

    if server_name == "admin":
        mcp_server = admin_mcp
        mount_prefix = "/mcp-admin"
    else:
        mcp_server = user_mcp
        mount_prefix = "/mcp"

    register_chatgpt_widgets(mcp_server)
    logger.debug("ChatGPT widgets registered", extra={"server": server_name})

    public_base_url = get_public_base_url()
    optional_auth_middleware = _optional_auth_middleware([f"{public_base_url}{mount_prefix}"])
    mcp_app = mcp_server.http_app(
        path="/",
        transport="http",
        json_response=False,
        stateless_http=True,
        middleware=[
            Middleware(RequestLoggingMiddleware, prefix=mount_prefix),
            *optional_auth_middleware,
        ],
    )
    logger.debug("MCP HTTP app created", extra={"server": server_name})
    return mcp_app


def build_mcp_http_apps() -> tuple[Any, Any]:
    """Return lazy user/admin MCP HTTP applications."""
    return LazyMCPHTTPApp("user"), LazyMCPHTTPApp("admin")
