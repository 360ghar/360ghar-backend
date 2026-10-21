"""Tests that a block prevents (re)opening a flatmates conversation.

Regression test for the block-bypass bug where ``create_conversation_from_payload``
did not check ``_is_blocked`` and ``_ensure_conversation`` would silently
reactivate a ``blocked`` conversation back to ``active``.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.enums import ConversationSource, ConversationStatus, FlatmatesProfileStatus
from app.schemas.flatmates import ConversationCreate, MessageCreate
from app.services.flatmates.conversations import (
    _ensure_conversation,
    create_conversation_from_payload,
    send_message,
)
from app.services.flatmates.moderation import create_block, delete_block
from app.services.flatmates.profiles import load_visible_peer


class TestConversationBlockGuard:
    @pytest.mark.asyncio
    async def test_blocker_cannot_open_conversation(self, db_session, test_user, test_user_2):
        await create_block(db_session, test_user.id, test_user_2.id)
        await db_session.flush()

        with pytest.raises(ForbiddenException):
            await create_conversation_from_payload(
                db_session,
                test_user.id,
                ConversationCreate(peer_user_id=test_user_2.id),
            )

    @pytest.mark.asyncio
    async def test_blocked_user_cannot_open_conversation(self, db_session, test_user, test_user_2):
        # test_user blocks test_user_2; the *blocked* user must also be refused
        # (block check is bidirectional).
        await create_block(db_session, test_user.id, test_user_2.id)
        await db_session.flush()

        with pytest.raises(ForbiddenException):
            await create_conversation_from_payload(
                db_session,
                test_user_2.id,
                ConversationCreate(peer_user_id=test_user.id),
            )

    @pytest.mark.asyncio
    async def test_ensure_conversation_does_not_reactivate_blocked(
        self, db_session, test_user, test_user_2
    ):
        # Establish a conversation, then block (which marks it blocked).
        conv = await _ensure_conversation(
            db_session,
            user_id=test_user.id,
            other_user_id=test_user_2.id,
            created_by_user_id=test_user.id,
            source=ConversationSource.profile_match,
        )
        await db_session.flush()
        await create_block(db_session, test_user.id, test_user_2.id)
        await db_session.flush()
        assert conv.status == ConversationStatus.blocked

        # A subsequent _ensure_conversation call must NOT flip it back to active.
        again = await _ensure_conversation(
            db_session,
            user_id=test_user.id,
            other_user_id=test_user_2.id,
            created_by_user_id=test_user.id,
            source=ConversationSource.profile_match,
        )
        assert again.status == ConversationStatus.blocked


class TestConversationPeerVisibility:
    """A conversation and its messages need a visible peer (same rule as GET /profiles/{id})."""

    async def _make_visible(self, db_session, user) -> None:
        user.flatmates_onboarding_completed = True
        user.flatmates_profile_status = FlatmatesProfileStatus.active
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_suspended_peer_cannot_open_conversation(
        self, db_session, test_user, test_user_2
    ):
        await self._make_visible(db_session, test_user_2)
        # Positive control: the peer is visible before suspension.
        assert (await load_visible_peer(db_session, test_user.id, test_user_2.id)).id == (
            test_user_2.id
        )

        test_user_2.is_active = False
        await db_session.flush()

        with pytest.raises(NotFoundException) as exc:
            await create_conversation_from_payload(
                db_session,
                test_user.id,
                ConversationCreate(peer_user_id=test_user_2.id),
            )
        assert exc.value.error_code == "PROFILE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_suspended_peer_cannot_receive_message(self, db_session, test_user, test_user_2):
        await self._make_visible(db_session, test_user_2)
        conv = await _ensure_conversation(
            db_session,
            user_id=test_user.id,
            other_user_id=test_user_2.id,
            created_by_user_id=test_user.id,
            source=ConversationSource.profile_match,
        )
        await db_session.flush()

        test_user_2.is_active = False
        await db_session.flush()

        with pytest.raises(NotFoundException) as exc:
            await send_message(db_session, conv.id, test_user.id, MessageCreate(body="hello"))
        assert exc.value.error_code == "PROFILE_NOT_FOUND"


class TestDeleteBlock:
    @pytest.mark.asyncio
    async def test_unblock_without_block_returns_404(self, db_session, test_user, test_user_2):
        with pytest.raises(NotFoundException) as exc:
            await delete_block(db_session, test_user.id, test_user_2.id)
        assert exc.value.status_code == 404
        assert exc.value.error_code == "BLOCK_NOT_FOUND"
