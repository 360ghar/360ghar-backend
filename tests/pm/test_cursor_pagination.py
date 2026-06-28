"""Cursor-pagination integration tests for tours, upload/media, swipes and pm/dashboard/activity.

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

from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType, TourStatus, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.tours import MediaFile, Tour
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
# Fixtures for tours and upload/media
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tour_owner(db_session) -> User:
    """A user who owns tours."""
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="tour_cursor_owner@example.com",
        phone="+919200000003",
        full_name="Tour Cursor Owner",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def tour_client(test_app, tour_owner) -> AsyncClient:
    """Authenticated client wired to tour_owner."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(tour_owner, from_attributes=True)

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
async def seeded_tours(db_session, tour_owner) -> list[Tour]:
    """Create 3 draft tours for tour_owner."""
    tours = []
    for i in range(3):
        tour = Tour(
            id=str(uuid.uuid4()),
            user_id=tour_owner.id,
            title=f"Cursor Tour {i}",
            status=TourStatus.draft,
            is_public=False,
        )
        db_session.add(tour)
        await db_session.flush()
        await db_session.refresh(tour)
        tours.append(tour)
    return tours


@pytest_asyncio.fixture
async def seeded_media(db_session, tour_owner) -> list[MediaFile]:
    """Create 3 media files for tour_owner."""
    files = []
    for i in range(3):
        mf = MediaFile(
            user_id=tour_owner.id,
            filename=f"cursor_file_{i}.jpg",
            file_url=f"https://example.com/cursor_file_{i}.jpg",
            file_size=1024 * (i + 1),
            mime_type="image/jpeg",
            folder="uploads",
            visibility="private",
            upload_status="complete",
        )
        db_session.add(mf)
        await db_session.flush()
        await db_session.refresh(mf)
        files.append(mf)
    return files


# ---------------------------------------------------------------------------
# Tours endpoint tests
# ---------------------------------------------------------------------------


async def test_tours_cursor_paginates(
    tour_client: AsyncClient,
    seeded_tours: list[Tour],
) -> None:
    """Page-walk: limit=2, 3 rows → page1 has_more=True, no ID overlap."""
    r1 = await tour_client.get("/api/v1/tours?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await tour_client.get(f"/api/v1/tours?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "ID overlap across pages"
    # Walk to terminal
    if body2.get("next_cursor"):
        r3 = await tour_client.get(f"/api/v1/tours?limit=2&cursor={body2['next_cursor']}")
        assert r3.status_code == 200, r3.text
        assert r3.json()["has_more"] is False


async def test_tours_include_total(
    tour_client: AsyncClient,
    seeded_tours: list[Tour],
) -> None:
    """include_total=true returns total >= 3."""
    r = await tour_client.get("/api/v1/tours?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert body["total"] >= 3


async def test_tours_invalid_cursor_400(tour_client: AsyncClient) -> None:
    """Garbage cursor → 400 with INVALID_CURSOR error code."""
    r = await tour_client.get("/api/v1/tours?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Upload/media endpoint tests
# ---------------------------------------------------------------------------


async def test_media_cursor_paginates(
    tour_client: AsyncClient,
    seeded_media: list[MediaFile],
) -> None:
    """Page-walk: limit=2, 3 rows → page1 has_more=True, no ID overlap."""
    r1 = await tour_client.get("/api/v1/upload/media?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await tour_client.get(f"/api/v1/upload/media?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "ID overlap across pages"
    if body2.get("next_cursor"):
        r3 = await tour_client.get(f"/api/v1/upload/media?limit=2&cursor={body2['next_cursor']}")
        assert r3.status_code == 200, r3.text
        assert r3.json()["has_more"] is False


async def test_media_include_total(
    tour_client: AsyncClient,
    seeded_media: list[MediaFile],
) -> None:
    """include_total=true returns total >= 3."""
    r = await tour_client.get("/api/v1/upload/media?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert body["total"] >= 3


async def test_media_invalid_cursor_400(tour_client: AsyncClient) -> None:
    """Garbage cursor → 400 with INVALID_CURSOR error code."""
    r = await tour_client.get("/api/v1/upload/media?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


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


async def test_pm_activity_include_total_not_capped(
    pm_client: AsyncClient,
    db_session,
    pm_owner: User,
) -> None:
    """include_total must reflect the true per-source SQL count, not the
    fetch_limit cap (offset + limit + 1).  With limit=2 the old code would
    cap at fetch_limit = 0+2+1 = 3 rows per source; adding 4 leases means the
    merged count from lease source alone exceeds that cap.  The real total
    should be >= 4 leases (no payments or maintenance requests seeded here).
    """
    today = date.today()
    for i in range(4):
        prop = Property(
            title=f"PM Total Cap Property {i}",
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
            tenant_name=f"Cap Tenant {i}",
            tenant_phone=f"+9130000000{i}",
            status=LeaseStatus.active,
            start_date=today - timedelta(days=10 + i),
            end_date=today + timedelta(days=350 - i),
            monthly_rent=21000.0 + i * 500,
            security_deposit=42000.0,
            grace_period_days=5,
            payment_due_day=1,
        )
        db_session.add(lease)
        await db_session.flush()

    r = await pm_client.get("/api/v1/pm/dashboard/activity?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    # With 4 leases and limit=2, the old cap would have returned 3 (fetch_limit).
    # The correct per-source count must return >= 4.
    assert body["total"] >= 4, (
        f"total={body['total']} appears capped at fetch_limit instead of returning real count"
    )


async def test_tours_list_no_scenes_field(
    tour_client: AsyncClient,
    seeded_tours: list[Tour],
) -> None:
    """GET /tours list items must NOT include a 'scenes' key (old contract)."""
    r = await tour_client.get("/api/v1/tours?limit=3")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert len(body["items"]) > 0
    for item in body["items"]:
        assert "scenes" not in item, (
            f"Tour list item should not expose 'scenes' but got keys: {list(item.keys())}"
        )
