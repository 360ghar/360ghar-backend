from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.agents import Agent
from app.models.enums import AgentType, ExperienceLevel, PropertyPurpose, PropertyType, UserRole
from app.models.properties import Property, Visit
from app.models.users import User

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="pagination_admin@example.com",
        phone="+919100000099",
        full_name="Pagination Admin",
        role=UserRole.admin.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def regular_user(db_session) -> User:
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="pagination_user@example.com",
        phone="+919100000098",
        full_name="Pagination User",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_client(test_app, admin_user) -> AsyncClient:
    """Authenticated client wired to admin_user."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_admin,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(admin_user, from_attributes=True)

    async def override_get_current_user() -> UserSchema:
        return user_schema

    async def override_get_current_active_user() -> UserSchema:
        return user_schema

    async def override_get_current_user_optional() -> UserSchema:
        return user_schema

    async def override_get_current_admin() -> UserSchema:
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional
    test_app.dependency_overrides[get_current_admin] = override_get_current_admin

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user_client(test_app, regular_user) -> AsyncClient:
    """Authenticated client wired to regular_user."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(regular_user, from_attributes=True)

    async def override_get_current_user() -> UserSchema:
        return user_schema

    async def override_get_current_active_user() -> UserSchema:
        return user_schema

    async def override_get_current_user_optional() -> UserSchema:
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def three_agents(db_session) -> list[Agent]:
    """Seed 3 active agents."""
    agents = []
    for i in range(3):
        agent = Agent(
            name=f"Pagination Agent {i}",
            contact_number=f"+9192000000{i}",
            agent_type=AgentType.general,
            experience_level=ExperienceLevel.intermediate,
            is_active=True,
            is_available=True,
            total_users_assigned=0,
            user_satisfaction_rating=4.0,
            working_hours={"start": "09:00", "end": "18:00", "timezone": "UTC"},
            languages=["english"],
        )
        db_session.add(agent)
        await db_session.flush()
        await db_session.refresh(agent)
        agents.append(agent)
    return agents


@pytest_asyncio.fixture
async def three_users(db_session) -> list[User]:
    """Seed 3 regular users."""
    users = []
    for i in range(3):
        user = User(
            supabase_user_id=str(uuid.uuid4()),
            email=f"pg_testuser_{i}@example.com",
            phone=f"+9199900000{i}",
            full_name=f"PG Test User {i}",
            role=UserRole.user.value,
            is_active=True,
            is_verified=True,
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
        users.append(user)
    return users


@pytest_asyncio.fixture
async def agent_with_three_visits(db_session, three_agents) -> tuple[Agent, list[Visit]]:
    """Seed an agent with 3 visits."""
    agent = three_agents[0]
    prop_user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="visit_user_pg@example.com",
        phone="+919880000099",
        full_name="Visit User PG",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(prop_user)
    await db_session.flush()
    await db_session.refresh(prop_user)

    prop = Property(
        title="Visit Test Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=10000,
        owner_id=prop_user.id,
    )
    db_session.add(prop)
    await db_session.flush()
    await db_session.refresh(prop)

    visits = []
    base_date = datetime.now(timezone.utc) + timedelta(days=10)
    for i in range(3):
        visit = Visit(
            user_id=prop_user.id,
            property_id=prop.id,
            agent_id=agent.id,
            scheduled_date=base_date + timedelta(days=i),
            status="scheduled",
        )
        db_session.add(visit)
        await db_session.flush()
        await db_session.refresh(visit)
        visits.append(visit)
    return agent, visits


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/agents (admin — list all agents)
# ---------------------------------------------------------------------------


async def test_agents_list_cursor_paginates(admin_client: AsyncClient, three_agents: list[Agent]) -> None:
    r1 = await admin_client.get("/api/v1/agents?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"] is not None

    r2 = await admin_client.get(f"/api/v1/agents?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
    assert body2["has_more"] is False


async def test_agents_list_include_total(admin_client: AsyncClient, three_agents: list[Agent]) -> None:
    r = await admin_client.get("/api/v1/agents?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_agents_list_invalid_cursor(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/api/v1/agents?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/agents/available
# ---------------------------------------------------------------------------


async def test_available_agents_cursor_paginates(user_client: AsyncClient, three_agents: list[Agent]) -> None:
    r1 = await user_client.get("/api/v1/agents/available?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True

    r2 = await user_client.get(f"/api/v1/agents/available?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_available_agents_include_total(user_client: AsyncClient, three_agents: list[Agent]) -> None:
    r = await user_client.get("/api/v1/agents/available?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_available_agents_invalid_cursor(user_client: AsyncClient) -> None:
    r = await user_client.get("/api/v1/agents/available?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/users (admin)
# ---------------------------------------------------------------------------


async def test_users_list_cursor_paginates(admin_client: AsyncClient, three_users: list[User]) -> None:
    r1 = await admin_client.get("/api/v1/users?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"] is not None

    r2 = await admin_client.get(f"/api/v1/users?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
    assert body2["has_more"] is False


async def test_users_list_include_total(admin_client: AsyncClient, three_users: list[User]) -> None:
    r = await admin_client.get("/api/v1/users?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_users_list_invalid_cursor(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/api/v1/users?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


@pytest_asyncio.fixture
async def mixed_users(db_session, three_agents) -> list[User]:
    """Seed users covering the is_active / phone_verified / unassigned axes."""
    users = []
    specs = [
        # (unassigned, active, phone_verified)
        (True, True, True),
        (True, True, False),
        (False, True, True),
        (True, False, False),
    ]
    for i, (unassigned, active, phone_verified) in enumerate(specs):
        user = User(
            supabase_user_id=str(uuid.uuid4()),
            email=f"pg_mixed_{i}@example.com",
            phone=f"+9197700000{i}",
            full_name=f"PG Mixed User {i}",
            role=UserRole.user.value,
            is_active=active,
            is_verified=True,
            phone_verified=phone_verified,
            agent_id=None if unassigned else three_agents[0].id,
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
        users.append(user)
    return users


async def test_users_list_filter_unassigned(admin_client: AsyncClient, mixed_users: list[User]) -> None:
    """?unassigned=true must only return users with no assigned agent."""
    r = await admin_client.get("/api/v1/users?unassigned=true&limit=50")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert all(item["agent_id"] is None for item in items)
    unassigned_ids = {u.id for u in mixed_users if u.agent_id is None}
    returned_ids = {item["id"] for item in items}
    assert unassigned_ids <= returned_ids


async def test_users_list_filter_is_active(admin_client: AsyncClient, mixed_users: list[User]) -> None:
    """?is_active=true must only return active users."""
    r = await admin_client.get("/api/v1/users?is_active=true&limit=50")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert all(item["is_active"] is True for item in items)
    inactive = next(u for u in mixed_users if not u.is_active)
    assert inactive.id not in {item["id"] for item in items}


async def test_users_list_filter_phone_verified(admin_client: AsyncClient, mixed_users: list[User]) -> None:
    """?phone_verified=true must only return phone-verified users."""
    r = await admin_client.get("/api/v1/users?phone_verified=true&limit=50")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert all(item["phone_verified"] is True for item in items)
    verified_ids = {u.id for u in mixed_users if u.phone_verified}
    returned_ids = {item["id"] for item in items}
    assert verified_ids <= returned_ids


async def test_users_list_filter_combined(admin_client: AsyncClient, mixed_users: list[User]) -> None:
    """Filters combine with include_total for exact counts."""
    r = await admin_client.get(
        "/api/v1/users?unassigned=true&is_active=true&phone_verified=true&include_total=true&limit=1"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Exactly one seeded user matches all three filters (the admin fixture
    # user is active+unassigned but not phone_verified).
    assert body["total"] == 1
    assert body["items"][0]["id"] == next(u for u in mixed_users if u.agent_id is None and u.is_active and u.phone_verified).id


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/agents/{agent_id}/visits
# ---------------------------------------------------------------------------


async def test_agent_visits_cursor_paginates(admin_client: AsyncClient, agent_with_three_visits) -> None:
    agent, visits = agent_with_three_visits
    r1 = await admin_client.get(f"/api/v1/agents/{agent.id}/visits?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True

    r2 = await admin_client.get(f"/api/v1/agents/{agent.id}/visits?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_agent_visits_include_total(admin_client: AsyncClient, agent_with_three_visits) -> None:
    agent, visits = agent_with_three_visits
    r = await admin_client.get(f"/api/v1/agents/{agent.id}/visits?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_agent_visits_invalid_cursor(admin_client: AsyncClient, three_agents: list[Agent]) -> None:
    agent = three_agents[0]
    r = await admin_client.get(f"/api/v1/agents/{agent.id}/visits?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
