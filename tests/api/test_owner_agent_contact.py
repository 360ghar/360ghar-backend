"""A non-owner sees the same contact for a listing in the list, detail and visit responses."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.api.api_v1.dependencies.auth import get_current_cached_active_user
from app.config import settings
from tests.fixtures.factories import AgentFactory, PropertyFactory, UserFactory, VisitFactory

pytestmark = pytest.mark.asyncio

AGENT_CONTACT = "+919111111111"
OWNER_CONTACT = "+919000000000"
COMPANY_CONTACT = "+918000000000"


@pytest.fixture(autouse=True)
def _company_number(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", COMPANY_CONTACT)


@pytest.mark.parametrize(
    ("agent_active", "expected"),
    [(True, AGENT_CONTACT), (False, COMPANY_CONTACT)],
    ids=["active-agent", "inactive-agent-uses-company-number"],
)
async def test_list_and_detail_show_the_same_non_owner_contact(
    client: AsyncClient, db_session, agent_active, expected
):
    agent = await AgentFactory.create(
        db_session, contact_number=AGENT_CONTACT, is_active=agent_active
    )
    owner = await UserFactory.create(db_session, agent_id=agent.id)
    prop = await PropertyFactory.create(db_session, owner=owner, owner_contact=OWNER_CONTACT)

    listed = await client.get("/api/v1/properties/")
    detail = await client.get(f"/api/v1/properties/{prop.id}")

    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    row = next(item for item in listed.json()["items"] if item["id"] == prop.id)
    assert row["owner_contact"] == expected
    assert detail.json()["owner_contact"] == expected


async def test_visit_list_and_detail_show_the_agent_contact_to_the_visitor(
    test_app, client: AsyncClient, db_session
):
    agent = await AgentFactory.create(db_session, contact_number=AGENT_CONTACT)
    owner = await UserFactory.create(db_session, agent_id=agent.id)
    visitor = await UserFactory.create(db_session)
    prop = await PropertyFactory.create(db_session, owner=owner, owner_contact=OWNER_CONTACT)
    visit = await VisitFactory.create(db_session, user=visitor, property_obj=prop)

    viewer = SimpleNamespace(id=visitor.id, role="user", agent_id=None, is_active=True)
    test_app.dependency_overrides[get_current_cached_active_user] = lambda: viewer

    listed = await client.get("/api/v1/visits")
    detail = await client.get(f"/api/v1/visits/{visit.id}")

    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    row = next(item for item in listed.json()["items"] if item["id"] == visit.id)
    assert row["property"]["owner_contact"] == AGENT_CONTACT
    assert detail.json()["property"]["owner_contact"] == AGENT_CONTACT
