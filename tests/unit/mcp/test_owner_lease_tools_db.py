"""Owner lease tools: stats over the owner scope and a cursor bound to the filters (database-backed).

r2-widgets-mcp-10 and -11: stats cover every lease in scope, not the page.
Wave-3 cursor rule: a cursor from other filters is rejected, not reused.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.chatgpt import pm_lease_tools
from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User


@pytest.fixture
async def lease_world(db_session):
    owner = User(
        supabase_user_id="owner-lease-tools",
        phone="+919400000001",
        full_name="Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    other = User(
        supabase_user_id="owner-lease-other",
        phone="+919400000002",
        full_name="Other Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    tenant = User(
        supabase_user_id="owner-lease-tenant",
        phone="+919400000003",
        full_name="Tenant",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([owner, other, tenant])
    await db_session.flush()

    def _prop(n: int, owner_user: User) -> Property:
        return Property(
            title=f"Flat {n}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=20000,
            monthly_rent=20000,
            owner_id=owner_user.id,
            is_managed=True,
            latitude=12.97,
            longitude=77.59,
        )

    props = [_prop(1, owner), _prop(2, owner), _prop(3, owner), _prop(4, other)]
    db_session.add_all(props)
    await db_session.flush()

    def _lease(prop: Property, owner_user: User, status: LeaseStatus, rent: int) -> Lease:
        return Lease(
            property_id=prop.id,
            owner_id=owner_user.id,
            tenant_user_id=tenant.id,
            status=status,
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 31),
            monthly_rent=rent,
            security_deposit=0,
            payment_due_day=1,
            grace_period_days=5,
        )

    leases = {
        "active_1": _lease(props[0], owner, LeaseStatus.active, 10000),
        "active_2": _lease(props[1], owner, LeaseStatus.active, 12000),
        "ended": _lease(props[2], owner, LeaseStatus.terminated, 99000),
        "other": _lease(props[3], other, LeaseStatus.active, 50000),
    }
    db_session.add_all(leases.values())
    await db_session.flush()
    return SimpleNamespace(db=db_session, owner=owner, leases=leases)


@contextmanager
def _as_owner(world) -> Iterator[None]:
    @asynccontextmanager
    async def _session():
        yield world.db

    with (
        patch.object(pm_lease_tools, "AsyncSessionLocal", side_effect=_session),
        patch.object(pm_lease_tools, "_get_optional_user", new=AsyncMock(return_value=world.owner)),
        patch.object(pm_lease_tools, "get_widget_for_tool", return_value="ui://w.html"),
    ):
        yield


@pytest.mark.asyncio
async def test_list_pages_with_stats_over_the_owner_scope(lease_world):
    with _as_owner(lease_world):
        result = await pm_lease_tools.owner_leases_list(limit=1)

    data = result.structured_content
    assert len(data["leases"]) == 1
    assert data["has_more"] is True and data["next_cursor"]
    # Two active leases of this owner (10000 + 12000). The terminated lease and the other
    # owner's active lease are not in the sum, and the page holds one lease.
    assert data["stats"] == {"active_leases": 2, "total_monthly_rent": 22000.0}


@pytest.mark.asyncio
async def test_cursor_walks_every_owner_lease_and_is_bound_to_the_filters(lease_world):
    owned = {
        lease_world.leases["active_1"].id,
        lease_world.leases["active_2"].id,
        lease_world.leases["ended"].id,
    }
    seen: list[int] = []
    cursor = None
    with _as_owner(lease_world):
        for _ in range(10):
            data = (
                await pm_lease_tools.owner_leases_list(limit=1, cursor=cursor)
            ).structured_content
            seen.extend(item["id"] for item in data["leases"])
            if not data["has_more"]:
                break
            cursor = data["next_cursor"]
        else:
            raise AssertionError("owner_leases_list never reached the last page")

        first = await pm_lease_tools.owner_leases_list(limit=1)
        other_filter = await pm_lease_tools.owner_leases_list(
            limit=1, cursor=first.structured_content["next_cursor"], status=LeaseStatus.active
        )

    assert set(seen) == owned
    assert len(seen) == len(owned)
    # A cursor made without a status filter cannot page a status-filtered list.
    assert other_filter.structured_content["error"] is True
    assert "does not match" in other_filter.structured_content["message"]


@pytest.mark.asyncio
async def test_get_returns_the_lease_key(lease_world):
    lease = lease_world.leases["active_1"]
    with _as_owner(lease_world):
        result = await pm_lease_tools.owner_leases_get(lease_id=lease.id)

    data = result.structured_content
    assert "error" not in data
    assert data["lease"]["id"] == lease.id
