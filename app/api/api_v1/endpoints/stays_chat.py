"""Booking chat for the stays app. Mounted under /bookings.

GET and POST /bookings/{booking_id}/messages. The guest and the property host may use it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_cached_active_user
from app.core.database import get_db
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.stays_chat import BookingMessageCreate, BookingMessageOut
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.stays_chat import list_booking_messages, send_booking_message

router = APIRouter()


@router.get(
    "/{booking_id}/messages",
    response_model=CursorPage[BookingMessageOut],
    summary="List booking chat messages",
)
async def list_messages(
    booking_id: int,
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Messages in the booking chat, newest first. Only the guest and the host."""
    binding: dict[str, Any] = {"booking_id": booking_id}
    rows, next_payload = await list_booking_messages(
        db,
        booking_id,
        current_user.id,
        cursor_payload=page.decoded(binding),
        limit=page.limit,
    )
    return build_cursor_page(
        [BookingMessageOut.model_validate(row) for row in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=None,
        filters=binding,
    )


@router.post(
    "/{booking_id}/messages",
    response_model=BookingMessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Send a booking chat message",
)
async def send_message(
    booking_id: int,
    body: BookingMessageCreate,
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
) -> BookingMessageOut:
    """Send a message in the booking chat. Only the guest and the host."""
    message = await send_booking_message(db, booking_id, current_user.id, body.body)
    return BookingMessageOut.model_validate(message)
