"""Cursor-pagination integration tests for flatmates list endpoints.

Tests run against a real test DB (via db_session / test_app / client fixtures
from tests/conftest.py).  Each test seeds its own rows and relies on the
function-scoped transaction-rollback fixture for isolation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.models.agents import Agent
from app.models.enums import (
    AgentType,
    ExperienceLevel,
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
from app.models.social import UserBlock, UserMatch, UserReport
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
        get_current_cached_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema
    from app.services.auth_user_cache import snapshot_from_user

    schema = UserSchema.model_validate(viewer_user, from_attributes=True)
    snapshot = snapshot_from_user(viewer_user)

    async def _get_user() -> UserSchema:
        return schema

    async def _get_cached_user():
        return snapshot

    test_app.dependency_overrides[get_current_user] = _get_user
    test_app.dependency_overrides[get_current_active_user] = _get_user
    test_app.dependency_overrides[get_current_user_optional] = _get_user
    test_app.dependency_overrides[get_current_cached_active_user] = _get_cached_user

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


async def test_discovery_gender_preference_filters_candidates(
    db_session, viewer_user, flatmates_client: AsyncClient
) -> None:
    male = _make_user(f"gender_m_{uuid.uuid4().hex[:6]}", flatmates=True)
    male.preferences = {"flatmates": {"gender": "male"}}
    female = _make_user(f"gender_f_{uuid.uuid4().hex[:6]}", flatmates=True)
    female.preferences = {"flatmates": {"gender": "female"}}
    db_session.add_all([male, female])
    await db_session.flush()
    await db_session.refresh(male)
    await db_session.refresh(female)

    r = await flatmates_client.get("/api/v1/flatmates/profiles?gender_preference=female&limit=50")
    assert r.status_code == 200, r.text
    ids = {item["id"] for item in r.json()["items"]}
    assert female.id in ids
    assert male.id not in ids

    r_any = await flatmates_client.get("/api/v1/flatmates/profiles?gender_preference=any&limit=50")
    assert r_any.status_code == 200, r_any.text
    any_ids = {item["id"] for item in r_any.json()["items"]}
    assert {male.id, female.id} <= any_ids


async def test_conversation_with_suspended_peer_returns_404(
    db_session, viewer_user, flatmates_client: AsyncClient
) -> None:
    peer = _make_user(f"suspended_{uuid.uuid4().hex[:6]}", flatmates=True)
    peer.is_active = False
    db_session.add(peer)
    await db_session.flush()
    await db_session.refresh(peer)

    r = await flatmates_client.post(
        "/api/v1/flatmates/conversations", json={"peer_user_id": peer.id}
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "PROFILE_NOT_FOUND"


async def test_profiles_invalid_cursor_400(flatmates_client: AsyncClient) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/profiles?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def _seed_peer_with_listing(db_session, prefs: dict[str, Any]) -> tuple[User, str]:
    peer = _make_user(f"peer_listing_{uuid.uuid4().hex[:6]}", flatmates=True)
    db_session.add(peer)
    await db_session.flush()
    title = f"Listing {uuid.uuid4().hex[:8]}"
    listing = Property(
        title=title,
        property_type=PropertyType.flatmate,
        purpose=PropertyPurpose.rent,
        base_price=1_000_000,
        monthly_rent=15000,
        owner_id=peer.id,
        is_available=True,
        listing_preferences=prefs,
    )
    db_session.add(listing)
    await db_session.flush()
    await db_session.refresh(peer)
    return peer, title


@pytest.mark.parametrize(
    "prefs",
    [{"moderation_status": "pending_review"}, {"moderation_status": "paused"}, {}],
    ids=["pending_review", "paused", "status_missing"],
)
async def test_unreviewed_listing_hidden_from_discovery_and_peer_lookup(
    db_session, viewer_user, flatmates_client: AsyncClient, prefs: dict[str, Any]
) -> None:
    peer, title = await _seed_peer_with_listing(db_session, prefs)

    r = await flatmates_client.get("/api/v1/flatmates/profiles?limit=50")
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["id"] == peer.id)
    assert item["listing"] is None

    r_peer = await flatmates_client.get(f"/api/v1/flatmates/profiles/{peer.id}")
    assert r_peer.status_code == 200, r_peer.text
    assert r_peer.json()["listing"] is None

    assert title not in r.text
    assert title not in r_peer.text


async def test_live_listing_shown_in_discovery_and_peer_lookup(
    db_session, viewer_user, flatmates_client: AsyncClient
) -> None:
    peer, title = await _seed_peer_with_listing(db_session, {"moderation_status": "live"})

    r = await flatmates_client.get("/api/v1/flatmates/profiles?limit=50")
    item = next(i for i in r.json()["items"] if i["id"] == peer.id)
    assert item["listing"]["title"] == title

    r_peer = await flatmates_client.get(f"/api/v1/flatmates/profiles/{peer.id}")
    assert r_peer.json()["listing"]["title"] == title


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
        u1, u2 = (
            (viewer_user.id, peer.id) if viewer_user.id < peer.id else (peer.id, viewer_user.id)
        )
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


@pytest_asyncio.fixture
async def mixed_outgoing_likes(db_session, viewer_user) -> tuple[UserSwipe, UserSwipe]:
    """Seed one outgoing property like and one outgoing user like for viewer_user."""
    owner = _make_user("property_owner")
    db_session.add(owner)
    await db_session.flush()
    await db_session.refresh(owner)

    property_obj = Property(
        title="Test liked property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=1_000_000,
        monthly_rent=25000,
        owner_id=owner.id,
        is_available=True,
        listing_preferences={"moderation_status": "live"},
    )
    db_session.add(property_obj)
    await db_session.flush()
    await db_session.refresh(property_obj)

    user_target = _make_user("liked_user", flatmates=True)
    db_session.add(user_target)
    await db_session.flush()
    await db_session.refresh(user_target)

    property_swipe = UserSwipe(
        user_id=viewer_user.id,
        property_id=property_obj.id,
        target_type=SwipeTargetType.property.value,
        swipe_action=SwipeAction.like.value,
        is_liked=True,
    )
    db_session.add(property_swipe)
    await db_session.flush()
    await db_session.refresh(property_swipe)

    user_swipe = UserSwipe(
        user_id=viewer_user.id,
        target_user_id=user_target.id,
        target_type=SwipeTargetType.user.value,
        swipe_action=SwipeAction.like.value,
        is_liked=True,
    )
    db_session.add(user_swipe)
    await db_session.flush()
    await db_session.refresh(user_swipe)

    return property_swipe, user_swipe


async def test_outgoing_likes_mixed_returns_property_and_user(
    flatmates_client: AsyncClient,
    mixed_outgoing_likes: tuple[UserSwipe, UserSwipe],
) -> None:
    r = await flatmates_client.get("/api/v1/flatmates/outgoing-likes?limit=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2

    target_types = {item["target_type"] for item in body["items"]}
    assert target_types == {"user", "property"}

    property_item = next(
        (item for item in body["items"] if item["target_type"] == "property"),
        None,
    )
    assert property_item is not None
    assert property_item["property"]["id"] == mixed_outgoing_likes[0].property_id
    assert property_item["property"]["liked"] is True

    user_item = next(
        (item for item in body["items"] if item["target_type"] == "user"),
        None,
    )
    assert user_item is not None
    assert user_item["peer"]["id"] == mixed_outgoing_likes[1].target_user_id


OWNER_CONTACT = "+91 1111111111"
AGENT_CONTACT = "+91 9000000001"
COMPANY_CONTACT = "+91 8000000000"


async def _seed_liked_listing_for_masking(db_session, viewer: User, *, with_agent: bool) -> None:
    agent_id = None
    if with_agent:
        agent = Agent(
            name="Assigned Agent",
            contact_number=AGENT_CONTACT,
            agent_type=AgentType.general,
            experience_level=ExperienceLevel.expert,
            is_active=True,
        )
        db_session.add(agent)
        await db_session.flush()
        agent_id = agent.id

    owner = _make_user("liked_listing_owner")
    owner.agent_id = agent_id
    db_session.add(owner)
    await db_session.flush()

    listing = Property(
        title="Liked listing",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=1_000_000,
        monthly_rent=25000,
        owner_id=owner.id,
        owner_contact=OWNER_CONTACT,
        is_available=True,
        listing_preferences={
            "moderation_status": "live",
            "moderated_by": 99,
            "moderation_reason": "internal note",
        },
    )
    db_session.add(listing)
    await db_session.flush()

    swipe = UserSwipe(
        user_id=viewer.id,
        property_id=listing.id,
        target_type=SwipeTargetType.property.value,
        swipe_action=SwipeAction.like.value,
        is_liked=True,
    )
    db_session.add(swipe)
    await db_session.flush()


async def test_outgoing_like_shows_agent_number_not_owner_contact(
    db_session, viewer_user, flatmates_client: AsyncClient
) -> None:
    await _seed_liked_listing_for_masking(db_session, viewer_user, with_agent=True)
    r = await flatmates_client.get("/api/v1/flatmates/outgoing-likes?limit=10")
    assert r.status_code == 200, r.text
    items = [i for i in r.json()["items"] if i["target_type"] == "property"]
    assert len(items) == 1
    assert items[0]["property"]["owner_contact"] == AGENT_CONTACT
    assert OWNER_CONTACT not in r.text


async def test_outgoing_like_shows_company_number_when_no_agent(
    db_session,
    viewer_user,
    flatmates_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", COMPANY_CONTACT)
    await _seed_liked_listing_for_masking(db_session, viewer_user, with_agent=False)
    r = await flatmates_client.get("/api/v1/flatmates/outgoing-likes?limit=10")
    assert r.status_code == 200, r.text
    items = [i for i in r.json()["items"] if i["target_type"] == "property"]
    assert len(items) == 1
    assert items[0]["property"]["owner_contact"] == COMPANY_CONTACT
    assert OWNER_CONTACT not in r.text


async def test_outgoing_like_drops_moderator_listing_keys(
    db_session, viewer_user, flatmates_client: AsyncClient
) -> None:
    await _seed_liked_listing_for_masking(db_session, viewer_user, with_agent=True)
    r = await flatmates_client.get("/api/v1/flatmates/outgoing-likes?limit=10")
    assert r.status_code == 200, r.text
    prop = next(i for i in r.json()["items"] if i["target_type"] == "property")["property"]
    prefs = prop["listing_preferences"] or {}
    assert "moderated_by" not in prefs
    assert "moderation_reason" not in prefs
    assert "internal note" not in r.text


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
    r = await admin_client.get("/api/v1/flatmates/moderation/listings?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 3


async def test_admin_listings_invalid_cursor_400(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/api/v1/flatmates/moderation/listings?cursor=garbage!!!")
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
    r = await admin_client.get("/api/v1/flatmates/moderation/reports?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 3


async def test_admin_reports_invalid_cursor_400(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/api/v1/flatmates/moderation/reports?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def _walk_pages(client: AsyncClient, path: str) -> list[int]:
    """Read every page of size 1 and return the ids in the order seen."""
    seen: list[int] = []
    cursor: str | None = None
    while True:
        params = f"limit=1&cursor={cursor}" if cursor else "limit=1"
        r = await client.get(f"{path}?{params}")
        assert r.status_code == 200, r.text
        body = r.json()
        seen.extend(item["id"] for item in body["items"])
        if not body["has_more"]:
            return seen
        cursor = body["next_cursor"]


async def test_profiles_pages_through_tied_last_active(
    flatmates_client: AsyncClient,
    three_discoverable_users: list[User],
) -> None:
    # The fixture leaves flatmates_last_active_at NULL for all three, so the sort ties.
    seen = await _walk_pages(flatmates_client, "/api/v1/flatmates/profiles")

    assert len(seen) == len(set(seen)), "a tied row repeated across pages"
    assert {u.id for u in three_discoverable_users} <= set(seen)


@pytest_asyncio.fixture
async def three_tied_blocks(db_session, viewer_user) -> list[UserBlock]:
    """Three blocks with one created_at, so only the id tiebreak orders them."""
    stamp = datetime(2026, 10, 1, tzinfo=UTC)
    targets = [_make_user(f"blk_{i}") for i in range(3)]
    await _flush_refresh(db_session, *targets)
    blocks = [
        UserBlock(blocker_user_id=viewer_user.id, blocked_user_id=t.id, created_at=stamp)
        for t in targets
    ]
    await _flush_refresh(db_session, *blocks)
    return blocks


async def test_blocks_pages_through_tied_created_at(
    flatmates_client: AsyncClient,
    three_tied_blocks: list[UserBlock],
) -> None:
    seen = await _walk_pages(flatmates_client, "/api/v1/flatmates/blocks")

    assert len(seen) == len(set(seen)), "a tied row repeated across pages"
    assert {b.id for b in three_tied_blocks} == set(seen)


def _peer_of(match: UserMatch, viewer_id: int) -> int:
    return match.user_two_id if match.user_one_id == viewer_id else match.user_one_id


async def test_unmatch_pair_returns_match_status(
    flatmates_client: AsyncClient,
    viewer_user: User,
    three_matches: list[UserMatch],
) -> None:
    match = three_matches[0]
    r = await flatmates_client.post(
        "/api/v1/flatmates/unmatch",
        json={"peer_user_id": _peer_of(match, viewer_user.id)},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"id": match.id, "status": "unmatched"}


async def test_block_returns_block_row_and_rejects_unmatch_only(
    flatmates_client: AsyncClient,
    viewer_user: User,
    three_matches: list[UserMatch],
) -> None:
    peer_id = _peer_of(three_matches[1], viewer_user.id)

    r = await flatmates_client.post(
        "/api/v1/flatmates/blocks",
        json={"blocked_user_id": peer_id, "unmatch_only": True},
    )
    assert r.status_code == 422, r.text
    fields = r.json()["error"]["details"]["fields"]
    assert any(item["field"] == "body.unmatch_only" for item in fields)

    r = await flatmates_client.post("/api/v1/flatmates/blocks", json={"blocked_user_id": peer_id})
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "blocker_user_id", "blocked_user_id", "created_at"}
    assert body["blocked_user_id"] == peer_id


@pytest.mark.parametrize(
    ("field", "value"),
    [("phone", "+919999999999"), ("email", "someone@example.com")],
)
async def test_profile_body_rejects_login_contact_fields(
    flatmates_client: AsyncClient,
    viewer_user: User,
    field: str,
    value: str,
) -> None:
    """Login phone and email are not writable on the flatmates profile (be-content-5)."""
    r = await flatmates_client.put("/api/v1/flatmates/profile", json={field: value})
    assert r.status_code == 422, r.text
    fields = r.json()["error"]["details"]["fields"]
    assert any(item["field"] == f"body.{field}" for item in fields)
