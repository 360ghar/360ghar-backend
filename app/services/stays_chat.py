"""Guest and host chat for one booking.

Uses the generic conversations tables with app='stays', context_type='booking' and
context_id=booking id. Only the guest and the property owner (the host) may read or write.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.models.bookings import Booking
from app.models.conversations import Conversation, ConversationParticipant, Message
from app.models.enums import ConversationApp, ConversationSource, ConversationStatus, MessageType
from app.models.properties import Property
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead, validate_keyset_payload


async def _booking_party(
    db: AsyncSession, booking_id: int, user_id: int
) -> tuple[Booking, int | None]:
    """Return the booking and its host id. Raise 404 unless the user is the guest or the host."""
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise NotFoundException(detail="Booking not found", error_code="BOOKING_NOT_FOUND")
    host_id = (
        await db.execute(select(Property.owner_id).where(Property.id == booking.property_id))
    ).scalar_one_or_none()
    if user_id not in {booking.user_id, host_id}:
        raise NotFoundException(detail="Booking not found", error_code="BOOKING_NOT_FOUND")
    return booking, host_id


async def _find_thread(db: AsyncSession, booking_id: int) -> Conversation | None:
    return (
        (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.app == ConversationApp.stays,
                    Conversation.context_type == "booking",
                    Conversation.context_id == booking_id,
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def _open_thread(db: AsyncSession, booking: Booking, host_id: int | None) -> Conversation:
    conversation = await _find_thread(db, booking.id)
    if conversation is not None:
        return conversation
    conversation = Conversation(
        app=ConversationApp.stays,
        created_by_user_id=booking.user_id,
        source=ConversationSource.booking_inquiry,
        context_type="booking",
        context_id=booking.id,
    )
    now = datetime.now(timezone.utc)
    try:
        # The unique index uq_conversations_stays_booking rejects a second thread. A savepoint
        # keeps the caller's transaction alive so the winner's thread can be loaded.
        async with db.begin_nested():
            db.add(conversation)
            await db.flush()
            for uid in {booking.user_id, host_id} - {None}:
                db.add(
                    ConversationParticipant(
                        conversation_id=conversation.id, user_id=uid, joined_at=now
                    )
                )
            await db.flush()
    except IntegrityError:
        existing = await _find_thread(db, booking.id)
        if existing is None:
            raise
        return existing
    return conversation


async def list_booking_messages(
    db: AsyncSession,
    booking_id: int,
    user_id: int,
    *,
    cursor_payload: dict[str, Any],
    limit: int,
    with_total: bool = False,
) -> tuple[list[Message], dict[str, Any] | None, int | None]:
    """One page of messages, newest first, and the total when ``with_total`` is set.

    A booking with no thread has no messages.
    """
    validate_keyset_payload(cursor_payload, "datetime")
    await _booking_party(db, booking_id, user_id)
    thread = await _find_thread(db, booking_id)
    if thread is None:
        return [], None, 0 if with_total else None
    total: int | None = None
    if with_total:
        total = (
            await db.execute(
                select(func.count(Message.id)).where(Message.conversation_id == thread.id)
            )
        ).scalar_one()
    stmt = (
        select(Message)
        .where(Message.conversation_id == thread.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit + 1)
    )
    predicate = keyset_filter(Message.created_at, Message.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    rows = list((await db.execute(stmt)).scalars().all())
    page, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda message: message.created_at,
        item_id=lambda message: message.id,
    )
    return page, next_payload, total


async def send_booking_message(
    db: AsyncSession, booking_id: int, user_id: int, body: str
) -> Message:
    booking, host_id = await _booking_party(db, booking_id, user_id)
    thread = await _open_thread(db, booking, host_id)
    if thread.status != ConversationStatus.active:
        raise BadRequestException(detail="Conversation is not active")
    message = Message(
        conversation_id=thread.id,
        sender_id=user_id,
        body=body,
        message_type=MessageType.text,
    )
    db.add(message)
    thread.last_message_at = datetime.now(timezone.utc)
    thread.last_message_preview = body[:200]
    await db.flush()
    await db.refresh(message)
    await db.commit()
    return message
