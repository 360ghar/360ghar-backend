"""
System tools for User MCP Server.

Tools for system-level status and feature information:
- System status and available features
"""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    AuthRequiredError,
)
from app.mcp.errors import (
    MCPResponse,
    internal_error_response,
)

# Import the user MCP server instance to register tools
from app.mcp.user.server import _get_user, user_mcp
from app.mcp.utils import get_db

logger = get_logger(__name__)


# ============================================================================
# System Tools
# ============================================================================


@user_mcp.tool(
    "user_system_status",
    annotations={
        "title": "System Status",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def user_system_status() -> dict[str, Any]:
    """Get system status and available user features."""
    try:
        auth_status = "unauthenticated"
        user_info = None

        async for db in get_db():
            user = await _get_user(db)
            if user:
                auth_status = "authenticated"
                user_info = {
                    "id": user.id,
                    "role": getattr(user, "role", "user"),
                    "full_name": getattr(user, "full_name", None),
                }

        return MCPResponse.success({
            "status": "operational",
            "version": settings.APP_VERSION,
            "server": "user",
            "auth": {
                "status": auth_status,
                "user": user_info,
            },
            "features": {
                "owner": {
                    "properties.list": True,
                    "properties.create": True,
                    "properties.update": True,
                    "properties.toggle_availability": True,
                },
                "tenant": {
                    "lease.current": True,
                    "rent.history": True,
                    "maintenance.create": True,
                    "maintenance.list": True,
                },
                "bookings": {
                    "create": True,
                    "list": True,
                    "get": True,
                    "cancel": True,
                    "check_availability": True,
                    "get_pricing": True,
                },
            },
        }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in user.system.status: %s", e, exc_info=True)
        return internal_error_response(f"Failed to get system status: {str(e)}")
