"""Cursor-pagination integration tests for swipes and pm/dashboard/activity endpoints.

Each endpoint gets:
  - a page-walk test (limit=2, 3 seeded rows, has_more True, no overlap)
  - an include_total test (total == 3)
  - an invalid-cursor-400 test asserting error.code == "INVALID_CURSOR"
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User, UserSwipe

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def swipe_owner(db_session) -> User:
    """A user who will swipe on properties."""
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="swipe_cursor_owner@example.com",
        phone="+919200000001",
        full_name="Swipe Cursor Owner",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def pm_owner(db_session) -> User:
    """A user who acts as a PM portfolio owner."""
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="pm_cursor_owner@example.com",
        phone="+919200000002",
        full_name="PM Cursor Owner",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def swipe_client(test_app, swipe_owner) -> AsyncClient:
    """Authenticated client wired to swipe_owner."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(swipe_owner, from_attributes=True)

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
async def pm_client(test_app, pm_owner) -> AsyncClient:
    """Authenticated client wired to pm_owner."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(pm_owner, from_attributes=True)

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
async def seeded_swipes(db_session, swipe_owner) -> list[UserSwipe]:
    """Create 3 liked swipes for swipe_owner across 3 properties."""
    swipes = []
    for i in range(3):
        prop = Property(
            title=f"Swipe Cursor Property {i}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=20000 + i * 1000,
            owner_id=swipe_owner.id,
        )
        db_session.add(prop)
        await db_session.flush()

        swipe = UserSwipe(
            user_id=swipe_owner.id,
            property_id=prop.id,
            is_liked=True,
        )
        db_session.add(swipe)
        await db_session.flush()
        await db_session.refresh(swipe)
        swipes.append(swipe)

    return swipes


@pytest_asyncio.fixture
async def seeded_pm_leases(db_session, pm_owner) -> list[Lease]:
    """Create 3 leases owned by pm_owner for activity pagination tests."""
    leases = []
    today = date.today()

    for i in range(3):
        prop = Property(
            title=f"PM Cursor Activity Property {i}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=30000,
            owner_id=pm_owner.id,
            is_managed=True,
        )
        db_session.add(prop)
        await db_session.flush()

        lease = Lease(
            property_id=prop.id,
            owner_id=pm_owner.id,
            tenant_name=f"Cursor Tenant {i}",
            tenant_phone=f"+9120000000{i}",
            status=LeaseStatus.active,
            start_date=today - timedelta(days=30 + i),
            end_date=today + timedelta(days=335 - i),
            monthly_rent=20000.0 + i * 1000,
            security_deposit=40000.0,
            grace_period_days=5,
            payment_due_day=1,
        )
        db_session.add(lease)
        await db_session.flush()
        await db_session.refresh(lease)
        leases.append(lease)

    return leases


# ---------------------------------------------------------------------------
# Swipes endpoint tests
# ---------------------------------------------------------------------------


async def test_swipes_cursor_paginates(
    swipe_client: AsyncClient,
    seeded_swipes: list[UserSwipe],
) -> None:
    """Page-walk: limit=2, 3 rows → page1 has_more=True, no ID overlap."""
    r1 = await swipe_client.get("/api/v1/swipes?limit=2&is_liked=true")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await swipe_client.get(f"/api/v1/swipes?limit=2&is_liked=true&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "ID overlap across pages"

    # Terminal page should have no more
    if body2.get("next_cursor"):
        r3 = await swipe_client.get(f"/api/v1/swipes?limit=2&is_liked=true&cursor={body2['next_cursor']}")
        assert r3.status_code == 200, r3.text
        assert r3.json()["has_more"] is False


async def test_swipes_include_total(
    swipe_client: AsyncClient,
    seeded_swipes: list[UserSwipe],
) -> None:
    """include_total=true returns total >= 3."""
    r = await swipe_client.get("/api/v1/swipes?limit=2&is_liked=true&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert body["total"] >= 3


async def test_swipes_invalid_cursor_400(swipe_client: AsyncClient) -> None:
    """Garbage cursor → 400 with INVALID_CURSOR error code."""
    r = await swipe_client.get("/api/v1/swipes?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# PM dashboard activity endpoint tests
# ---------------------------------------------------------------------------


async def test_pm_activity_cursor_paginates(
    pm_client: AsyncClient,
    seeded_pm_leases: list[Lease],
) -> None:
    """Page-walk: limit=2, 3 lease rows → page1 has_more=True, no overlap."""
    r1 = await pm_client.get("/api/v1/pm/dashboard/activity?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/dashboard/activity?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()

    # Verify items are different positions in the list (page2 items not present in page1)
    # Use (type, lease_id) as identity — lease_id is unique per item
    def item_key(item: dict) -> tuple:
        return (item["type"], item.get("lease_id"), item.get("id"))

    keys1 = {item_key(item) for item in body1["items"]}
    keys2 = {item_key(item) for item in body2["items"]}
    assert keys1.isdisjoint(keys2), "Activity item overlap across pages"

    # Walk to terminal page
    if body2.get("next_cursor"):
        r3 = await pm_client.get(f"/api/v1/pm/dashboard/activity?limit=2&cursor={body2['next_cursor']}")
        assert r3.status_code == 200, r3.text
        assert r3.json()["has_more"] is False


async def test_pm_activity_include_total(
    pm_client: AsyncClient,
    seeded_pm_leases: list[Lease],
) -> None:
    """include_total=true returns total >= 3."""
    r = await pm_client.get("/api/v1/pm/dashboard/activity?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert body["total"] >= 3


async def test_pm_activity_invalid_cursor_400(pm_client: AsyncClient) -> None:
    """Garbage cursor → 400 with INVALID_CURSOR error code."""
    r = await pm_client.get("/api/v1/pm/dashboard/activity?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
