"""Migration 20261015004000 closes the pair of every block saved before the block rule."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.models.enums import SwipeAction, SwipeTargetType, UserMatchStatus
from app.models.social import UserBlock, UserMatch
from app.models.users import User, UserSwipe
from app.services.flatmates.helpers import _canonical_pair

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20261015004000_flatmates_block_closes_pair.sql"
)


@pytest_asyncio.fixture
async def test_user_3(db_session) -> User:
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="testuser3@example.com",
        phone="+919876543212",
        full_name="Test User 3",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


async def _run_migration(db_session) -> None:
    statements = [part.strip() for part in MIGRATION.read_text().split(";") if part.strip()]
    for statement in statements:
        await db_session.execute(text(statement))


def _swipe(user_id: int, target_user_id: int) -> UserSwipe:
    return UserSwipe(
        user_id=user_id,
        target_user_id=target_user_id,
        target_type=SwipeTargetType.user.value,
        swipe_action=SwipeAction.like.value,
        is_liked=True,
    )


@pytest.mark.asyncio
async def test_migration_closes_blocked_pairs_and_clears_their_likes(
    db_session, test_user, test_user_2
) -> None:
    db_session.add_all(
        [
            # A block with no match row, and a like from the blocked user from before the block.
            UserBlock(blocker_user_id=test_user.id, blocked_user_id=test_user_2.id),
            _swipe(test_user_2.id, test_user.id),
        ]
    )
    await db_session.flush()

    await _run_migration(db_session)
    await _run_migration(db_session)  # a second run changes nothing

    one, two = _canonical_pair(test_user.id, test_user_2.id)
    status = (
        await db_session.execute(
            select(UserMatch.status).where(
                UserMatch.user_one_id == one, UserMatch.user_two_id == two
            )
        )
    ).scalar_one()
    assert status == UserMatchStatus.blocked
    swipes = (await db_session.execute(select(func.count()).select_from(UserSwipe))).scalar_one()
    assert swipes == 0


@pytest.mark.asyncio
async def test_migration_closes_an_active_match_and_keeps_an_unmatched_one(
    db_session, test_user, test_user_2, test_user_3
) -> None:
    one, two = _canonical_pair(test_user.id, test_user_2.id)
    other_one, other_two = _canonical_pair(test_user.id, test_user_3.id)
    db_session.add_all(
        [
            UserMatch(user_one_id=one, user_two_id=two, status=UserMatchStatus.active),
            UserMatch(
                user_one_id=other_one, user_two_id=other_two, status=UserMatchStatus.unmatched
            ),
            UserBlock(blocker_user_id=test_user.id, blocked_user_id=test_user_2.id),
            # Both users block each other: one match row, no duplicate-row error.
            UserBlock(blocker_user_id=test_user_2.id, blocked_user_id=test_user.id),
            UserBlock(blocker_user_id=test_user.id, blocked_user_id=test_user_3.id),
        ]
    )
    await db_session.flush()

    await _run_migration(db_session)

    rows = {
        (row.user_one_id, row.user_two_id): row.status
        for row in (
            await db_session.execute(
                select(UserMatch.user_one_id, UserMatch.user_two_id, UserMatch.status)
            )
        ).all()
    }
    assert rows == {
        (one, two): UserMatchStatus.blocked,
        (other_one, other_two): UserMatchStatus.unmatched,
    }
