"""Cursor-pagination integration tests for flatmates list endpoints.

Tests run against a real test DB (via db_session / test_app / client fixtures
from tests/conftest.py).  Each test seeds its own rows and relies on the
function-scoped transaction-rollback fixture for isolation.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import (
    FlatmatesProfileStatus,
    PropertyPurpose,
    PropertyType,
    SwipeAction,
    SwipeTargetType,
    UserMatchStatus,
    UserReportReason,
    UserReportStatus,
    UserRole,
)
from app.models.properties import Property
from app.models.social import UserMatch, UserReport
from app.models.users import User, UserSwipe

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(suffix: str, *, flatmates: bool = False) -> User:
    return User(
        supabase_user_id=str(uuid.uuid4()),
        email=f"test_{suffix}@example.com",
        phone=f"+91{abs(hash(suffix)) % 9_000_000_000 + 1_000_000_000}",
        full_name=f"Test {suffix}",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
        flatmates_onboarding_completed=flatmates,
        flatmates_profile_status=FlatmatesProfileStatus.active if flatmates else None,
        flatmates_city="Bengaluru" if flatmates else None,
    )


def _make_admin_user(suffix: str) -> User:
    return User(
        supabase_user_id=str(uuid.uuid4()),
        email=f"admin_{suffix}@example.com",
        phone=f"+91{abs(hash('admin' + suffix)) % 9_000_000_000 + 1_000_000_000}",
        full_name=f"Admin {suffix}",
        role=UserRole.admin.value,
        is_active=True,
        is_verified=True,
    )


async def _flush_refresh(db_session, *objs: Any) -> None:
    for obj in objs:
        db_session.add(obj)
    await db_session.flush()
    for obj in objs:
        await db_session.refresh(obj)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def viewer_user(db_session) -> User:
    """Main authenticated user (the viewer / current_user)."""
    user = _make_user("viewer_flat", flatmates=True)
    await _flush_refresh(db_session, user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    user = _make_admin_user("pagination")
    await _flush_refresh(db_session, user)
    return user


@pytest_asyncio.fixture
async def flatmates_client(test_app, viewer_user) -> AsyncClient:
    """Authenticated ASGI client wired to viewer_user."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    schema = UserSchema.model_validate(viewer_user, from_attributes=True)

    async def _get_user() -> UserSchema:
        return schema

    test_app.dependency_overrides[get_current_user] = _get_user
    test_app.dependency_overrides[get_current_active_user] = _get_user
    test_app.dependency_overrides[get_current_user_optional] = _get_user

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(test_app, admin_user) -> AsyncClient:
    """Authenticated ASGI client wired to admin_user."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    schema = UserSchema.model_validate(admin_user, from_attributes=True)

    async def _get_user() -> UserSchema:
        return schema

    test_app.dependency_overrides[get_current_user] = _get_user
    test_app.dependency_overrides[get_current_active_user] = _get_user
    test_app.dependency_overrides[get_current_user_optional] = _get_user

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /flatmates/profiles  (offset-fallback)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def three_discoverable_users(db_session, viewer_user) -> list[User]:
    """Seed 3 flatmate users discoverable by viewer_user."""
    users = [_make_user(f"disc_{i}", flatmates=True) for i in range(3)]
    for u in users:
        db_session.add(u)
    await db_session.flush()
    for u in users:
        await db_session.refresh(u)
    return users


async def test_profiles_cursor_paginates(
    flatmates_client: AsyncClient,
    three_discoverable_users: list[User],
) -> None:
    r1 = await flatmates_client.get("/api/v1/flatmates/profiles?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await flatmates_client.get(
        f"/api/v1/flatmates/profiles?limit=2&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"


async def test_profiles_include_total(
    flatmates_client: AsyncClient,
    three_discoverable_users: list[User],
) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/profiles?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 3


async def test_profiles_invalid_cursor_400(flatmates_client: AsyncClient) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/profiles?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# GET /flatmates/matches  (keyset desc on created_at)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def three_matches(db_session, viewer_user) -> list[UserMatch]:
    """Seed 3 active matches for viewer_user."""
    peers = [_make_user(f"peer_match_{i}", flatmates=True) for i in range(3)]
    for p in peers:
        db_session.add(p)
    await db_session.flush()
    for p in peers:
        await db_session.refresh(p)

    matches = []
    for peer in peers:
        u1, u2 = (viewer_user.id, peer.id) if viewer_user.id < peer.id else (peer.id, viewer_user.id)
        match = UserMatch(
            user_one_id=u1,
            user_two_id=u2,
            status=UserMatchStatus.active,
        )
        db_session.add(match)
        await db_session.flush()
        await db_session.refresh(match)
        matches.append(match)
    return matches


async def test_matches_cursor_paginates(
    flatmates_client: AsyncClient,
    three_matches: list[UserMatch],
) -> None:
    r1 = await flatmates_client.get("/api/v1/flatmates/matches?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await flatmates_client.get(
        f"/api/v1/flatmates/matches?limit=2&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"


async def test_matches_include_total(
    flatmates_client: AsyncClient,
    three_matches: list[UserMatch],
) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/matches?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 3


async def test_matches_invalid_cursor_400(flatmates_client: AsyncClient) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/matches?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# GET /flatmates/likes  (incoming likes; keyset desc on created_at)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def three_incoming_likes(db_session, viewer_user) -> list[UserSwipe]:
    """Seed 3 incoming likes targeting viewer_user."""
    likers = [_make_user(f"liker_{i}", flatmates=True) for i in range(3)]
    for lk in likers:
        db_session.add(lk)
    await db_session.flush()
    for lk in likers:
        await db_session.refresh(lk)

    swipes = []
    for liker in likers:
        swipe = UserSwipe(
            user_id=liker.id,
            target_user_id=viewer_user.id,
            target_type=SwipeTargetType.user.value,
            swipe_action=SwipeAction.like.value,
            is_liked=True,
        )
        db_session.add(swipe)
        await db_session.flush()
        await db_session.refresh(swipe)
        swipes.append(swipe)
    return swipes


async def test_likes_cursor_paginates(
    flatmates_client: AsyncClient,
    three_incoming_likes: list[UserSwipe],
) -> None:
    r1 = await flatmates_client.get("/api/v1/flatmates/likes?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await flatmates_client.get(
        f"/api/v1/flatmates/likes?limit=2&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"


async def test_likes_include_total(
    flatmates_client: AsyncClient,
    three_incoming_likes: list[UserSwipe],
) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/likes?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 3


async def test_likes_invalid_cursor_400(flatmates_client: AsyncClient) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/likes?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# GET /flatmates/outgoing-likes  (outgoing likes; keyset desc on created_at)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def three_outgoing_likes(db_session, viewer_user) -> list[UserSwipe]:
    """Seed 3 outgoing likes FROM viewer_user to three distinct targets."""
    targets = [_make_user(f"target_{i}", flatmates=True) for i in range(3)]
    for t in targets:
        db_session.add(t)
    await db_session.flush()
    for t in targets:
        await db_session.refresh(t)

    swipes = []
    for target in targets:
        swipe = UserSwipe(
            user_id=viewer_user.id,
            target_user_id=target.id,
            target_type=SwipeTargetType.user.value,
            swipe_action=SwipeAction.like.value,
            is_liked=True,
        )
        db_session.add(swipe)
        await db_session.flush()
        await db_session.refresh(swipe)
        swipes.append(swipe)
    return swipes


async def test_outgoing_likes_cursor_paginates(
    flatmates_client: AsyncClient,
    three_outgoing_likes: list[UserSwipe],
) -> None:
    r1 = await flatmates_client.get("/api/v1/flatmates/outgoing-likes?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await flatmates_client.get(
        f"/api/v1/flatmates/outgoing-likes?limit=2&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None


async def test_outgoing_likes_include_total(
    flatmates_client: AsyncClient,
    three_outgoing_likes: list[UserSwipe],
) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/outgoing-likes?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3


async def test_outgoing_likes_invalid_cursor_400(flatmates_client: AsyncClient) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/outgoing-likes?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# GET /flatmates-admin/moderation/listings  (keyset asc on created_at)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def three_pending_listings(db_session, admin_user) -> list[Property]:
    """Seed 3 pending-review flatmate listings owned by admin_user."""
    listings = []
    for i in range(3):
        prop = Property(
            title=f"Pagination Listing {i}",
            property_type=PropertyType.flatmate,
            purpose=PropertyPurpose.rent,
            base_price=10000 + i * 1000,
            owner_id=admin_user.id,
            is_available=True,
            listing_preferences={"moderation_status": "pending_review"},
        )
        db_session.add(prop)
        await db_session.flush()
        await db_session.refresh(prop)
        listings.append(prop)
    return listings


async def test_admin_listings_cursor_paginates(
    admin_client: AsyncClient,
    three_pending_listings: list[Property],
) -> None:
    r1 = await admin_client.get("/api/v1/flatmates/moderation/listings?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await admin_client.get(
        f"/api/v1/flatmates/moderation/listings?limit=2&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"


async def test_admin_listings_include_total(
    admin_client: AsyncClient,
    three_pending_listings: list[Property],
) -> None:
    r = await admin_client.get(
        "/api/v1/flatmates/moderation/listings?limit=2&include_total=true"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 3


async def test_admin_listings_invalid_cursor_400(admin_client: AsyncClient) -> None:
    r = await admin_client.get(
        "/api/v1/flatmates/moderation/listings?cursor=garbage!!!"
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# GET /flatmates-admin/moderation/reports  (keyset asc on created_at)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def three_open_reports(db_session, admin_user) -> list[UserReport]:
    """Seed 3 open user reports."""
    reporters = [_make_user(f"reporter_{i}") for i in range(3)]
    reporteds = [_make_user(f"reported_{i}") for i in range(3)]
    for u in reporters + reporteds:
        db_session.add(u)
    await db_session.flush()
    for u in reporters + reporteds:
        await db_session.refresh(u)

    reports = []
    for reporter, reported in zip(reporters, reporteds, strict=True):
        report = UserReport(
            reporter_user_id=reporter.id,
            reported_user_id=reported.id,
            reason=UserReportReason.spam,
            status=UserReportStatus.open,
        )
        db_session.add(report)
        await db_session.flush()
        await db_session.refresh(report)
        reports.append(report)
    return reports


async def test_admin_reports_cursor_paginates(
    admin_client: AsyncClient,
    three_open_reports: list[UserReport],
) -> None:
    r1 = await admin_client.get("/api/v1/flatmates/moderation/reports?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await admin_client.get(
        f"/api/v1/flatmates/moderation/reports?limit=2&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "Pages must not overlap"


async def test_admin_reports_include_total(
    admin_client: AsyncClient,
    three_open_reports: list[UserReport],
) -> None:
    r = await admin_client.get(
        "/api/v1/flatmates/moderation/reports?limit=2&include_total=true"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 3


async def test_admin_reports_invalid_cursor_400(admin_client: AsyncClient) -> None:
    r = await admin_client.get(
        "/api/v1/flatmates/moderation/reports?cursor=garbage!!!"
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
