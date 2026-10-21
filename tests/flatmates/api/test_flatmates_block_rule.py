"""Block and unmatch rule over HTTP (decisions.md, Wave 3d).

An unmatch is final. A block closes the pair even when it never matched. After the
unblock, POST /flatmates/conversations still returns 403 until both users like again.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.enums import FlatmatesProfileStatus, UserMatchStatus, UserRole
from app.models.social import UserMatch
from app.models.users import User

pytestmark = pytest.mark.asyncio

CONVERSATIONS = "/api/v1/flatmates/conversations"


def _visible_user(suffix: str) -> User:
    return User(
        supabase_user_id=str(uuid.uuid4()),
        email=f"block_rule_{suffix}@example.com",
        phone=f"+91{abs(hash('block_rule' + suffix)) % 9_000_000_000 + 1_000_000_000}",
        full_name=f"Block Rule {suffix}",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
        flatmates_onboarding_completed=True,
        flatmates_profile_status=FlatmatesProfileStatus.active,
        flatmates_city="Bengaluru",
    )


@pytest_asyncio.fixture
async def viewer(db_session) -> User:
    user = _visible_user("viewer")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def peer(db_session) -> User:
    user = _visible_user("peer")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client(test_app, viewer) -> AsyncClient:
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_cached_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema
    from app.services.auth_user_cache import snapshot_from_user

    schema = UserSchema.model_validate(viewer, from_attributes=True)
    snapshot = snapshot_from_user(viewer)

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


async def _pair_status(db_session, viewer: User, peer: User) -> UserMatchStatus | None:
    one, two = sorted((viewer.id, peer.id))
    return (
        await db_session.execute(
            select(UserMatch.status).where(
                UserMatch.user_one_id == one, UserMatch.user_two_id == two
            )
        )
    ).scalar_one_or_none()


async def test_unmatch_then_post_conversation_is_forbidden(
    client: AsyncClient, db_session, viewer: User, peer: User
) -> None:
    one, two = sorted((viewer.id, peer.id))
    db_session.add(UserMatch(user_one_id=one, user_two_id=two, status=UserMatchStatus.active))
    await db_session.flush()

    r = await client.post("/api/v1/flatmates/unmatch", json={"peer_user_id": peer.id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unmatched"

    r = await client.post(CONVERSATIONS, json={"peer_user_id": peer.id})
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"]


async def test_block_without_a_match_then_unblock_keeps_conversation_closed(
    client: AsyncClient, db_session, viewer: User, peer: User
) -> None:
    assert await _pair_status(db_session, viewer, peer) is None

    r = await client.post("/api/v1/flatmates/blocks", json={"blocked_user_id": peer.id})
    assert r.status_code == 201, r.text
    assert await _pair_status(db_session, viewer, peer) == UserMatchStatus.blocked

    # While the block exists.
    r = await client.post(CONVERSATIONS, json={"peer_user_id": peer.id})
    assert r.status_code == 403, r.text

    r = await client.delete(f"/api/v1/flatmates/blocks/{peer.id}")
    assert r.status_code == 204, r.text

    # After the unblock the pair is still closed.
    assert await _pair_status(db_session, viewer, peer) == UserMatchStatus.blocked
    r = await client.post(CONVERSATIONS, json={"peer_user_id": peer.id})
    assert r.status_code == 403, r.text


async def test_unblock_then_two_likes_opens_the_pair_again(
    client: AsyncClient, db_session, viewer: User, peer: User
) -> None:
    from app.schemas.flatmates import SwipeRequest
    from app.services.flatmates.matching import record_swipe

    assert (
        await client.post("/api/v1/flatmates/blocks", json={"blocked_user_id": peer.id})
    ).status_code == 201
    assert (await client.delete(f"/api/v1/flatmates/blocks/{peer.id}")).status_code == 204

    def like(target: User) -> SwipeRequest:
        return SwipeRequest.model_validate(
            {"target_type": "user", "action": "like", "target_user_id": target.id}
        )

    first = await record_swipe(db_session, peer.id, like(viewer))
    assert first["did_match"] is False
    r = await client.post(CONVERSATIONS, json={"peer_user_id": peer.id})
    assert r.status_code == 403, r.text

    second = await record_swipe(db_session, viewer.id, like(peer))
    assert second["did_match"] is True
    assert await _pair_status(db_session, viewer, peer) == UserMatchStatus.active
    r = await client.post(CONVERSATIONS, json={"peer_user_id": peer.id})
    assert r.status_code in (200, 201), r.text
