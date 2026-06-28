from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import (
    InsufficientPermissionsError,
    NotFoundException,
    UserNotFoundException,
)
from app.services.pm_authz import (
    assert_can_access_lease,
    assert_can_access_property,
    assert_can_manage_owner_portfolio,
    can_access_visit,
    get_accessible_owner_ids,
)


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_assert_can_manage_owner_portfolio_allows_admin():
    db = AsyncMock()
    actor = SimpleNamespace(id=1, role="admin", agent_id=None)

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=999)

    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_assert_can_manage_owner_portfolio_rejects_agent_without_profile():
    db = AsyncMock()
    actor = SimpleNamespace(id=2, role="agent", agent_id=None)

    with pytest.raises(InsufficientPermissionsError, match="not linked"):
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=10)


@pytest.mark.asyncio
async def test_assert_can_manage_owner_portfolio_rejects_missing_owner():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    actor = SimpleNamespace(id=2, role="agent", agent_id=50)

    with pytest.raises(UserNotFoundException, match="Owner not found"):
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=10)


@pytest.mark.asyncio
async def test_assert_can_manage_owner_portfolio_rejects_unassigned_agent():
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(id=10, agent_id=99))
    actor = SimpleNamespace(id=2, role="agent", agent_id=50)

    with pytest.raises(InsufficientPermissionsError, match="Agent not authorized"):
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=10)


@pytest.mark.asyncio
async def test_assert_can_manage_owner_portfolio_rejects_user_for_other_owner():
    db = AsyncMock()
    actor = SimpleNamespace(id=3, role="user", agent_id=None)

    with pytest.raises(InsufficientPermissionsError, match="Not authorized"):
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=9)


@pytest.mark.asyncio
async def test_assert_can_manage_owner_portfolio_allows_owner_self():
    db = AsyncMock()
    actor = SimpleNamespace(id=3, role="user", agent_id=None)

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=3)


@pytest.mark.asyncio
async def test_assert_can_access_property_allows_tenant_with_active_lease():
    db = AsyncMock()
    prop = SimpleNamespace(
        id=5,
        owner_id=2,
        owner=SimpleNamespace(agent_id=7),
        images=[],
        property_amenities=[],
    )
    db.execute = AsyncMock(side_effect=[_ScalarResult(prop), _ScalarResult(123)])
    actor = SimpleNamespace(id=9, role="user", agent_id=None)

    result = await assert_can_access_property(db, actor=actor, property_id=5, allow_tenant=True)

    assert result is prop


@pytest.mark.asyncio
async def test_assert_can_access_property_denies_tenant_without_active_lease():
    db = AsyncMock()
    prop = SimpleNamespace(
        id=5,
        owner_id=2,
        owner=SimpleNamespace(agent_id=7),
        images=[],
        property_amenities=[],
    )
    db.execute = AsyncMock(side_effect=[_ScalarResult(prop), _ScalarResult(None)])
    actor = SimpleNamespace(id=9, role="user", agent_id=None)

    with pytest.raises(InsufficientPermissionsError, match="Not authorized"):
        await assert_can_access_property(db, actor=actor, property_id=5, allow_tenant=True)


@pytest.mark.asyncio
async def test_assert_can_access_lease_raises_not_found():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    actor = SimpleNamespace(id=9, role="user", agent_id=None)

    with pytest.raises(NotFoundException, match="Lease not found"):
        await assert_can_access_lease(db, actor=actor, lease_id=77)


@pytest.mark.asyncio
async def test_assert_can_access_lease_allows_tenant():
    db = AsyncMock()
    lease = SimpleNamespace(
        id=7,
        owner_id=2,
        tenant_user_id=9,
        property=SimpleNamespace(images=[]),
        tenant_user=SimpleNamespace(id=9),
    )
    db.execute = AsyncMock(return_value=_ScalarResult(lease))
    actor = SimpleNamespace(id=9, role="user", agent_id=None)

    result = await assert_can_access_lease(db, actor=actor, lease_id=7)

    assert result is lease


@pytest.mark.asyncio
async def test_assert_can_access_lease_rejects_unassigned_agent():
    db = AsyncMock()
    lease = SimpleNamespace(
        id=7,
        owner_id=2,
        tenant_user_id=9,
        property=SimpleNamespace(images=[]),
        tenant_user=SimpleNamespace(id=9),
    )
    db.execute = AsyncMock(return_value=_ScalarResult(lease))
    db.get = AsyncMock(return_value=SimpleNamespace(id=2, agent_id=77))
    actor = SimpleNamespace(id=10, role="agent", agent_id=55)

    with pytest.raises(InsufficientPermissionsError, match="Agent not authorized"):
        await assert_can_access_lease(db, actor=actor, lease_id=7)


@pytest.mark.asyncio
async def test_get_accessible_owner_ids_admin_returns_none():
    db = AsyncMock()
    actor = SimpleNamespace(id=1, role="admin", agent_id=None)

    result = await get_accessible_owner_ids(db, actor=actor)

    assert result is None


@pytest.mark.asyncio
async def test_get_accessible_owner_ids_agent_without_profile_returns_empty():
    db = AsyncMock()
    actor = SimpleNamespace(id=1, role="agent", agent_id=None)

    result = await get_accessible_owner_ids(db, actor=actor)

    assert result == []


@pytest.mark.asyncio
async def test_get_accessible_owner_ids_agent_returns_assigned_owners():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_RowsResult([(11,), (12,)]))
    actor = SimpleNamespace(id=1, role="agent", agent_id=99)

    result = await get_accessible_owner_ids(db, actor=actor)

    assert result == [11, 12]


@pytest.mark.asyncio
async def test_get_accessible_owner_ids_regular_user_returns_self():
    db = AsyncMock()
    actor = SimpleNamespace(id=44, role="user", agent_id=None)

    result = await get_accessible_owner_ids(db, actor=actor)

    assert result == [44]


@pytest.mark.asyncio
async def test_can_access_visit_allows_assigned_agent():
    """The agent assigned to a visit can access it, without DB lookups."""
    db = AsyncMock()
    actor = SimpleNamespace(id=2, role="agent", agent_id=50)

    result = await can_access_visit(
        db,
        actor=actor,
        visit_user_id=10,
        visit_property_id=20,
        visit_agent_id=50,
    )

    assert result is True
    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_can_access_visit_rejects_unassigned_agent():
    """An agent not linked to the user, owner, or visit assignment is denied."""
    db = AsyncMock()
    # visit user (managed by agent 99), property, owner (managed by agent 77)
    db.get = AsyncMock(
        side_effect=[
            SimpleNamespace(id=10, agent_id=99),
            SimpleNamespace(id=20, owner_id=30),
            SimpleNamespace(id=30, agent_id=77),
        ]
    )
    actor = SimpleNamespace(id=2, role="agent", agent_id=55)

    result = await can_access_visit(
        db,
        actor=actor,
        visit_user_id=10,
        visit_property_id=20,
        visit_agent_id=50,  # assigned to a different agent
    )

    assert result is False
