"""
Agent tools for the Admin MCP server.

Tools:
    - agent_properties_list
    - agent_properties_get
    - agent_properties_create_for_owner
    - agent_properties_verify
    - agent_leases_list
    - agent_leases_create
    - agent_leases_terminate
    - agent_rent_list_due
    - agent_rent_record_payment
    - agent_maintenance_list
    - agent_maintenance_update_status
    - agent_bookings_list_all
    - agent_bookings_update_status
    - agent_dashboard_overview
"""
# Re-export shared helpers for backward-compatible test mocking
from app.mcp.admin.agent_tools.bookings import *  # noqa: F401, F403
from app.mcp.admin.agent_tools.dashboard import *  # noqa: F401, F403
from app.mcp.admin.agent_tools.leases import *  # noqa: F401, F403
from app.mcp.admin.agent_tools.maintenance import *  # noqa: F401, F403

# Import sub-modules to trigger @admin_mcp.tool() registration
from app.mcp.admin.agent_tools.properties import *  # noqa: F401, F403
from app.mcp.admin.agent_tools.rent import *  # noqa: F401, F403
from app.mcp.admin.server import _get_user, _require_agent_or_admin, _require_auth  # noqa: F401
from app.mcp.utils import get_db  # noqa: F401  – re-exported so tests can patch app.mcp.admin.agent.get_db
