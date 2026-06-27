"""Shared imports for Admin MCP agent sub-modules."""

from __future__ import annotations

from app.core.logging import get_logger as _get_logger
from app.core.utils import make_tz_aware, utc_now, utc_now_iso
import sys as _sys

from app.mcp.admin.server import (
    _require_agent_or_admin,
    _require_auth,
    admin_mcp,
)


async def _get_user(db):
    """Lazy proxy — delegates to app.mcp.admin.agent._get_user.

    Using sys.modules to look up the name at call-time means that when a
    test patches ``app.mcp.admin.agent._get_user``, this proxy will call
    the mock rather than the original function.
    """
    return await _sys.modules["app.mcp.admin.agent"]._get_user(db)


def get_db():
    """Lazy proxy — delegates to app.mcp.admin.agent.get_db.

    Same rationale as _get_user: deferred lookup lets test patches on
    ``app.mcp.admin.agent.get_db`` take effect inside all submodule tools.
    """
    return _sys.modules["app.mcp.admin.agent"].get_db()

from app.mcp.apps_sdk import MCP_SECURITY_SCHEMES_MIXED, AuthRequiredError
from app.mcp.errors import (
    MCPErrorCode,
    MCPResponse,
    internal_error_response,
    invalid_input_response,
    not_found_response,
)
from app.mcp.utils import (
    get_user_role,
    serialize_booking,
    serialize_lease,
    serialize_maintenance_request,
    serialize_property_basic,
    serialize_property_full,
    serialize_user_basic,
)

__all__ = [
    "MCP_SECURITY_SCHEMES_MIXED",
    "AuthRequiredError",
    "MCPErrorCode",
    "MCPResponse",
    "_get_user",
    "_require_agent_or_admin",
    "_require_auth",
    "admin_mcp",
    "get_db",
    "get_user_role",
    "internal_error_response",
    "invalid_input_response",
    "logger",
    "make_tz_aware",
    "not_found_response",
    "serialize_booking",
    "serialize_lease",
    "serialize_maintenance_request",
    "serialize_property_basic",
    "serialize_property_full",
    "serialize_user_basic",
    "utc_now",
    "utc_now_iso",
]

logger = _get_logger(__name__)
