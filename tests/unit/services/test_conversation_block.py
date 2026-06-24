"""Tests that a block prevents (re)opening a flatmates conversation.

Regression test for the block-bypass bug where ``create_conversation_from_payload``
did not check ``_is_blocked`` and ``_ensure_conversation`` would silently
reactivate a ``blocked`` conversation back to ``active``.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ForbiddenException
from app.models.enums import ConversationSource, ConversationStatus
from app.schemas.flatmates import ConversationCreate
from app.services.flatmates.conversations import (
    _ensure_conversation,
    create_conversation_from_payload,
)
from app.services.flatmates.moderation import create_block


class TestConversationBlockGuard:
    @pytest.mark.asyncio
    async def test_blocker_cannot_open_conversation(
        self, db_session, test_user, test_user_2
    ):
        await create_block(db_session, test_user.id, test_user_2.id)
        await db_session.flush()

        with pytest.raises(ForbiddenException):
            await create_conversation_from_payload(
                db_session,
                test_user.id,
                ConversationCreate(peer_user_id=test_user_2.id),
            )

    @pytest.mark.asyncio
    async def test_blocked_user_cannot_open_conversation(
        self, db_session, test_user, test_user_2
    ):
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
