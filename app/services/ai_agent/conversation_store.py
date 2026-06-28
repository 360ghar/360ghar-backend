"""
Conversation persistence for the AI Agent.

Manages CRUD operations for AI conversations and messages.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.ai_conversations import AIConversation, AIConversationMessage
from app.schemas.pagination import offset_payload, read_offset

logger = get_logger(__name__)


async def get_or_create_conversation(
    db: AsyncSession,
    user_id: int,
    conversation_id: int | None = None,
) -> AIConversation:
    """Load an existing conversation or create a new one."""
    if conversation_id is not None:
        stmt = select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == user_id,
        )
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv is not None:
            return conv
        logger.warning(
            "Conversation %s not found for user %s, creating new",
            conversation_id,
            user_id,
        )

    conv = AIConversation(user_id=user_id)
    db.add(conv)
    await db.flush()
    return conv


async def add_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str | None = None,
    tool_name: str | None = None,
    tool_args: dict[str, Any] | None = None,
    tool_result: dict[str, Any] | None = None,
) -> AIConversationMessage:
    """Persist a message to the conversation."""
    msg = AIConversationMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
    )
    db.add(msg)
    await db.flush()

    # Auto-generate title from first user message
    if role == "user" and content:
        conv_stmt = select(AIConversation).where(AIConversation.id == conversation_id)
        result = await db.execute(conv_stmt)
        conv = result.scalar_one_or_none()
        if conv and not conv.title:
            conv.title = content[:60].strip()
            await db.flush()

    return msg


async def get_history(
    db: AsyncSession,
    conversation_id: int,
    limit: int = 50,
) -> list[AIConversationMessage]:
    """Retrieve the most recent messages for a conversation."""
    stmt = (
        select(AIConversationMessage)
        .where(AIConversationMessage.conversation_id == conversation_id)
        .order_by(AIConversationMessage.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()  # Chronological order
    return messages


async def list_conversations(
    db: AsyncSession,
    user_id: int,
    *,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    """List conversations for a user with message counts."""
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    total: int | None = None
    if with_total:
        total = (
            await db.execute(
                select(func.count()).select_from(AIConversation).where(AIConversation.user_id == user_id)
            )
        ).scalar_one()

    msg_count = (
        select(func.count(AIConversationMessage.id))
        .where(AIConversationMessage.conversation_id == AIConversation.id)
        .correlate(AIConversation)
        .scalar_subquery()
    )
    stmt = (
        select(AIConversation, msg_count.label("message_count"))
        .where(AIConversation.user_id == user_id)
        .order_by(AIConversation.updated_at.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_payload = offset_payload(offset + limit) if has_more else None

    items = [
        {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "message_count": count or 0,
        }
        for conv, count in rows
    ]
    return items, next_payload, total


async def delete_conversation(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> bool:
    """Delete a conversation owned by the user. Returns True if deleted."""
    stmt = delete(AIConversation).where(
        AIConversation.id == conversation_id,
        AIConversation.user_id == user_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return bool(result.rowcount) > 0  # type: ignore[attr-defined]
