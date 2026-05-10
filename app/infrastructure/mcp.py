"""MCP HTTP app construction for the application factory."""

from __future__ import annotations

from typing import Any

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware

from app.core.logging import get_logger
from app.mcp.admin import admin_mcp
from app.mcp.auth_provider import SupabaseTokenVerifier, get_public_base_url
from app.mcp.chatgpt import register_chatgpt_widgets
from app.mcp.user import user_mcp
from app.middleware.security import RequestLoggingMiddleware

logger = get_logger(__name__)


def _optional_auth_middleware(expected_resources: list[str]) -> list[Middleware]:
    token_verifier = SupabaseTokenVerifier(
        required_scopes=["mcp:read", "mcp:write"],
        expected_resources=expected_resources,
    )
    return [
        Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(token_verifier)),
        Middleware(AuthContextMiddleware),
    ]


def build_mcp_http_apps() -> tuple[Any, Any]:
    """Register widgets and build user/admin MCP HTTP applications."""
    register_chatgpt_widgets(user_mcp)
    logger.debug("ChatGPT widgets registered", extra={"server": "user_mcp"})
    register_chatgpt_widgets(admin_mcp)
    logger.debug("ChatGPT widgets registered", extra={"server": "admin_mcp"})

    public_base_url = get_public_base_url()
    user_optional_auth_middleware = _optional_auth_middleware([f"{public_base_url}/mcp"])
    admin_optional_auth_middleware = _optional_auth_middleware([f"{public_base_url}/mcp-admin"])

    user_mcp_app = user_mcp.http_app(
        path="/",
        transport="http",
        json_response=False,
        stateless_http=True,
        middleware=[
            Middleware(RequestLoggingMiddleware, prefix="/mcp"),
            *user_optional_auth_middleware,
        ],
    )
    logger.debug("User MCP HTTP app created")

    admin_mcp_app = admin_mcp.http_app(
        path="/",
        transport="http",
        json_response=False,
        stateless_http=True,
        middleware=[
            Middleware(RequestLoggingMiddleware, prefix="/mcp-admin"),
            *admin_optional_auth_middleware,
        ],
    )
    logger.debug("Admin MCP HTTP app created")
    return user_mcp_app, admin_mcp_app
