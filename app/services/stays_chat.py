"""Guest and host chat for one booking.

Uses the generic conversations tables with app='stays', context_type='booking' and
context_id=booking id. Only the guest and the property owner (the host) may read or write.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.bookings import Booking
from app.models.conversations import Conversation, ConversationParticipant, Message
from app.models.enums import ConversationApp, ConversationSource, MessageType
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
    # ponytail: no unique index on (app, context_type, context_id). Two first messages sent at
    # the same moment can open two threads. Add a partial unique index if this matters.
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
    db.add(conversation)
    await db.flush()
    now = datetime.now(timezone.utc)
    for uid in {booking.user_id, host_id} - {None}:
        db.add(ConversationParticipant(conversation_id=conversation.id, user_id=uid, joined_at=now))
    await db.flush()
    return conversation


async def list_booking_messages(
    db: AsyncSession,
    booking_id: int,
    user_id: int,
    *,
    cursor_payload: dict[str, Any],
    limit: int,
) -> tuple[list[Message], dict[str, Any] | None]:
    """One page of messages, newest first. A booking with no thread has no messages."""
    validate_keyset_payload(cursor_payload, "datetime")
    await _booking_party(db, booking_id, user_id)
    thread = await _find_thread(db, booking_id)
    if thread is None:
        return [], None
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
    return trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda message: message.created_at,
        item_id=lambda message: message.id,
    )


async def send_booking_message(
    db: AsyncSession, booking_id: int, user_id: int, body: str
) -> Message:
    booking, host_id = await _booking_party(db, booking_id, user_id)
    thread = await _open_thread(db, booking, host_id)
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
