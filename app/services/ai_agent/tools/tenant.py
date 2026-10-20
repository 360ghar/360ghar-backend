"""
Tenant tools — lease, rent, and maintenance tools for tenants.

These tools allow tenants to view their lease, check rent dues/payment
history, and submit/list maintenance requests. Each tool wraps
``app.mcp.tool_ops``, the same code the MCP tenant tools use.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic_ai import RunContext

from app.core.logging import get_logger
from app.mcp.tool_ops import (
    create_maintenance_request,
    get_rent_history,
    get_tenant_current_lease,
    list_maintenance_requests,
)
from app.models.enums import MaintenanceCategory
from app.schemas.pagination import decode_cursor
from app.services.ai_agent.tools.helpers import AgentDeps

logger = get_logger(__name__)


async def tenant_lease_current(
    ctx: RunContext[AgentDeps],
) -> dict[str, Any]:
    """Get the current active lease for the tenant."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await get_tenant_current_lease(db, tenant_user_id=user.id, viewer=user)


async def tenant_rent_history(
    ctx: RunContext[AgentDeps],
    cursor: str | None = None,
    limit: int = 20,
    include_total: bool = False,
) -> dict[str, Any]:
    """Get rent payment history for the tenant, newest first."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await get_rent_history(
        db,
        tenant_user_id=user.id,
        cursor_payload=decode_cursor(cursor, {}) if cursor else {},
        limit=limit,
        filters={},
        include_total=include_total,
    )


async def tenant_maintenance_create(
    ctx: RunContext[AgentDeps],
    property_id: int,
    title: str,
    description: str,
    category: MaintenanceCategory,
    priority: Literal["low", "medium", "high", "urgent", "emergency"] = "medium",
) -> dict[str, Any]:
    """Submit a maintenance request for a property the user is renting."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    return await create_maintenance_request(
        db,
        tenant_user_id=user.id,
        property_id=property_id,
        title=title,
        description=description,
        category=category,
        priority=priority,
    )


async def tenant_maintenance_list(
    ctx: RunContext[AgentDeps],
    cursor: str | None = None,
    limit: int = 20,
    status: Literal["open", "in_progress", "scheduled", "completed", "cancelled"] | None = None,
    include_total: bool = False,
) -> dict[str, Any]:
    """List maintenance requests submitted by the tenant. Status uses the card's labels."""
    db, user = ctx.deps.db, ctx.deps.user
    assert db is not None
    filters = {"status": status}
    return await list_maintenance_requests(
        db,
        tenant_user_id=user.id,
        status=status,
        cursor_payload=decode_cursor(cursor, filters) if cursor else {},
        limit=limit,
        filters=filters,
        include_total=include_total,
    )
