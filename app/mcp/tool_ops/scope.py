"""Owner scope for list and stats tools. Shared by the MCP tools and the agent tools."""

from __future__ import annotations

from typing import Any

from app.services.pm_authz import get_accessible_owner_ids


async def owner_scope(db: Any, user: Any, owner_id: int | None) -> list[int] | None:
    """Owner ids the caller may read, or None for every owner (admins only).

    Uses the same rule as the admin MCP tools (``get_accessible_owner_ids``). An
    ``owner_id`` outside the caller's scope gives ``[]``, so no row is returned.
    Pass the result to every stats and list query; ``None`` means no filter.
    """
    # The caller only needs id, role and agent_id, which the ORM user has.
    accessible = await get_accessible_owner_ids(db, actor=user)
    if accessible is None:
        return [owner_id] if owner_id else None
    if owner_id is None:
        return list(accessible)
    return [owner_id] if owner_id in accessible else []
