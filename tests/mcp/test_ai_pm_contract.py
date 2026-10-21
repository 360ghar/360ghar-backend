"""Owner dashboard tool payload and tenant lease lookup (be-ai-9, r2-widgets-mcp-1)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.chatgpt import pm_dashboard_tools
from app.mcp.tool_ops.leases import get_tenant_current_lease
from app.models.enums import LeaseStatus
from tests.pm.test_pm_contract_wave3 import _property, _user
from tests.pm.test_pm_round3_rent import _charge, _rent_lease

pytestmark = pytest.mark.asyncio


async def test_owner_dashboard_tool_emits_flat_keys_and_number_money(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    await _charge(db_session, owner, lease)

    @asynccontextmanager
    async def _session():
        yield db_session

    tool = pm_dashboard_tools.owner_dashboard_overview
    fn = getattr(tool, "fn", tool)
    with (
        patch.object(pm_dashboard_tools, "AsyncSessionLocal", _session),
        patch.object(pm_dashboard_tools, "_get_optional_user", AsyncMock(return_value=owner)),
    ):
        result = await fn()

    dash = result.structured_content["dashboard"]
    assert {
        "total_properties",
        "occupied_properties",
        "vacant_properties",
        "monthly_revenue_current",
        "outstanding_rent_total",
    } <= dash.keys()
    assert dash["total_properties"] >= 1
    for key in (
        "monthly_revenue_current",
        "monthly_revenue_previous",
        "outstanding_rent_total",
        "upcoming_expenses_total",
    ):
        assert isinstance(dash[key], float), key
        assert not isinstance(dash[key], Decimal)
    assert dash["outstanding_rent_total"] > 0


async def test_tenant_sees_expiring_soon_lease(db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1000.00", tenant=tenant)
    lease.status = LeaseStatus.expiring_soon
    await db_session.flush()

    result = await get_tenant_current_lease(db_session, tenant_user_id=tenant.id, viewer=tenant)

    assert result["lease"] is not None
    assert result["lease"]["id"] == lease.id
