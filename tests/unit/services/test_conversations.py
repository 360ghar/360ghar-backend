"""Tests for conversations service."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event

from app.schemas.flatmates import MessageCreate
from app.services.flatmates.conversations import send_message
from app.models.enums import MessageType


class TestConversationsService:
    @pytest.mark.asyncio
    async def test_send_message_dispatches_notification_after_commit(
        self, db_session, test_user, test_user_2
    ):
        """Test that the push notification is scheduled via after_commit hook."""
        from app.services.flatmates.conversations import _ensure_conversation
        from app.models.enums import ConversationSource
        
        conv = await _ensure_conversation(
            db_session,
            user_id=test_user.id,
            other_user_id=test_user_2.id,
            created_by_user_id=test_user.id,
            source=ConversationSource.profile_match,
        )
        await db_session.flush()

        payload = MessageCreate(
            body="Hello world",
            message_type=MessageType.text,
        )

        with patch("app.services.flatmates.conversations.asyncio.create_task") as mock_create_task:
            # We must mock _find_participant_peer_id and _is_blocked as well, or just run them with DB
            await send_message(db_session, conv.id, test_user.id, payload)
            
            # Since the transaction is not committed yet, the after_commit event is registered but not fired
            mock_create_task.assert_not_called()

            # Now we commit the transaction
            await db_session.commit()

            # The after_commit event should fire and call create_task
            mock_create_task.assert_called_once()
