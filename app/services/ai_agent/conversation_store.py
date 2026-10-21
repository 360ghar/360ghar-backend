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
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead

logger = get_logger(__name__)


async def get_owned_conversation(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
) -> AIConversation | None:
    """Return the conversation when the user owns it. Other users get None (404 at the route)."""
    stmt = select(AIConversation).where(
        AIConversation.id == conversation_id,
        AIConversation.user_id == user_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_conversation(db: AsyncSession, user_id: int) -> AIConversation:
    """Create an empty conversation for the user."""
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
    """Retrieve the most recent messages for a conversation, oldest first.

    Rows of one reply share ``created_at`` (one transaction), so ``id`` breaks ties.
    """
    stmt = (
        select(AIConversationMessage)
        .where(AIConversationMessage.conversation_id == conversation_id)
        .order_by(AIConversationMessage.created_at.desc(), AIConversationMessage.id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()  # Chronological order
    return messages


async def get_history_page(
    db: AsyncSession,
    conversation_id: int,
    *,
    cursor_payload: dict[str, Any],
    limit: int,
) -> tuple[list[AIConversationMessage], dict[str, Any] | None]:
    """Keyset page of messages, newest first; the next cursor points to older messages.

    The page itself is returned in chronological order so clients can prepend it.
    """
    stmt = select(AIConversationMessage).where(
        AIConversationMessage.conversation_id == conversation_id
    )
    predicate = keyset_filter(
        AIConversationMessage.created_at, AIConversationMessage.id, cursor_payload, descending=True
    )
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(
        AIConversationMessage.created_at.desc(), AIConversationMessage.id.desc()
    ).limit(limit + 1)
    result = await db.execute(stmt)
    messages, next_payload = trim_keyset_lookahead(
        list(result.scalars().all()),
        limit=limit,
        sort_value=lambda m: m.created_at,
        item_id=lambda m: m.id,
    )
    messages.reverse()  # Chronological order within the page
    return messages, next_payload


async def list_conversations(
    db: AsyncSession,
    user_id: int,
    *,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    """One keyset page of a user's conversations, newest activity first.

    The cursor holds ``(updated_at, id)`` of the last row. A conversation that gets a
    new message moves to the top; it does not repeat or shift the rows after the cursor.
    """
    if cursor_payload is None:
        cursor_payload = {}

    total: int | None = None
    if with_total:
        total = (
            await db.execute(
                select(func.count())
                .select_from(AIConversation)
                .where(AIConversation.user_id == user_id)
            )
        ).scalar_one()

    msg_count = (
        select(func.count(AIConversationMessage.id))
        .where(AIConversationMessage.conversation_id == AIConversation.id)
        .correlate(AIConversation)
        .scalar_subquery()
    )
    stmt = select(AIConversation, msg_count.label("message_count")).where(
        AIConversation.user_id == user_id
    )
    predicate = keyset_filter(
        AIConversation.updated_at, AIConversation.id, cursor_payload, descending=True
    )
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(AIConversation.updated_at.desc(), AIConversation.id.desc()).limit(
        limit + 1
    )
    rows = (await db.execute(stmt)).all()
    page_rows, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda row: row[0].updated_at,
        item_id=lambda row: row[0].id,
    )

    items = [
        {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "message_count": count or 0,
        }
        for conv, count in page_rows
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
