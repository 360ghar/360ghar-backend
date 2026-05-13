"""
Admin MCP Server — instance creation and shared helpers.

The ``admin_mcp`` AppsSDKFastMCP instance is created here and shared
across all sub-modules.  Sub-modules import this instance to register
their tools via ``@admin_mcp.tool()`` decorators.

This module also defines the shared auth helpers used by every tool.
"""
from __future__ import annotations

from typing import NoReturn

from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    AppsSDKFastMCP,
    raise_auth_required,
)
from app.mcp.utils import (
    get_user_from_mcp_context,
    get_user_role,
)
from app.models.enums import UserRole

logger = get_logger(__name__)

# Create the Admin MCP server instance
admin_mcp = AppsSDKFastMCP("ghar360-admin")


async def _get_user(db):
    """Get user from MCP OAuth context."""
    return await get_user_from_mcp_context(db)


def _require_auth(*, action: str, message: str, scope: str = "mcp:read mcp:write") -> NoReturn:
    raise_auth_required(
        message=message,
        error_description=message,
        scope=scope,
        structured_content={
            "requires_auth": True,
            "action": action,
        },
    )


def _require_agent_or_admin(user) -> bool:
    """Check if user is agent or admin, return True if authorized."""
    role = get_user_role(user)
    return role in (UserRole.agent, UserRole.admin)


# Import sub-modules to trigger tool registration
from app.mcp.admin import admin as _admin  # noqa: E402,F401
from app.mcp.admin import agent as _agent  # noqa: E402,F401
