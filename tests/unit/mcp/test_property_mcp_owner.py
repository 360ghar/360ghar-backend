"""User MCP owner tools for one listing, against real rows.

- owner_properties_get masks the owner's number by viewer. The owner sees the owner's
  number. A tenant with an active lease sees the assigned agent's number, or the company
  number when no agent is assigned. An anonymous caller gets no data.
- owner_properties_update uses the same field rules and access checks as PUT
  /properties/{id}: base_price cap, non-negative rent, rent kept positive, owner-only.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.mcp.apps_sdk import AuthRequiredError
from app.models.agents import Agent
from app.models.enums import (
    AgentType,
    ExperienceLevel,
    LeaseStatus,
    PropertyPurpose,
    PropertyType,
    UserRole,
)
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User

pytestmark = pytest.mark.asyncio

OWNER_NUMBER = "9000000111"
AGENT_NUMBER = "9000000001"
COMPANY_NUMBER = "9000000999"


async def _gen(db):
    yield db


@pytest.fixture
def company_number(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", COMPANY_NUMBER)
    return COMPANY_NUMBER


@pytest.fixture
async def listing(db_session):
    """An owner with an assigned agent, a tenant on an active lease, and one listing."""
    agent = Agent(
        name="RM",
        contact_number=AGENT_NUMBER,
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.beginner,
        is_active=True,
        is_available=True,
    )
    db_session.add(agent)
    await db_session.flush()

    def _user(name, role, agent_id, n):
        return User(
            supabase_user_id=f"mcp-mask-{n}",
            phone=f"+9188811100{n:02d}",
            full_name=name,
            role=role,
            agent_id=agent_id,
            is_active=True,
            is_verified=True,
        )

    owner = _user("Owner", UserRole.user.value, agent.id, 1)
    tenant = _user("Tenant", UserRole.user.value, None, 2)
    db_session.add_all([owner, tenant])
    await db_session.flush()

    prop = Property(
        title="Masked flat",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=25000,
        monthly_rent=25000,
        owner_id=owner.id,
        is_managed=True,
        owner_contact=OWNER_NUMBER,
        latitude=12.97,
        longitude=77.59,
    )
    db_session.add(prop)
    await db_session.flush()

    lease = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=25000,
        security_deposit=50000,
        payment_due_day=1,
        grace_period_days=5,
    )
    db_session.add(lease)
    await db_session.flush()
    return {"owner": owner, "tenant": tenant, "property": prop}


async def _owner_properties_get(db, user, property_id):
    from app.mcp.user.owner import owner_properties_get

    with (
        patch("app.mcp.user.owner.get_db", return_value=_gen(db)),
        patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
    ):
        return await owner_properties_get(property_id=property_id)


async def test_owner_sees_the_owner_number(db_session, listing, company_number):
    result = await _owner_properties_get(db_session, listing["owner"], listing["property"].id)

    assert result["ok"] is True
    assert result["data"]["property"]["owner_phone"] == OWNER_NUMBER


async def test_tenant_with_active_lease_sees_the_agent_number_not_the_owner_number(
    db_session, listing, company_number
):
    result = await _owner_properties_get(db_session, listing["tenant"], listing["property"].id)

    assert result["ok"] is True
    assert result["data"]["property"]["owner_phone"] == AGENT_NUMBER
    assert OWNER_NUMBER not in str(result)


async def test_tenant_sees_the_company_number_when_the_owner_has_no_agent(
    db_session, listing, company_number
):
    listing["owner"].agent_id = None
    await db_session.flush()

    result = await _owner_properties_get(db_session, listing["tenant"], listing["property"].id)

    assert result["data"]["property"]["owner_phone"] == COMPANY_NUMBER


async def test_anonymous_caller_gets_no_property_data(db_session, listing, company_number):
    from app.mcp.user.owner import owner_properties_get

    with (
        patch("app.mcp.user.owner.get_db", return_value=_gen(db_session)),
        patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=None)),
        pytest.raises(AuthRequiredError),
    ):
        await owner_properties_get(property_id=listing["property"].id)


async def _owner_properties_update(db, user, property_id, **fields):
    from app.mcp.user.owner import owner_properties_update

    with (
        patch("app.mcp.user.owner.get_db", return_value=_gen(db)),
        patch("app.mcp.user.owner._get_user", new=AsyncMock(return_value=user)),
    ):
        return await owner_properties_update(property_id=property_id, **fields)


async def test_owner_update_applies_a_valid_change(db_session, listing):
    result = await _owner_properties_update(
        db_session, listing["owner"], listing["property"].id, title="Renamed flat"
    )

    assert result["ok"] is True, result
    assert result["data"]["property"]["title"] == "Renamed flat"


async def test_owner_update_rejects_a_base_price_above_the_cap(db_session, listing):
    result = await _owner_properties_update(
        db_session, listing["owner"], listing["property"].id, base_price=1e12
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_INPUT"
    await db_session.refresh(listing["property"])
    assert float(listing["property"].base_price) == 25000.0


async def test_owner_update_rejects_a_negative_rent(db_session, listing):
    result = await _owner_properties_update(
        db_session, listing["owner"], listing["property"].id, monthly_rent=-5
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_INPUT"


async def test_owner_update_keeps_a_rent_listing_rent_positive(db_session, listing):
    result = await _owner_properties_update(
        db_session, listing["owner"], listing["property"].id, monthly_rent=0
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_INPUT"


async def test_tenant_cannot_update_the_listing(db_session, listing):
    result = await _owner_properties_update(
        db_session, listing["tenant"], listing["property"].id, title="Tenant edit"
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
    await db_session.refresh(listing["property"])
    assert listing["property"].title == "Masked flat"


async def test_update_helper_ignores_keys_the_caller_left_as_none(db_session, listing):
    # The AI agent tool passes every key. None means not sent, so only title changes.
    from app.mcp.tool_ops import update_property_fields

    result = await update_property_fields(
        db_session,
        actor=listing["owner"],
        property_id=listing["property"].id,
        updates={
            "title": "Agent edit",
            "description": None,
            "base_price": None,
            "monthly_rent": None,
            "daily_rate": None,
            "is_available": None,
            "max_occupancy": None,
            "main_image_url": None,
        },
    )

    assert "error" not in result, result
    assert result["property"]["title"] == "Agent edit"
    await db_session.refresh(listing["property"])
    assert float(listing["property"].monthly_rent) == 25000.0
