"""
User MCP Server - Core instance and shared utilities.

This module creates the User MCP server instance and provides shared
helper functions used across all user tool sub-modules.
"""
from __future__ import annotations

from typing import NoReturn

from app.core.logging import get_logger
from app.mcp.apps_sdk import (
    AppsSDKFastMCP,
    raise_auth_required,
)
from app.mcp.utils import get_user_from_mcp_context

logger = get_logger(__name__)

# Create the User MCP server instance
user_mcp = AppsSDKFastMCP("ghar360-user")


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


def _count_mcp_tools(mcp: AppsSDKFastMCP) -> int:
    """Count the number of tools currently registered on the MCP server.

    Uses the local provider's internal component storage to get a
    synchronous tool count without needing an async event loop.
    """
    from fastmcp.tools.base import Tool

    try:
        components = mcp.local_provider._components
        return sum(1 for v in components.values() if isinstance(v, Tool))
    except AttributeError:
        # If internal API changes, fall back to 0 (cannot verify)
        return 0


# ============================================================================
# Import sub-modules to register tools on user_mcp
# ============================================================================
# These imports trigger the @user_mcp.tool() decorators defined in each
# sub-module. They must come AFTER the user_mcp instance is created.

from app.mcp.user import booking as booking  # noqa: E402,F401
from app.mcp.user import discovery as discovery  # noqa: E402,F401
from app.mcp.user import owner as owner  # noqa: E402,F401
from app.mcp.user import system as system  # noqa: E402,F401
from app.mcp.user import tenant as tenant  # noqa: E402,F401
from app.mcp.user import visits as visits  # noqa: E402,F401

# ============================================================================
# ChatGPT App PM Tools Registration
# ============================================================================
# Import ChatGPT PM tools (cross-cutting owner/tenant) to register them
try:
    _before_count = _count_mcp_tools(user_mcp)
    from app.mcp.chatgpt import (
        pm_dashboard_tools,  # noqa: F401
        pm_lease_tools,  # noqa: F401
        pm_maintenance_tools,  # noqa: F401
        pm_rent_tools,  # noqa: F401
        pm_tenant_tools,  # noqa: F401
    )
    _after_count = _count_mcp_tools(user_mcp)
    _new_tools = _after_count - _before_count
    if _new_tools == 0:
        logger.warning(
            "No new ChatGPT PM tools registered after import. "
            "This may indicate a registration failure."
        )
    else:
        logger.info(
            "ChatGPT PM tools registered successfully",
            extra={"new_tools_count": _new_tools},
        )
except ImportError as e:
    logger.warning("ChatGPT PM tools not registered: %s", e)
