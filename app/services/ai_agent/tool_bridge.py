"""
Tool bridge: adapts MCP tool logic into Pydantic AI tool functions.

.. deprecated::
   This module has been decomposed into :mod:`app.services.ai_agent.tools`.
   Import from the new package directly.  This file is retained as a
   thin re-export shim for backward compatibility.
"""

from __future__ import annotations

from app.services.ai_agent.tools import (  # noqa: F401 — re-exports
    ADMIN_TOOLS,
    GUEST_TOOLS,
    USER_TOOLS,
    AgentDeps,
    _user_schema,
    admin_system_status,
    agent_bookings_list_all,
    agent_bookings_update_status,
    agent_dashboard_overview,
    agent_leases_create,
    agent_leases_list,
    agent_leases_terminate,
    agent_maintenance_list,
    agent_maintenance_update_status,
    agent_properties_create_for_owner,
    agent_properties_get,
    agent_properties_list,
    agent_properties_verify,
    agent_rent_list_due,
    agent_rent_record_payment,
    bookings_cancel,
    bookings_check_availability,
    bookings_create,
    bookings_get,
    bookings_get_pricing,
    bookings_list,
    get_tools_for_role,
    guest_property_details,
    guest_property_recommendations,
    guest_property_search,
    owner_properties_create,
    owner_properties_get,
    owner_properties_list,
    owner_properties_toggle_availability,
    owner_properties_update,
    tenant_lease_current,
    tenant_maintenance_create,
    tenant_maintenance_list,
    tenant_rent_history,
    user_system_status,
)
