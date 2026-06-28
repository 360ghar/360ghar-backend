"""
AI agent tools package.

Re-exports all tool functions and the ``AgentDeps`` dependency container
so that existing callers can import from ``app.services.ai_agent.tools``
instead of the individual sub-modules.

Tool registration constants (``USER_TOOLS``, ``ADMIN_TOOLS``,
``GUEST_TOOLS``) and the ``get_tools_for_role`` helper are also
re-exported here for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from app.services.ai_agent.tools.booking import (  # noqa: F401 — re-exports
    agent_bookings_list_all,
    agent_bookings_update_status,
    bookings_cancel,
    bookings_check_availability,
    bookings_create,
    bookings_get,
    bookings_get_pricing,
    bookings_list,
    user_system_status,
)
from app.services.ai_agent.tools.discovery import (  # noqa: F401 — re-exports
    guest_property_details,
    guest_property_recommendations,
    guest_property_search,
)
from app.services.ai_agent.tools.helpers import (  # noqa: F401 — re-exports
    AgentDeps,
    _user_schema,
)
from app.services.ai_agent.tools.owner import (  # noqa: F401 — re-exports
    admin_system_status,
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
    owner_properties_create,
    owner_properties_get,
    owner_properties_list,
    owner_properties_toggle_availability,
    owner_properties_update,
)
from app.services.ai_agent.tools.tenant import (  # noqa: F401 — re-exports
    tenant_lease_current,
    tenant_maintenance_create,
    tenant_maintenance_list,
    tenant_rent_history,
)

# ============================================================================
# Tool Registration
# ============================================================================

# Maps tool name → (function, description, is_admin_only)
USER_TOOLS: list[tuple[str, Any, str]] = [
    ("owner_properties_list", owner_properties_list, "List all properties owned by the user"),
    ("owner_properties_create", owner_properties_create, "Create a new property listing"),
    ("owner_properties_get", owner_properties_get, "Get detailed property info"),
    ("owner_properties_update", owner_properties_update, "Update a property listing"),
    (
        "owner_properties_toggle_availability",
        owner_properties_toggle_availability,
        "Toggle property availability",
    ),
    ("tenant_lease_current", tenant_lease_current, "View current active lease"),
    ("tenant_rent_history", tenant_rent_history, "View rent payment history"),
    ("tenant_maintenance_create", tenant_maintenance_create, "Submit a maintenance request"),
    ("tenant_maintenance_list", tenant_maintenance_list, "List maintenance requests"),
    ("bookings_check_availability", bookings_check_availability, "Check booking availability"),
    ("bookings_get_pricing", bookings_get_pricing, "Get booking pricing breakdown"),
    ("bookings_create", bookings_create, "Create a booking"),
    ("bookings_list", bookings_list, "List user bookings"),
    ("bookings_get", bookings_get, "Get booking details"),
    ("bookings_cancel", bookings_cancel, "Cancel a booking"),
    ("user_system_status", user_system_status, "Get system status"),
]

ADMIN_TOOLS: list[tuple[str, Any, str]] = [
    ("agent_properties_list", agent_properties_list, "List managed properties"),
    ("agent_properties_get", agent_properties_get, "Get managed property details"),
    (
        "agent_properties_create_for_owner",
        agent_properties_create_for_owner,
        "Create property for an owner",
    ),
    ("agent_properties_verify", agent_properties_verify, "Verify a property listing"),
    ("agent_leases_list", agent_leases_list, "List leases"),
    ("agent_leases_create", agent_leases_create, "Create a lease"),
    ("agent_leases_terminate", agent_leases_terminate, "Terminate a lease"),
    ("agent_rent_list_due", agent_rent_list_due, "List overdue rent"),
    ("agent_rent_record_payment", agent_rent_record_payment, "Record a rent payment"),
    ("agent_maintenance_list", agent_maintenance_list, "List maintenance requests (admin)"),
    (
        "agent_maintenance_update_status",
        agent_maintenance_update_status,
        "Update maintenance request status",
    ),
    ("agent_bookings_list_all", agent_bookings_list_all, "List all bookings (admin)"),
    ("agent_bookings_update_status", agent_bookings_update_status, "Update booking status"),
    ("agent_dashboard_overview", agent_dashboard_overview, "Get dashboard overview"),
    ("admin_system_status", admin_system_status, "Admin system status"),
]


GUEST_TOOLS: list[tuple[str, Any, str]] = [
    (
        "guest_property_search",
        guest_property_search,
        "Search properties by city, type, purpose, price, bedrooms, or text query",
    ),
    (
        "guest_property_details",
        guest_property_details,
        "Get full details for a specific property by ID",
    ),
    (
        "guest_property_recommendations",
        guest_property_recommendations,
        "Get a list of recommended properties to browse",
    ),
]


def get_tools_for_role(role: str) -> list[tuple[str, Any, str]]:
    """Return the list of tools available for a given user role."""
    if role == "guest":
        return list(GUEST_TOOLS)
    tools = list(USER_TOOLS)
    if role in ("agent", "admin"):
        tools.extend(ADMIN_TOOLS)
    return tools


__all__ = [
    # Helpers
    "AgentDeps",
    "_user_schema",
    # Discovery
    "guest_property_search",
    "guest_property_details",
    "guest_property_recommendations",
    # Owner
    "owner_properties_list",
    "owner_properties_create",
    "owner_properties_get",
    "owner_properties_update",
    "owner_properties_toggle_availability",
    "agent_properties_list",
    "agent_properties_get",
    "agent_properties_create_for_owner",
    "agent_properties_verify",
    "agent_leases_list",
    "agent_leases_create",
    "agent_leases_terminate",
    "agent_rent_list_due",
    "agent_rent_record_payment",
    "agent_maintenance_list",
    "agent_maintenance_update_status",
    "agent_dashboard_overview",
    "admin_system_status",
    # Tenant
    "tenant_lease_current",
    "tenant_rent_history",
    "tenant_maintenance_create",
    "tenant_maintenance_list",
    # Booking
    "bookings_check_availability",
    "bookings_get_pricing",
    "bookings_create",
    "bookings_list",
    "bookings_get",
    "bookings_cancel",
    "user_system_status",
    "agent_bookings_list_all",
    "agent_bookings_update_status",
    # Registration
    "USER_TOOLS",
    "ADMIN_TOOLS",
    "GUEST_TOOLS",
    "get_tools_for_role",
]
