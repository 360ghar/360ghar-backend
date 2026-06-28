"""Conversation and message CRUD.

Uses the generic conversations system (app.models.conversations) scoped
to ``app='flatmates'``. Conversations are N-party via a separate
participants table, but flatmates usage is always 1:1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.core.logging import get_logger
from app.models.conversations import (
    Conversation,
    ConversationParticipant,
    Message,
)
from app.models.enums import (
    ConversationApp,
    ConversationSource,
    ConversationStatus,
    MessageType,
    UserMatchStatus,
)
from app.models.properties import Property
from app.models.social import MatchQnAAnswer, UserMatch
from app.models.users import User
from app.schemas.flatmates import ConversationCreate, MessageCreate, QnAAnswers
from app.schemas.pagination import offset_payload, read_offset
from app.services.flatmates.helpers import (
    _build_peer_payload,
    _build_property_context,
    _canonical_pair,
    _is_blocked,
)
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _find_participant_peer_id(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> int | None:
    """Return the *other* participant's user_id in a 1:1 flatmates conversation."""
    stmt = select(ConversationParticipant.user_id).where(
        ConversationParticipant.conversation_id == conversation_id,
        ConversationParticipant.user_id != user_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_context_property(
    db: AsyncSession,
    conversation: Conversation,
) -> Property | None:
    """Fetch the property referenced by a conversation's polymorphic context."""
    if conversation.context_type != "property" or conversation.context_id is None:
        return None
    return await db.get(Property, conversation.context_id)


async def _ensure_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    other_user_id: int,
    created_by_user_id: int,
    source: str,
    context_property_id: int | None = None,
) -> Conversation:
    """Find or create a 1:1 flatmates conversation between two users."""
    # Find conversations where BOTH users are participants and total participant count is 2
    user_conv_ids = select(ConversationParticipant.conversation_id).where(
        ConversationParticipant.user_id == user_id
    )
    other_conv_ids = select(ConversationParticipant.conversation_id).where(
        ConversationParticipant.user_id == other_user_id
    )
    existing_id = (
        await db.execute(
            select(ConversationParticipant.conversation_id)
            .where(
                ConversationParticipant.conversation_id.in_(user_conv_ids),
                ConversationParticipant.conversation_id.in_(other_conv_ids),
            )
            .group_by(ConversationParticipant.conversation_id)
            .having(func.count() == 2)
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing_id is not None:
        conversation = await db.get(Conversation, existing_id)
        assert conversation is not None  # noqa: S101
        if context_property_id is not None:
            conversation.context_type = "property"
            conversation.context_id = context_property_id
        # Never silently reactivate a blocked conversation — a block must be
        # lifted explicitly via the unblock flow, not undone by a swipe or a
        # new conversation request. (Callers should also reject blocked pairs
        # upfront via _is_blocked, but guard here too as defense-in-depth.)
        if conversation.status not in (
            ConversationStatus.active,
            ConversationStatus.blocked,
        ):
            conversation.status = ConversationStatus.active
        if source == ConversationSource.profile_match:
            conversation.source = ConversationSource.profile_match
        return conversation

    # Create new conversation + two participants
    conversation = Conversation(
        app=ConversationApp.flatmates,
        created_by_user_id=created_by_user_id,
        source=source,
        context_type="property" if context_property_id is not None else None,
        context_id=context_property_id,
    )
    db.add(conversation)
    await db.flush()

    for uid in (user_id, other_user_id):
        db.add(
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=uid,
                joined_at=datetime.now(timezone.utc),
            )
        )
    await db.flush()
    return conversation


async def _match_created_at(
    db: AsyncSession,
    user_id: int,
    peer_id: int,
) -> datetime | None:
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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

    # Refuse to open (or reopen) a conversation when either party has blocked
    # the other — mirrors the block guard on the swipe/like paths in matching.py.
    if await _is_blocked(db, user_id, payload.peer_user_id):
        raise ForbiddenException(detail="You can't start a conversation with this user")

    conversation = await _ensure_conversation(
        db,
        user_id=user_id,
        other_user_id=payload.peer_user_id,
        created_by_user_id=user_id,
        source=ConversationSource.profile_match,
    )

    if payload.initial_message and payload.initial_message.strip():
        message = Message(
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


async def get_conversation_summary(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> dict[str, Any]:
    current_user = await db.get(User, user_id)
    conversation = await get_conversation(db, conversation_id, user_id)
    peer_id = await _find_participant_peer_id(db, conversation.id, user_id)
    if peer_id is None:
        raise BadRequestException(detail="Conversation not found")

    peer = await db.get(User, peer_id)
    if peer is None:
        raise BadRequestException(detail="Conversation not found")

    context_property = await _get_context_property(db, conversation)

    unread_count_stmt = select(func.count(Message.id)).where(
        Message.conversation_id == conversation.id,
        Message.sender_id != user_id,
        Message.read_at.is_(None),
    )
    unread_count = int((await db.execute(unread_count_stmt)).scalar() or 0)

    return {
        "id": conversation.id,
        "source": conversation.source,
        "status": conversation.status,
        "peer": _build_peer_payload(peer, current_user),
        "context_property": _build_property_context(context_property),
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

    # Find conversation IDs the user participates in (flatmates app only)
    conv_id_subq = (
        select(ConversationParticipant.conversation_id)
        .join(Conversation, Conversation.id == ConversationParticipant.conversation_id)
        .where(
            ConversationParticipant.user_id == user_id,
            Conversation.app == ConversationApp.flatmates,
        )
    )

    total: int | None = None
    if with_total:
        total = (
            await db.execute(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.id.in_(conv_id_subq))
            )
        ).scalar_one()

    stmt = (
        select(Conversation)
        .where(Conversation.id.in_(conv_id_subq))
        .order_by(func.coalesce(Conversation.last_message_at, Conversation.created_at).desc())
        .offset(offset)
        .limit(limit + 1)
    )
    conversations = list((await db.execute(stmt)).scalars().all())
    has_more = len(conversations) > limit
    conversations = conversations[:limit]
    next_payload = offset_payload(offset + limit) if has_more else None

    if not conversations:
        return [], next_payload, total

    # Bulk-load all participants for these conversations
    conv_ids = [conv.id for conv in conversations]
    participant_rows = list(
        (
            await db.execute(
                select(ConversationParticipant.conversation_id, ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id.in_(conv_ids),
                    ConversationParticipant.user_id != user_id,
                )
            )
        )
        .all()
    )
    peer_by_conv: dict[int, int] = {
        row.conversation_id: row.user_id for row in participant_rows
    }

    # Bulk-load context properties (flatmates context_type='property')
    property_ids = {
        conv.context_id
        for conv in conversations
        if conv.context_type == "property" and conv.context_id is not None
    }
    property_map: dict[int, Property] = {}
    if property_ids:
        prop_rows = list(
            (await db.execute(select(Property).where(Property.id.in_(property_ids)))).scalars().all()
        )
        property_map = {p.id: p for p in prop_rows}

    peer_ids = set(peer_by_conv.values())
    users_stmt = select(User).where(User.id.in_(peer_ids))
    users = list((await db.execute(users_stmt)).scalars().all())
    user_map = {user.id: user for user in users}

    unread_stmt = (
        select(Message.conversation_id, func.count(Message.id))
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.sender_id != user_id,
            Message.read_at.is_(None),
        )
        .group_by(Message.conversation_id)
    )
    unread_rows = (await db.execute(unread_stmt)).all()
    unread_map = {conversation_id: int(count) for conversation_id, count in unread_rows}

    # Bulk load matches
    match_stmt = select(UserMatch).where(
        (UserMatch.user_one_id == user_id) | (UserMatch.user_two_id == user_id),
    )
    matches = list((await db.execute(match_stmt)).scalars().all())
    match_created_at_map: dict[int, datetime] = {}
    match_id_map: dict[int, int] = {}
    for match in matches:
        match_peer_id = match.user_one_id if match.user_two_id == user_id else match.user_two_id
        match_created_at_map[match_peer_id] = match.created_at
        match_id_map[match_peer_id] = match.id

    # Bulk load QnA
    qna_map: dict[int, dict[str, Any] | None] = {}
    if match_id_map:
        qna_stmt = select(MatchQnAAnswer).where(
            MatchQnAAnswer.match_id.in_(list(match_id_map.values()))
        )
        qna_answers = list((await db.execute(qna_stmt)).scalars().all())
        from collections import defaultdict

        qna_by_match: dict[int, list[MatchQnAAnswer]] = defaultdict(list)
        for ans in qna_answers:
            qna_by_match[ans.match_id].append(ans)

        for match_peer_id, mid in match_id_map.items():
            answers = qna_by_match.get(mid, [])
            answer_map = {ans.user_id: ans for ans in answers}
            cu_ans = _build_qna_answer_payload(answer_map.get(user_id))
            peer_ans = _build_qna_answer_payload(answer_map.get(match_peer_id))
            if cu_ans is None and peer_ans is None:
                qna_map[match_peer_id] = None
            else:
                qna_map[match_peer_id] = {
                    "current_user": cu_ans,
                    "peer": peer_ans,
                    "both_answered": cu_ans is not None and peer_ans is not None,
                }

    items: list[dict[str, Any]] = []
    for conversation in conversations:
        peer_id = peer_by_conv.get(conversation.id)
        if peer_id is None:
            continue
        peer = user_map.get(peer_id)
        if peer is None:
            continue
        context_property = None
        if conversation.context_type == "property" and conversation.context_id is not None:
            context_property = property_map.get(conversation.context_id)
        items.append(
            {
                "id": conversation.id,
                "source": conversation.source,
                "status": conversation.status,
                "peer": _build_peer_payload(peer, current_user),
                "context_property": _build_property_context(context_property),
                "last_message_preview": conversation.last_message_preview,
                "last_message_at": conversation.last_message_at,
                "unread_count": unread_map.get(conversation.id, 0),
                "matched_at": match_created_at_map.get(peer_id),
                "qna": qna_map.get(peer_id),
            }
        )
    return items, next_payload, total


async def find_1to1_conversation(
    db: AsyncSession,
    user_id: int,
    other_user_id: int,
) -> Conversation | None:
    """Find the flatmates conversation between two specific users (if any)."""
    user_conv_ids = select(ConversationParticipant.conversation_id).where(
        ConversationParticipant.user_id == user_id
    )
    other_conv_ids = select(ConversationParticipant.conversation_id).where(
        ConversationParticipant.user_id == other_user_id
    )
    conv_id = (
        await db.execute(
            select(ConversationParticipant.conversation_id)
            .where(
                ConversationParticipant.conversation_id.in_(user_conv_ids),
                ConversationParticipant.conversation_id.in_(other_conv_ids),
            )
            .group_by(ConversationParticipant.conversation_id)
            .having(func.count() == 2)
            .limit(1)
        )
    ).scalar_one_or_none()
    if conv_id is None:
        return None
    return await db.get(Conversation, conv_id)


async def get_conversation(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise BadRequestException(detail="Conversation not found")
    # Verify the user is a participant
    is_participant = (
        await db.execute(
            select(ConversationParticipant.id).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if is_participant is None:
        raise BadRequestException(detail="Conversation not found")
    return conversation


async def list_messages(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
    *,
    limit: int = 50,
    before_id: int | None = None,
    mark_read: bool = True,
) -> tuple[list[Message], bool]:
    """Return a chronologically-ordered page of messages.

    The function is intentionally READ-ONLY: scroll-back via ``before_id`` would
    otherwise silently mark every old message on the page as read, firing
    spurious read-receipts and destroying unread state. The "I have seen the
    bottom of the conversation" read marker is set by the explicit
    ``mark_conversation_read`` endpoint / ``mark_read=True`` argument (which
    only the first / most-recent page should pass).

    ``limit`` is clamped to [1, 200] and ``before_id`` to >= 1 as
    defense-in-depth: the FastAPI layer already constrains these via Query(),
    but a direct service-level caller (or a future refactor) must not be
    able to trigger the infinite-loop bug by passing limit=0.
    """
    limit = max(1, min(int(limit), 200))
    if before_id is not None and before_id < 1:
        before_id = None
    await get_conversation(db, conversation_id, user_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit + 1)
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    # Return in chronological order
    messages = list(reversed(rows))

    # Only mark unread messages as read when this is the newest page (no
    # before_id) and the caller explicitly opts in. Backward pagination must
    # never touch read state.
    if mark_read and before_id is None and messages:
        now = datetime.now(timezone.utc)
        for message in messages:
            if message.sender_id != user_id and message.read_at is None:
                message.read_at = now
        await db.flush()
    return messages, has_more


async def send_message(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
    payload: MessageCreate,
) -> Message:
    conversation = await get_conversation(db, conversation_id, user_id)
    if conversation.status != ConversationStatus.active:
        raise BadRequestException(detail="Conversation is not active")

    body = payload.body.strip() if payload.body else None
    attachment_url = payload.attachment_url
    if attachment_url is not None and not ValidationUtils.is_absolute_url(attachment_url):
        logger.warning(
            "Non-absolute attachment_url in conversation %s from user %s: %s",
            conversation_id,
            user_id,
            attachment_url,
        )
    message = Message(
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
    peer_id = await _find_participant_peer_id(db, conversation.id, user_id)

    if peer_id is not None and not await _is_blocked(db, user_id, peer_id):
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

    return message


async def mark_conversation_read(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
) -> dict[str, str]:
    """Mark all peer messages in a conversation as read."""
    await get_conversation(db, conversation_id, user_id)

    now = datetime.now(timezone.utc)
    await db.execute(
        update(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.sender_id != user_id,
            Message.read_at.is_(None),
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
    # Verify the user is a participant
    conversation = await get_conversation(db, conversation_id, user_id)
    peer_id = await _find_participant_peer_id(db, conversation_id, user_id)
    if peer_id is None:
        raise NotFoundException(detail="Conversation peer not found")

    user_one_id, user_two_id = _canonical_pair(user_id, peer_id)

    match_result = await db.execute(
        select(UserMatch).where(
            UserMatch.user_one_id == user_one_id,
            UserMatch.user_two_id == user_two_id,
        )
    )
    user_match = match_result.scalar_one_or_none()

    context_property_id = (
        conversation.context_id if conversation.context_type == "property" else None
    )
    if not user_match:
        user_match = UserMatch(
            user_one_id=user_one_id,
            user_two_id=user_two_id,
            context_property_id=context_property_id,
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
        # Use a savepoint so that a concurrent-insert IntegrityError does not
        # roll back the UserMatch that was already flushed above.
        try:
            async with db.begin_nested():
                qna_answer = MatchQnAAnswer(
                    match_id=user_match.id,
                    user_id=user_id,
                )
                db.add(qna_answer)
                await db.flush()
        except IntegrityError:
            # Another request inserted the row concurrently; re-fetch it.
            existing = await db.execute(
                select(MatchQnAAnswer).where(
                    MatchQnAAnswer.match_id == user_match.id,
                    MatchQnAAnswer.user_id == user_id,
                )
            )
            qna_answer = existing.scalar_one_or_none()
            if qna_answer is None:
                raise NotFoundException(detail="QnA answer could not be created") from None

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
