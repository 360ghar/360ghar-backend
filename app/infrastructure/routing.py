"""Route and mount registration for the FastAPI application."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.api.api_v1.api import api_router
from app.api.api_v1.endpoints.oauth import oauth_mcp_router, oauth_wellknown_router
from app.api.api_v1.endpoints.websocket import router as ws_router
from app.api.deeplinks import redirect_router as deeplink_redirect_router
from app.api.deeplinks import wellknown_router as deeplink_wellknown_router
from app.api.share import router as share_router
from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def register_routes(app: FastAPI, *, user_mcp_app: Any, admin_mcp_app: Any) -> None:
    """Register REST, websocket, share, OAuth, and MCP routes."""
    app.include_router(api_router, prefix=settings.API_V1_STR)
    app.include_router(ws_router, tags=["websocket"])
    app.include_router(share_router, tags=["share"])
    app.include_router(oauth_wellknown_router)
    app.include_router(oauth_mcp_router)
    # Deep links: Android/iOS verification files + smart fallback pages at root.
    # Registered after the API/share/OAuth routers so the app-link fallback
    # paths never shadow more specific application routes.
    app.include_router(deeplink_wellknown_router, tags=["deeplinks"])
    app.include_router(deeplink_redirect_router, tags=["deeplinks"])
    app.mount("/mcp", user_mcp_app)
    app.mount("/mcp-admin", admin_mcp_app)
    logger.info("MCP servers mounted", extra={"paths": ["/mcp", "/mcp-admin"]})
