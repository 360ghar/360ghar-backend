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

# Import each tool by name. The import registers the @admin_mcp.tool() handler
# and keeps the name importable from this module.
from app.mcp.admin.agent_tools.bookings import (  # noqa: F401
    agent_bookings_list_all,
    agent_bookings_update_status,
)
from app.mcp.admin.agent_tools.dashboard import agent_dashboard_overview  # noqa: F401
from app.mcp.admin.agent_tools.leases import (  # noqa: F401
    agent_leases_create,
    agent_leases_list,
    agent_leases_terminate,
)
from app.mcp.admin.agent_tools.maintenance import (  # noqa: F401
    agent_maintenance_list,
    agent_maintenance_update_status,
)
from app.mcp.admin.agent_tools.properties import (  # noqa: F401
    agent_properties_create_for_owner,
    agent_properties_get,
    agent_properties_list,
    agent_properties_verify,
)
from app.mcp.admin.agent_tools.rent import (  # noqa: F401
    agent_rent_list_due,
    agent_rent_record_payment,
)
