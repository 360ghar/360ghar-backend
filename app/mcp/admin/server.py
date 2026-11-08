"""
Admin MCP Server — instance creation and shared helpers.

The ``admin_mcp`` AppsSDKFastMCP instance is created here and shared
across all sub-modules.  Sub-modules import this instance to register
their tools via ``@admin_mcp.tool()`` decorators.

This module also defines the shared auth helpers used by every tool.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.mcp.apps_sdk import AppsSDKFastMCP

# Re-exported: tool modules import these two names from this module.
from app.mcp.utils import get_user_from_mcp_context as _get_user  # noqa: F401
from app.mcp.utils import get_user_role
from app.mcp.utils import require_mcp_auth as _require_auth  # noqa: F401
from app.models.enums import UserRole

logger = get_logger(__name__)

# Create the Admin MCP server instance
admin_mcp = AppsSDKFastMCP("ghar360-admin")


def _require_agent_or_admin(user) -> bool:
    """Check if user is agent or admin, return True if authorized."""
    role = get_user_role(user)
    return role in (UserRole.agent, UserRole.admin)


# Import sub-modules to trigger tool registration
from app.mcp.admin import admin as _admin  # noqa: E402,F401
from app.mcp.admin import agent as _agent  # noqa: E402,F401
