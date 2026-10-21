"""An unmatch is final, a block closes the pair, and swipe targets and match contacts need a visible profile.

Covers ledger r3-fm-web-b-10 and be-content-1. Each test fails without its fix:
the conversation or match would otherwise reopen, or a paused peer would be matched
or have its phone returned.
"""

from __future__ import annotations

import pytest
from sqlalchemy import and_, func, or_, select

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.enums import (
    ConversationSource,
    ConversationStatus,
    FlatmatesProfileStatus,
    SwipeAction,
    SwipeTargetType,
    UserMatchStatus,
)
from app.models.social import UserBlock, UserMatch
from app.models.users import UserSwipe
from app.schemas.flatmates import ConversationCreate, MessageCreate, SwipeRequest
from app.services.flatmates.conversations import (
    _ensure_conversation,
    create_conversation_from_payload,
    send_message,
)
from app.services.flatmates.helpers import _canonical_pair, _ensure_match
from app.services.flatmates.matching import get_match_contact, record_swipe, unmatch_user_pair
from app.services.flatmates.moderation import create_block, delete_block


def _make_visible(user) -> None:
    user.flatmates_onboarding_completed = True
    user.flatmates_profile_status = FlatmatesProfileStatus.active


async def _active_pair(db_session, user_a, user_b) -> tuple[int, int]:
    """Create an active match and its conversation. Return (match_id, conversation_id)."""
    _make_visible(user_a)
    _make_visible(user_b)
    await db_session.flush()
    match = await _ensure_match(db_session, user_id=user_a.id, other_user_id=user_b.id)
    conv = await _ensure_conversation(
        db_session,
        user_id=user_a.id,
        other_user_id=user_b.id,
        created_by_user_id=user_a.id,
        source=ConversationSource.profile_match,
    )
    await db_session.flush()
    return match.id, conv.id


async def _match_status(db_session, user_a, user_b) -> str:
    one, two = _canonical_pair(user_a.id, user_b.id)
    return (
        await db_session.execute(
            select(UserMatch.status).where(
                UserMatch.user_one_id == one, UserMatch.user_two_id == two
            )
        )
    ).scalar_one()


class TestUnmatchIsFinal:
    @pytest.mark.asyncio
    async def test_unmatched_pair_cannot_open_conversation(
        self, db_session, test_user, test_user_2
    ):
        await _active_pair(db_session, test_user, test_user_2)
        await unmatch_user_pair(db_session, test_user.id, test_user_2.id)

        with pytest.raises(ForbiddenException):
            await create_conversation_from_payload(
                db_session,
                test_user.id,
                ConversationCreate(peer_user_id=test_user_2.id),
            )

    @pytest.mark.asyncio
    async def test_unmatched_conversation_stays_closed_and_rejects_messages(
        self, db_session, test_user, test_user_2
    ):
        _, conv_id = await _active_pair(db_session, test_user, test_user_2)
        await unmatch_user_pair(db_session, test_user.id, test_user_2.id)

        again = await _ensure_conversation(
            db_session,
            user_id=test_user.id,
            other_user_id=test_user_2.id,
            created_by_user_id=test_user.id,
            source=ConversationSource.profile_match,
        )
        assert again.id == conv_id
        assert again.status == ConversationStatus.closed

        with pytest.raises(BadRequestException):
            await send_message(db_session, conv_id, test_user.id, MessageCreate(body="hello"))

    @pytest.mark.asyncio
    async def test_reciprocal_like_does_not_reopen_unmatched_pair(
        self, db_session, test_user, test_user_2
    ):
        _make_visible(test_user)
        _make_visible(test_user_2)
        await db_session.flush()
        await record_swipe(
            db_session,
            test_user_2.id,
            SwipeRequest(
                target_type=SwipeTargetType.user,
                action=SwipeAction.like,
                target_user_id=test_user.id,
            ),
        )
        first = await record_swipe(
            db_session,
            test_user.id,
            SwipeRequest(
                target_type=SwipeTargetType.user,
                action=SwipeAction.like,
                target_user_id=test_user_2.id,
            ),
        )
        assert first["did_match"] is True
        match_id = first["match_id"]

        await unmatch_user_pair(db_session, test_user.id, test_user_2.id)

        again = await record_swipe(
            db_session,
            test_user.id,
            SwipeRequest(
                target_type=SwipeTargetType.user,
                action=SwipeAction.like,
                target_user_id=test_user_2.id,
            ),
        )
        assert again["did_match"] is False
        assert again["match_id"] is None
        assert await _match_status(db_session, test_user, test_user_2) == "unmatched"
        with pytest.raises(NotFoundException) as exc:
            await get_match_contact(db_session, test_user.id, match_id)
        assert exc.value.error_code == "MATCH_NOT_FOUND"


class TestEnsureMatchKeepsUnmatched:
    @pytest.mark.asyncio
    async def test_ensure_match_does_not_reactivate_unmatched_pair(
        self, db_session, test_user, test_user_2
    ):
        await _active_pair(db_session, test_user, test_user_2)
        await unmatch_user_pair(db_session, test_user.id, test_user_2.id)

        match = await _ensure_match(db_session, user_id=test_user.id, other_user_id=test_user_2.id)
        assert match.status == UserMatchStatus.unmatched
        assert await _match_status(db_session, test_user, test_user_2) == "unmatched"


def _like(target_user_id: int) -> SwipeRequest:
    return SwipeRequest(
        target_type=SwipeTargetType.user,
        action=SwipeAction.like,
        target_user_id=target_user_id,
    )


async def _swipe_count(db_session, user_a, user_b) -> int:
    return (
        await db_session.execute(
            select(func.count())
            .select_from(UserSwipe)
            .where(
                or_(
                    and_(UserSwipe.user_id == user_a.id, UserSwipe.target_user_id == user_b.id),
                    and_(UserSwipe.user_id == user_b.id, UserSwipe.target_user_id == user_a.id),
                )
            )
        )
    ).scalar_one()


class TestBlockRule:
    """Block rule (decisions.md, Wave 3d).

    A block closes the pair even when it never matched, and clears both users' likes.
    The pair stays closed after the unblock. It reopens only when both users like again.
    An unmatched pair never reopens.
    """

    @pytest.mark.asyncio
    async def test_block_without_a_match_leaves_a_closed_row(
        self, db_session, test_user, test_user_2
    ):
        _make_visible(test_user)
        _make_visible(test_user_2)
        await db_session.flush()

        await create_block(db_session, test_user.id, test_user_2.id)
        assert await _match_status(db_session, test_user, test_user_2) == "blocked"

        await delete_block(db_session, test_user.id, test_user_2.id)
        assert await _match_status(db_session, test_user, test_user_2) == "blocked"
        with pytest.raises(ForbiddenException):
            await create_conversation_from_payload(
                db_session,
                test_user.id,
                ConversationCreate(peer_user_id=test_user_2.id),
            )

    @pytest.mark.asyncio
    async def test_a_like_from_before_the_block_does_not_count_after_the_unblock(
        self, db_session, test_user, test_user_2
    ):
        _make_visible(test_user)
        _make_visible(test_user_2)
        await db_session.flush()
        # test_user_2 likes test_user. No match yet, so the block finds no match row.
        await record_swipe(db_session, test_user_2.id, _like(test_user.id))
        assert await _swipe_count(db_session, test_user, test_user_2) == 1

        await create_block(db_session, test_user.id, test_user_2.id)
        assert await _swipe_count(db_session, test_user, test_user_2) == 0
        await delete_block(db_session, test_user.id, test_user_2.id)

        # Without the block rule this like met the old like and matched at once.
        first = await record_swipe(db_session, test_user.id, _like(test_user_2.id))
        assert first["did_match"] is False
        assert first["match_id"] is None
        assert await _match_status(db_session, test_user, test_user_2) == "blocked"

        # Both users liked after the unblock, so the pair matches again.
        second = await record_swipe(db_session, test_user_2.id, _like(test_user.id))
        assert second["did_match"] is True
        assert await _match_status(db_session, test_user, test_user_2) == "active"

    @pytest.mark.asyncio
    async def test_blocked_pair_stays_closed_until_both_like_again(
        self, db_session, test_user, test_user_2
    ):
        match_id, conv_id = await _active_pair(db_session, test_user, test_user_2)
        await create_block(db_session, test_user.id, test_user_2.id)
        await delete_block(db_session, test_user.id, test_user_2.id)

        # The unblock alone opens nothing.
        assert await _match_status(db_session, test_user, test_user_2) == "blocked"
        with pytest.raises(NotFoundException) as exc:
            await get_match_contact(db_session, test_user.id, match_id)
        assert exc.value.error_code == "MATCH_NOT_FOUND"
        with pytest.raises(ForbiddenException):
            await create_conversation_from_payload(
                db_session,
                test_user.id,
                ConversationCreate(peer_user_id=test_user_2.id),
            )
        with pytest.raises(BadRequestException):
            await send_message(db_session, conv_id, test_user.id, MessageCreate(body="hello"))

        # One like does not reopen it.
        one_sided = await record_swipe(db_session, test_user_2.id, _like(test_user.id))
        assert one_sided["did_match"] is False
        assert await _match_status(db_session, test_user, test_user_2) == "blocked"

        # The second like does. The same match and conversation come back.
        both = await record_swipe(db_session, test_user.id, _like(test_user_2.id))
        assert both["did_match"] is True
        assert both["match_id"] == match_id
        assert both["conversation_id"] == conv_id
        assert await _match_status(db_session, test_user, test_user_2) == "active"
        contact = await get_match_contact(db_session, test_user.id, match_id)
        assert contact["phone"] == test_user_2.phone
        message = await send_message(
            db_session, conv_id, test_user.id, MessageCreate(body="hello again")
        )
        assert message is not None

    @pytest.mark.asyncio
    async def test_swipe_is_refused_while_the_block_exists(
        self, db_session, test_user, test_user_2
    ):
        await _active_pair(db_session, test_user, test_user_2)
        await create_block(db_session, test_user.id, test_user_2.id)

        for swiper, target in ((test_user, test_user_2), (test_user_2, test_user)):
            with pytest.raises(BadRequestException):
                await record_swipe(db_session, swiper.id, _like(target.id))
        assert await _swipe_count(db_session, test_user, test_user_2) == 0

    @pytest.mark.asyncio
    async def test_a_block_does_not_weaken_an_unmatch(self, db_session, test_user, test_user_2):
        await _active_pair(db_session, test_user, test_user_2)
        await unmatch_user_pair(db_session, test_user.id, test_user_2.id)
        await create_block(db_session, test_user.id, test_user_2.id)
        await delete_block(db_session, test_user.id, test_user_2.id)
        assert await _match_status(db_session, test_user, test_user_2) == "unmatched"

        await record_swipe(db_session, test_user_2.id, _like(test_user.id))
        again = await record_swipe(db_session, test_user.id, _like(test_user_2.id))
        assert again["did_match"] is False
        assert await _match_status(db_session, test_user, test_user_2) == "unmatched"

    @pytest.mark.asyncio
    async def test_posting_an_existing_block_closes_the_pair(
        self, db_session, test_user, test_user_2
    ):
        """A block saved before the rule has no match row. Posting it again closes the pair."""
        db_session.add(UserBlock(blocker_user_id=test_user.id, blocked_user_id=test_user_2.id))
        await db_session.flush()

        await create_block(db_session, test_user.id, test_user_2.id)
        assert await _match_status(db_session, test_user, test_user_2) == "blocked"

    @pytest.mark.asyncio
    async def test_ensure_match_does_not_reactivate_blocked_pair(
        self, db_session, test_user, test_user_2
    ):
        await _active_pair(db_session, test_user, test_user_2)
        await create_block(db_session, test_user.id, test_user_2.id)
        await delete_block(db_session, test_user.id, test_user_2.id)

        match = await _ensure_match(db_session, user_id=test_user.id, other_user_id=test_user_2.id)
        assert match.status == UserMatchStatus.blocked
        assert await _match_status(db_session, test_user, test_user_2) == "blocked"


class TestSwipeTargetVisibility:
    @pytest.mark.asyncio
    async def test_paused_user_cannot_be_swiped_or_matched(
        self, db_session, test_user, test_user_2
    ):
        _make_visible(test_user)
        _make_visible(test_user_2)
        test_user_2.flatmates_profile_status = FlatmatesProfileStatus.paused
        await db_session.flush()

        with pytest.raises(NotFoundException) as exc:
            await record_swipe(
                db_session,
                test_user.id,
                SwipeRequest(
                    target_type=SwipeTargetType.user,
                    action=SwipeAction.like,
                    target_user_id=test_user_2.id,
                ),
            )
        assert exc.value.error_code == "PROFILE_NOT_FOUND"
        stored = (
            await db_session.execute(
                select(func.count())
                .select_from(UserSwipe)
                .where(
                    UserSwipe.user_id == test_user.id,
                    UserSwipe.target_user_id == test_user_2.id,
                )
            )
        ).scalar_one()
        assert stored == 0


class TestMatchContactVisibility:
    @pytest.mark.asyncio
    async def test_contact_returns_phone_for_visible_peer(self, db_session, test_user, test_user_2):
        match_id, _ = await _active_pair(db_session, test_user, test_user_2)

        contact = await get_match_contact(db_session, test_user.id, match_id)
        assert contact["phone"] == test_user_2.phone

    @pytest.mark.asyncio
    async def test_contact_hidden_when_peer_profile_paused(
        self, db_session, test_user, test_user_2
    ):
        match_id, _ = await _active_pair(db_session, test_user, test_user_2)
        test_user_2.flatmates_profile_status = FlatmatesProfileStatus.paused
        await db_session.flush()

        with pytest.raises(NotFoundException) as exc:
            await get_match_contact(db_session, test_user.id, match_id)
        assert exc.value.error_code == "MATCH_NOT_FOUND"
