"""
Shared tool operation implementations for MCP servers and the AI agent tool bridge.

These functions contain the business logic (service calls, DB queries, serialization)
that is shared across:
- ``app/mcp/user/`` (User MCP server package at /mcp)
- ``app/mcp/admin/`` (Admin MCP server package at /mcp-admin)
- ``app/services/ai_agent/tool_bridge.py`` (Pydantic AI agent)

Each function takes a ``db: AsyncSession`` and domain-specific parameters,
performs authorization checks, calls the appropriate service layer,
and returns a plain dict response. The callers (MCP server decorators,
tool bridge wrappers) handle response format wrapping (MCPResponse,
AppsSDKToolResult, etc.).
"""

from app.mcp.tool_ops.bookings import (
    cancel_booking,
    check_availability,
    create_booking,
    get_booking_detail,
    get_pricing,
    list_user_bookings,
)
from app.mcp.tool_ops.dashboard import compute_dashboard_metrics
from app.mcp.tool_ops.leases import (
    create_lease,
    get_tenant_current_lease,
    list_leases,
    terminate_lease,
)
from app.mcp.tool_ops.maintenance import (
    apply_maintenance_status_update,
    build_maintenance_status_filter,
    create_maintenance_request,
    list_maintenance_requests,
)
from app.mcp.tool_ops.properties import (
    create_property,
    enrich_properties_with_lease_info,
    get_property_detail,
    list_properties_enriched,
    toggle_property_availability,
    update_property_fields,
)
from app.mcp.tool_ops.rent import (
    compute_rent_due_items,
    get_rent_history,
    record_rent_payment,
)
from app.schemas.user import User as UserSchema


def _user_schema(user) -> UserSchema:
    """Convert a SQLAlchemy User to a Pydantic UserSchema."""
    return UserSchema.model_validate(user)


__all__ = [
    # Properties
    "create_property",
    "enrich_properties_with_lease_info",
    "get_property_detail",
    "list_properties_enriched",
    "toggle_property_availability",
    "update_property_fields",
    # Leases
    "create_lease",
    "get_tenant_current_lease",
    "list_leases",
    "terminate_lease",
    # Rent
    "compute_rent_due_items",
    "get_rent_history",
    "record_rent_payment",
    # Maintenance
    "apply_maintenance_status_update",
    "build_maintenance_status_filter",
    "create_maintenance_request",
    "list_maintenance_requests",
    # Bookings
    "cancel_booking",
    "check_availability",
    "create_booking",
    "get_booking_detail",
    "get_pricing",
    "list_user_bookings",
    # Dashboard
    "compute_dashboard_metrics",
]
