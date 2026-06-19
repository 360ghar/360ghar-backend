"""Conversation and message CRUD."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logging import get_logger
from app.models.enums import ConversationSource, ConversationStatus, MessageType, UserMatchStatus
from app.models.social import MatchQnAAnswer, UserConversation, UserMatch, UserMessage
from app.models.users import User
from app.schemas.flatmates import ConversationCreate, MessageCreate, QnAAnswers
from app.schemas.pagination import offset_payload, read_offset
from app.services.flatmates.helpers import (
    _build_peer_payload,
    _build_property_context,
    _canonical_pair,
)
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


async def _ensure_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    other_user_id: int,
    created_by_user_id: int,
    source: str,
    context_property_id: int | None = None,
) -> UserConversation:
    user_one_id, user_two_id = _canonical_pair(user_id, other_user_id)
    stmt = select(UserConversation).where(
        UserConversation.user_one_id == user_one_id,
        UserConversation.user_two_id == user_two_id,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation:
        if context_property_id is not None:
            conversation.context_property_id = context_property_id
        if conversation.status != ConversationStatus.active:
            conversation.status = ConversationStatus.active
        if source == ConversationSource.profile_match:
            conversation.source = ConversationSource.profile_match
        return conversation

    conversation = UserConversation(
        user_one_id=user_one_id,
        user_two_id=user_two_id,
        created_by_user_id=created_by_user_id,
        context_property_id=context_property_id,
        source=source,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def create_conversation_from_payload(
    db: AsyncSession,
    user_id: int,
    payload: ConversationCreate,
) -> dict[str, Any]:
    """Create (or return existing) conversation between current user and a peer.

    Optionally sends an initial message if ``payload.initial_message`` is provided.
    """
    if payload.peer_user_id == user_id:
        raise BadRequestException(detail="Cannot create a conversation with yourself")

    peer = await db.get(User, payload.peer_user_id)
    if peer is None:
        raise BadRequestException(detail="User not found")

    conversation = await _ensure_conversation(
        db,
        user_id=user_id,
        other_user_id=payload.peer_user_id,
        created_by_user_id=user_id,
        source=ConversationSource.profile_match,
    )

    if payload.initial_message and payload.initial_message.strip():
        message = UserMessage(
            conversation_id=conversation.id,
            sender_id=user_id,
            body=payload.initial_message.strip(),
            message_type=MessageType.text,
        )
        db.add(message)
        now = datetime.now(timezone.utc)
        conversation.last_message_at = now
        conversation.last_message_preview = payload.initial_message.strip()
        await db.flush()
        await db.refresh(message)
    else:
        await db.flush()

    return await get_conversation_summary(db, conversation.id, user_id)


async def _match_created_at(
    db: AsyncSession,
    user_id: int,
    peer_id: int,
) -> datetime | None:
    from app.models.social import UserMatch

    user_one_id, user_two_id = _canonical_pair(user_id, peer_id)
    result = await db.execute(
        select(UserMatch.created_at).where(
            UserMatch.user_one_id == user_one_id,
            UserMatch.user_two_id == user_two_id,
        )
    )
    return result.scalar_one_or_none()


def _build_qna_answer_payload(answer: MatchQnAAnswer | None) -> dict[str, Any] | None:
    if answer is None:
        return None
    if not any((answer.q1, answer.q2, answer.q3)):
        return None
    return {
        "user_id": answer.user_id,
        "q1": answer.q1,
        "q2": answer.q2,
        "q3": answer.q3,
    }


async def _conversation_qna_state(
    db: AsyncSession,
    *,
    user_id: int,
    peer_id: int,
) -> dict[str, Any] | None:
    user_one_id, user_two_id = _canonical_pair(user_id, peer_id)
    match_id = (
        await db.execute(
            select(UserMatch.id).where(
                UserMatch.user_one_id == user_one_id,
                UserMatch.user_two_id == user_two_id,
            )
        )
    ).scalar_one_or_none()
    if match_id is None:
        return None

    answer_rows = list(
        (
            await db.execute(
                select(MatchQnAAnswer).where(
                    MatchQnAAnswer.match_id == match_id,
                    MatchQnAAnswer.user_id.in_([user_id, peer_id]),
                )
            )
        )
        .scalars()
        .all()
    )
    answer_map = {answer.user_id: answer for answer in answer_rows}
    current_user = _build_qna_answer_payload(answer_map.get(user_id))
    peer = _build_qna_answer_payload(answer_map.get(peer_id))
    if current_user is None and peer is None:
        return None
    return {
        "current_user": current_user,
        "peer": peer,
        "both_answered": current_user is not None and peer is not None,
    }


async def get_conversation_summary(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> dict[str, Any]:
    current_user = await db.get(User, user_id)
    conversation = await get_conversation(db, conversation_id, user_id)
    peer_id = (
        conversation.user_two_id
        if conversation.user_one_id == user_id
        else conversation.user_one_id
    )
    peer = await db.get(User, peer_id)
    if peer is None:
        raise BadRequestException(detail="Conversation not found")

    unread_count_stmt = select(func.count(UserMessage.id)).where(
        UserMessage.conversation_id == conversation.id,
        UserMessage.sender_id != user_id,
        UserMessage.read_at.is_(None),
    )
    unread_count = int((await db.execute(unread_count_stmt)).scalar() or 0)

    return {
        "id": conversation.id,
        "source": conversation.source,
        "status": conversation.status,
        "peer": _build_peer_payload(peer, current_user),
        "context_property": _build_property_context(conversation.context_property),
        "last_message_preview": conversation.last_message_preview,
        "last_message_at": conversation.last_message_at,
        "unread_count": unread_count,
        "matched_at": await _match_created_at(db, user_id, peer_id),
        "qna": await _conversation_qna_state(db, user_id=user_id, peer_id=peer_id),
    }


async def list_conversations(
    db: AsyncSession,
    user_id: int,
    *,
    cursor_payload: dict | None = None,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[dict[str, Any]], dict | None, int | None]:
    if cursor_payload is None:
        cursor_payload = {}
    offset = read_offset(cursor_payload)

    current_user = await db.get(User, user_id)

    total: int | None = None
    if with_total:
        total = (
            await db.execute(
                select(func.count())
                .select_from(UserConversation)
                .where(
                    or_(
                        UserConversation.user_one_id == user_id,
                        UserConversation.user_two_id == user_id,
                    )
                )
            )
        ).scalar_one()

    stmt = (
        select(UserConversation)
        .options(selectinload(UserConversation.context_property))
        .where(
            or_(
                UserConversation.user_one_id == user_id,
                UserConversation.user_two_id == user_id,
            )
        )
        .order_by(
            func.coalesce(UserConversation.last_message_at, UserConversation.created_at).desc()
        )
        .offset(offset)
        .limit(limit + 1)
    )
    conversations = list((await db.execute(stmt)).scalars().all())
    has_more = len(conversations) > limit
    conversations = conversations[:limit]
    next_payload = offset_payload(offset + limit) if has_more else None

    if not conversations:
        return [], next_payload, total

    peer_ids = {
        conversation.user_two_id
        if conversation.user_one_id == user_id
        else conversation.user_one_id
        for conversation in conversations
    }
    users_stmt = select(User).where(User.id.in_(peer_ids))
    users = list((await db.execute(users_stmt)).scalars().all())
    user_map = {user.id: user for user in users}

    unread_stmt = (
        select(UserMessage.conversation_id, func.count(UserMessage.id))
        .where(
            UserMessage.conversation_id.in_([conversation.id for conversation in conversations]),
            UserMessage.sender_id != user_id,
            UserMessage.read_at.is_(None),
        )
        .group_by(UserMessage.conversation_id)
    )
    unread_rows = (await db.execute(unread_stmt)).all()
    unread_map = {conversation_id: int(count) for conversation_id, count in unread_rows}

    # Bulk load matches
    match_stmt = select(UserMatch).where(
        or_(
            UserMatch.user_one_id == user_id,
            UserMatch.user_two_id == user_id,
        )
    )
    matches = list((await db.execute(match_stmt)).scalars().all())
    match_created_at_map = {}
    match_id_map = {}
    for match in matches:
        peer = match.user_one_id if match.user_two_id == user_id else match.user_two_id
        match_created_at_map[peer] = match.created_at
        match_id_map[peer] = match.id

    # Bulk load QnA
    qna_map = {}
    if match_id_map:
        qna_stmt = select(MatchQnAAnswer).where(
            MatchQnAAnswer.match_id.in_(list(match_id_map.values()))
        )
        qna_answers = list((await db.execute(qna_stmt)).scalars().all())
        from collections import defaultdict
        qna_by_match: dict[int, list[MatchQnAAnswer]] = defaultdict(list)
        for ans in qna_answers:
            qna_by_match[ans.match_id].append(ans)

        for peer, mid in match_id_map.items():
            answers = qna_by_match.get(mid, [])
            answer_map = {ans.user_id: ans for ans in answers}
            cu_ans = _build_qna_answer_payload(answer_map.get(user_id))
            peer_ans = _build_qna_answer_payload(answer_map.get(peer))
            if cu_ans is None and peer_ans is None:
                qna_map[peer] = None
            else:
                qna_map[peer] = {
                    "current_user": cu_ans,
                    "peer": peer_ans,
                    "both_answered": cu_ans is not None and peer_ans is not None,
                }

    items: list[dict[str, Any]] = []
    for conversation in conversations:
        peer_id = (
            conversation.user_two_id
            if conversation.user_one_id == user_id
            else conversation.user_one_id
        )
        peer = user_map.get(peer_id)
        if peer is None:
            continue
        items.append(
            {
                "id": conversation.id,
                "source": conversation.source,
                "status": conversation.status,
                "peer": _build_peer_payload(peer, current_user),
                "context_property": _build_property_context(conversation.context_property),
                "last_message_preview": conversation.last_message_preview,
                "last_message_at": conversation.last_message_at,
                "unread_count": unread_map.get(conversation.id, 0),
                "matched_at": match_created_at_map.get(peer_id),
                "qna": qna_map.get(peer_id),
            }
        )
    return items, next_payload, total


async def get_conversation(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> UserConversation:
    stmt = (
        select(UserConversation)
        .options(selectinload(UserConversation.context_property))
        .where(UserConversation.id == conversation_id)
    )
    conversation = (await db.execute(stmt)).scalar_one_or_none()
    if conversation is None:
        raise BadRequestException(detail="Conversation not found")
    if user_id not in {conversation.user_one_id, conversation.user_two_id}:
        raise BadRequestException(detail="Conversation not found")
    return conversation


async def list_messages(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> list[UserMessage]:
    await get_conversation(db, conversation_id, user_id)
    stmt = (
        select(UserMessage)
        .where(UserMessage.conversation_id == conversation_id)
        .order_by(UserMessage.created_at.asc())
    )
    messages = list((await db.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc)
    for message in messages:
        if message.sender_id != user_id and message.read_at is None:
            message.read_at = now
    await db.flush()
    return messages


async def send_message(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
    payload: MessageCreate,
) -> UserMessage:
    conversation = await get_conversation(db, conversation_id, user_id)
    if conversation.status != ConversationStatus.active:
        raise BadRequestException(detail="Conversation is not active")

    body = payload.body.strip() if payload.body else None
    attachment_url = payload.attachment_url
    if attachment_url is not None and not ValidationUtils.is_absolute_url(attachment_url):
        logger.warning(
            "Non-absolute attachment_url in conversation %s from user %s: %s",
            conversation_id, user_id, attachment_url,
        )
    message = UserMessage(
        conversation_id=conversation.id,
        sender_id=user_id,
        body=body,
        attachment_url=attachment_url,
        message_type=payload.message_type,
        message_metadata=payload.metadata,
    )
    db.add(message)
    await db.flush()
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.last_message_preview = body or payload.attachment_url or "Attachment"
    await db.flush()
    await db.refresh(message)

    # --- Push notification to peer ---
    peer_id = (
        conversation.user_two_id
        if conversation.user_one_id == user_id
        else conversation.user_one_id
    )

    try:
        from app.services.push_notification import notify_new_message

        sender = await db.get(User, user_id)
        sender_name = (sender.full_name if sender else None) or "Someone"
        await notify_new_message(
            db,
            recipient_db_id=peer_id,
            sender_name=sender_name,
            conversation_id=conversation.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Message notification failed (best-effort): %s", exc, exc_info=True)
        pass  # best-effort; never block message delivery

    return message


async def mark_conversation_read(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> dict[str, str]:
    """Mark all peer messages in a conversation as read."""
    # Authorization check: raises if the user is not a participant.
    await get_conversation(db, conversation_id, user_id)

    now = datetime.now(timezone.utc)
    await db.execute(
        update(UserMessage)
        .where(
            UserMessage.conversation_id == conversation_id,
            UserMessage.sender_id != user_id,
            UserMessage.read_at.is_(None),
        )
        .values(read_at=now)
    )
    await db.commit()

    return {"status": "success"}


async def save_match_qna_answers(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
    payload: QnAAnswers,
) -> dict[str, int | str]:
    """Persist current-user match Q&A answers for a conversation."""
    result = await db.execute(
        select(UserConversation).where(
            UserConversation.id == conversation_id,
            (UserConversation.user_one_id == user_id) | (UserConversation.user_two_id == user_id),
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise NotFoundException(detail="Conversation not found")

    other_user_id = (
        conversation.user_two_id if conversation.user_one_id == user_id else conversation.user_one_id
    )
    user_one_id, user_two_id = _canonical_pair(user_id, other_user_id)

    match_result = await db.execute(
        select(UserMatch).where(
            UserMatch.user_one_id == user_one_id,
            UserMatch.user_two_id == user_two_id,
        )
    )
    user_match = match_result.scalar_one_or_none()

    if not user_match:
        user_match = UserMatch(
            user_one_id=user_one_id,
            user_two_id=user_two_id,
            context_property_id=conversation.context_property_id,
            status=UserMatchStatus.active,
        )
        db.add(user_match)
        await db.flush()

    existing = await db.execute(
        select(MatchQnAAnswer).where(
            MatchQnAAnswer.match_id == user_match.id,
            MatchQnAAnswer.user_id == user_id,
        )
    )
    qna_answer = existing.scalar_one_or_none()
    if qna_answer is None:
        qna_answer = MatchQnAAnswer(
            match_id=user_match.id,
            user_id=user_id,
        )
        db.add(qna_answer)

    answer_fields = {
        0: "q1",
        1: "q2",
        2: "q3",
    }
    for idx_str, answer_text in payload.answers.items():
        answer_field = answer_fields.get(int(idx_str))
        if answer_field is not None:
            setattr(qna_answer, answer_field, str(answer_text))

    await db.commit()
    return {"status": "success", "match_id": user_match.id}
