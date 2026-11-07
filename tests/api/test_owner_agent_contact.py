"""The listing contact a non-owner sees in list, detail and visit responses.

A guest sees the company number. A signed-in viewer sees their own relationship
manager (users.agent_id), never the owner's agent and never the owner's number.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
    get_current_user_optional,
)
from app.config import settings
from app.models.enums import UserRole
from app.services.property import load_viewer
from tests.fixtures.factories import AgentFactory, PropertyFactory, UserFactory, VisitFactory

pytestmark = pytest.mark.asyncio

OWNER_AGENT_CONTACT = "+919111111111"
VIEWER_MANAGER_CONTACT = "+919222222222"
OWNER_CONTACT = "+919000000000"
COMPANY_CONTACT = "+918000000000"


@pytest.fixture(autouse=True)
def _company_number(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", COMPANY_CONTACT)


@pytest.fixture(autouse=True)
def _no_list_cache(monkeypatch):
    """The property list is cached by its filters. A shared Redis would serve the page of an
    earlier test, which does not hold this test's new property, and would keep this test's
    rolled-back rows for the next one. Reads and writes are both off."""
    monkeypatch.setattr(
        "app.services.property.search.PropertyCacheManager.get_cached_properties",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.property.search.PropertyCacheManager.cache_properties",
        AsyncMock(return_value=None),
    )


async def _listing(db_session):
    """A listing whose owner has their own agent, which no other viewer may see."""
    owner_agent = await AgentFactory.create(db_session, contact_number=OWNER_AGENT_CONTACT)
    owner = await UserFactory.create(db_session, agent_id=owner_agent.id)
    return await PropertyFactory.create(db_session, owner=owner, owner_contact=OWNER_CONTACT)


async def _list_and_detail(client: AsyncClient, prop_id: int) -> tuple[dict, dict]:
    listed = await client.get("/api/v1/properties/")
    detail = await client.get(f"/api/v1/properties/{prop_id}")
    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    row = next(item for item in listed.json()["items"] if item["id"] == prop_id)
    return row, detail.json()


async def test_guest_sees_the_company_number_and_no_agent(client: AsyncClient, db_session):
    prop = await _listing(db_session)

    row, detail = await _list_and_detail(client, prop.id)

    assert row["owner_contact"] == COMPANY_CONTACT
    assert detail["owner_contact"] == COMPANY_CONTACT
    assert detail["agent"] is None


@pytest.mark.parametrize(
    ("manager_active", "expected"),
    [(True, VIEWER_MANAGER_CONTACT), (False, COMPANY_CONTACT)],
    ids=["active-manager", "inactive-manager-uses-company-number"],
)
async def test_signed_in_viewer_sees_their_own_manager(
    test_app, client: AsyncClient, db_session, manager_active, expected
):
    prop = await _listing(db_session)
    manager = await AgentFactory.create(
        db_session, contact_number=VIEWER_MANAGER_CONTACT, is_active=manager_active
    )
    viewer = await UserFactory.create(db_session, agent_id=manager.id)
    test_app.dependency_overrides[get_current_user_optional] = lambda: viewer

    row, detail = await _list_and_detail(client, prop.id)

    assert row["owner_contact"] == expected
    assert detail["owner_contact"] == expected
    if manager_active:
        assert detail["agent"]["id"] == manager.id
        assert detail["agent"]["contact_number"] == VIEWER_MANAGER_CONTACT
    else:
        assert detail["agent"] is None
    assert OWNER_AGENT_CONTACT not in str(detail)


async def test_visit_list_and_detail_show_the_visitors_manager(
    test_app, client: AsyncClient, db_session
):
    prop = await _listing(db_session)
    manager = await AgentFactory.create(db_session, contact_number=VIEWER_MANAGER_CONTACT)
    visitor = await UserFactory.create(db_session, agent_id=manager.id)
    visit = await VisitFactory.create(db_session, user=visitor, property_obj=prop)

    viewer = SimpleNamespace(id=visitor.id, role="user", agent_id=manager.id, is_active=True)
    test_app.dependency_overrides[get_current_cached_active_user] = lambda: viewer

    listed = await client.get("/api/v1/visits")
    detail = await client.get(f"/api/v1/visits/{visit.id}")

    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    row = next(item for item in listed.json()["items"] if item["id"] == visit.id)
    assert row["property"]["owner_contact"] == VIEWER_MANAGER_CONTACT
    assert detail.json()["property"]["owner_contact"] == VIEWER_MANAGER_CONTACT


async def test_manager_comes_from_the_current_assignment_not_the_auth_snapshot(
    test_app, client: AsyncClient, db_session
):
    prop = await _listing(db_session)
    old = await AgentFactory.create(db_session, contact_number="+919333333333")
    new = await AgentFactory.create(db_session, contact_number=VIEWER_MANAGER_CONTACT)
    visitor = await UserFactory.create(db_session, agent_id=new.id)
    visit = await VisitFactory.create(db_session, user=visitor, property_obj=prop)

    # The cached snapshot still names the old manager.
    snapshot = SimpleNamespace(id=visitor.id, role="user", agent_id=old.id, is_active=True)
    test_app.dependency_overrides[get_current_cached_active_user] = lambda: snapshot

    detail = await client.get(f"/api/v1/visits/{visit.id}")

    assert detail.status_code == 200, detail.text
    assert detail.json()["property"]["owner_contact"] == VIEWER_MANAGER_CONTACT


async def test_a_failed_manager_lookup_falls_back_and_keeps_the_session(db_session, monkeypatch):
    manager = await AgentFactory.create(db_session, contact_number=VIEWER_MANAGER_CONTACT)
    user = await UserFactory.create(db_session, agent_id=manager.id)
    real_execute = db_session.execute

    async def failing_execute(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("connection reset"))

    monkeypatch.setattr(db_session, "execute", failing_execute)
    viewer = await load_viewer(db_session, user)
    monkeypatch.setattr(db_session, "execute", real_execute)

    assert viewer.manager is None
    assert viewer.id == user.id
    # The savepoint rolled back; the request's transaction still works.
    assert (await db_session.execute(text("SELECT 1"))).scalar() == 1


async def test_agent_sees_the_owners_agent_on_the_pm_detail(
    test_app, client: AsyncClient, db_session
):
    owner_agent = await AgentFactory.create(db_session, contact_number=OWNER_AGENT_CONTACT)
    owner = await UserFactory.create(db_session, agent_id=owner_agent.id)
    prop = await PropertyFactory.create(
        db_session, owner=owner, owner_contact=OWNER_CONTACT, is_managed=True
    )
    agent_user = await UserFactory.create(
        db_session, role=UserRole.agent.value, agent_id=owner_agent.id
    )
    test_app.dependency_overrides[get_current_active_user] = lambda: agent_user

    detail = await client.get(f"/api/v1/pm/properties/{prop.id}")

    assert detail.status_code == 200, detail.text
    assert detail.json()["property"]["owner_contact"] == OWNER_AGENT_CONTACT
