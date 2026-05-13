"""
Admin tools for the Admin MCP server.

Tools:
    - admin_system_status
"""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.mcp.admin.server import _get_user, admin_mcp
from app.mcp.apps_sdk import (
    MCP_SECURITY_SCHEMES_MIXED,
    AuthRequiredError,
)
from app.mcp.errors import (
    MCPResponse,
    internal_error_response,
)
from app.mcp.utils import (
    get_db,
    get_user_role,
)
from app.models.enums import UserRole

logger = get_logger(__name__)


# ============================================================================
# System Tools
# ============================================================================


@admin_mcp.tool(
    "admin_system_status",
    annotations={
        "title": "Admin System Status",
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "securitySchemes": MCP_SECURITY_SCHEMES_MIXED,
    },
)
async def admin_system_status() -> dict[str, Any]:
    """Get admin system status and available features."""
    try:
        auth_status = "unauthenticated"
        user_info = None
        is_authorized = False

        async for db in get_db():
            user = await _get_user(db)
            if user:
                auth_status = "authenticated"
                role = get_user_role(user)
                is_authorized = role in (UserRole.agent, UserRole.admin)
                user_info = {
                    "id": user.id,
                    "role": role.value,
                    "full_name": getattr(user, "full_name", None),
                    "is_authorized": is_authorized,
                }

        return MCPResponse.success({
            "status": "operational",
            "version": settings.APP_VERSION,
            "server": "admin",
            "auth": {
                "status": auth_status,
                "user": user_info,
            },
            "access": "granted" if is_authorized else "denied",
            "features": {
                "agent.properties": {
                    "list": True,
                    "get": True,
                    "create_for_owner": True,
                    "verify": True,
                },
                "agent.leases": {
                    "list": True,
                    "create": True,
                    "terminate": True,
                },
                "agent.rent": {
                    "list_due": True,
                    "record_payment": True,
                },
                "agent.maintenance": {
                    "list": True,
                    "update_status": True,
                },
                "agent.bookings": {
                    "list_all": True,
                    "update_status": True,
                },
                "agent.dashboard": {
                    "overview": True,
                },
            },
        }).model_dump()
    except AuthRequiredError:
        raise
    except Exception as e:
        logger.error("Error in admin.system.status: %s", e, exc_info=True)
        return internal_error_response(f"Failed to get system status: {str(e)}")
