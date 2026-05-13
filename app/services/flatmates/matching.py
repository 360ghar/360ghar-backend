"""Swipe, match, and compatibility logic."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestException
from app.core.logging import get_logger
from app.models.enums import (
    ConversationSource,
    ConversationStatus,
    PropertyType,
    SwipeAction,
    SwipeTargetType,
    UserMatchStatus,
)
from app.models.properties import Property
from app.models.social import FlatmateSuperLikeUsage, UserConversation, UserMatch
from app.models.users import User, UserSwipe
from app.schemas.flatmates import SwipeRequest
from app.services.flatmates.conversations import _ensure_conversation
from app.services.flatmates.helpers import (
    _build_peer_payload,
    _build_property_context,
    _canonical_pair,
    _ensure_match,
    _is_blocked,
)

logger = get_logger(__name__)
SUPER_LIKE_DAILY_CAP = 3


async def _consume_super_like_quota(
    db: AsyncSession,
    *,
    user_id: int,
    target_user_id: int,
    existing_swipe: UserSwipe | None = None,
) -> None:
    if existing_swipe and existing_swipe.swipe_action == SwipeAction.super_like.value:
        return

    used_on = datetime.now(timezone.utc).date()
    existing_usage_stmt = select(FlatmateSuperLikeUsage.id).where(
        FlatmateSuperLikeUsage.user_id == user_id,
        FlatmateSuperLikeUsage.target_user_id == target_user_id,
        FlatmateSuperLikeUsage.used_on == used_on,
    )
    existing_usage = (await db.execute(existing_usage_stmt)).scalar_one_or_none()
    if existing_usage is not None:
        return

    count_stmt = select(func.count(FlatmateSuperLikeUsage.id)).where(
        FlatmateSuperLikeUsage.user_id == user_id,
        FlatmateSuperLikeUsage.used_on == used_on,
    )
    used_count = int((await db.execute(count_stmt)).scalar() or 0)
    if used_count >= SUPER_LIKE_DAILY_CAP:
        raise BadRequestException(detail="Daily super like limit reached")

    db.add(
        FlatmateSuperLikeUsage(
            user_id=user_id,
            target_user_id=target_user_id,
            used_on=used_on,
        )
    )


async def record_swipe(
    db: AsyncSession,
    user_id: int,
    payload: SwipeRequest,
) -> dict[str, Any]:
    positive_actions = {SwipeAction.like.value, SwipeAction.super_like.value}
    is_liked = payload.action.value in positive_actions

    if payload.target_type == SwipeTargetType.property:
        property_obj = await db.get(Property, payload.property_id)
        if property_obj is None:
            raise BadRequestException(detail="Property not found")
        if property_obj.property_type in {PropertyType.flatmate, PropertyType.pg}:
            preferences = (
                property_obj.listing_preferences
                if isinstance(property_obj.listing_preferences, dict)
                else {}
            )
            if (
                not property_obj.is_available
                or preferences.get("moderation_status", "live") != "live"
            ):
                raise BadRequestException(detail="Property not found")
        if property_obj.owner_id == user_id:
            raise BadRequestException(detail="Cannot swipe your own listing")
        if await _is_blocked(db, user_id, property_obj.owner_id):
            raise BadRequestException(detail="Conversation is blocked")

        stmt = select(UserSwipe).where(
            UserSwipe.user_id == user_id,
            UserSwipe.property_id == payload.property_id,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        was_liked = existing.is_liked if existing else False
        if existing:
            existing.target_type = payload.target_type.value
            existing.swipe_action = payload.action.value
            existing.is_liked = is_liked
            existing.context_property_id = payload.context_property_id
        else:
            db.add(
                UserSwipe(
                    user_id=user_id,
                    property_id=payload.property_id,
                    target_type=payload.target_type.value,
                    swipe_action=payload.action.value,
                    context_property_id=payload.context_property_id,
                    is_liked=is_liked,
                )
            )

        conversation_id = None
        if is_liked:
            conversation = await _ensure_conversation(
                db,
                user_id=user_id,
                other_user_id=property_obj.owner_id,
                created_by_user_id=user_id,
                source=ConversationSource.listing_interest.value,
                context_property_id=payload.property_id,
            )
            conversation_id = conversation.id
            if not was_liked:
                property_obj.interest_count = (property_obj.interest_count or 0) + 1

        await db.flush()
        return {
            "stored": True,
            "action": payload.action,
            "target_type": payload.target_type,
            "conversation_id": conversation_id,
            "match_id": None,
            "did_match": False,
        }

    target_user = await db.get(User, payload.target_user_id)
    if target_user is None:
        raise BadRequestException(detail="User not found")
    if target_user.id == user_id:
        raise BadRequestException(detail="Cannot swipe your own profile")
    if await _is_blocked(db, user_id, target_user.id):
        raise BadRequestException(detail="Conversation is blocked")

    stmt = select(UserSwipe).where(
        UserSwipe.user_id == user_id,
        UserSwipe.target_user_id == payload.target_user_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if payload.action == SwipeAction.super_like:
        assert payload.target_user_id is not None
        await _consume_super_like_quota(
            db,
            user_id=user_id,
            target_user_id=payload.target_user_id,
            existing_swipe=existing,
        )
    if existing:
        existing.target_type = payload.target_type.value
        existing.swipe_action = payload.action.value
        existing.is_liked = is_liked
        existing.context_property_id = payload.context_property_id
    else:
        db.add(
            UserSwipe(
                user_id=user_id,
                target_user_id=payload.target_user_id,
                target_type=payload.target_type.value,
                swipe_action=payload.action.value,
                context_property_id=payload.context_property_id,
                is_liked=is_liked,
            )
        )

    did_match = False
    match_id = None
    conversation_id = None
    if is_liked:
        reciprocal_stmt = select(UserSwipe).where(
            UserSwipe.user_id == payload.target_user_id,
            UserSwipe.target_user_id == user_id,
            UserSwipe.is_liked.is_(True),
        )
        reciprocal = (await db.execute(reciprocal_stmt)).scalar_one_or_none()
        if reciprocal:
            assert payload.target_user_id is not None
            match = await _ensure_match(
                db,
                user_id=user_id,
                other_user_id=payload.target_user_id,
                context_property_id=payload.context_property_id,
            )
            conversation = await _ensure_conversation(
                db,
                user_id=user_id,
                other_user_id=payload.target_user_id,
                created_by_user_id=user_id,
                source=ConversationSource.profile_match,
                context_property_id=payload.context_property_id,
            )
            did_match = True
            match_id = match.id
            conversation_id = conversation.id

            # --- Push notifications to both users ---
            try:
                from app.services.push_notification import notify_new_match

                swiper = await db.get(User, user_id)
                target = await db.get(User, payload.target_user_id)
                swiper_name = swiper.full_name or "Someone" if swiper else "Someone"
                target_name = target.full_name or "Someone" if target else "Someone"
                assert payload.target_user_id is not None
                await notify_new_match(
                    db,
                    recipient_db_id=payload.target_user_id,
                    peer_name=swiper_name,
                    match_id=match_id,
                )
                await notify_new_match(
                    db,
                    recipient_db_id=user_id,
                    peer_name=target_name,
                    match_id=match_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Match notification failed (best-effort): %s", exc, exc_info=True)
                pass  # best-effort; never block swipe recording

            # --- SSE events for new match ---
            try:
                from app.core.sse import sse_bus

                for uid in (user_id, payload.target_user_id):
                    if uid is not None:
                        await sse_bus.emit(
                        uid,
                        {"type": "new_match", "match_id": match_id, "conversation_id": conversation_id},
                    )
            except Exception:  # noqa: BLE001
                pass  # best-effort

    await db.flush()
    return {
        "stored": True,
        "action": payload.action,
        "target_type": payload.target_type,
        "conversation_id": conversation_id,
        "match_id": match_id,
        "did_match": did_match,
    }


async def list_incoming_likes(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return positive profile swipes the current user has not answered yet."""
    current_user = await db.get(User, user_id)
    answered_target_ids = select(UserSwipe.target_user_id).where(
        UserSwipe.user_id == user_id,
        UserSwipe.target_user_id.is_not(None),
    )
    stmt = (
        select(UserSwipe)
        .options(selectinload(UserSwipe.user), selectinload(UserSwipe.context_property))
        .where(
            UserSwipe.target_type == SwipeTargetType.user.value,
            UserSwipe.target_user_id == user_id,
            UserSwipe.is_liked.is_(True),
            ~UserSwipe.user_id.in_(answered_target_ids),
        )
        .order_by(UserSwipe.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    incoming_swipes = list((await db.execute(stmt)).scalars().all())

    items: list[dict[str, Any]] = []
    for swipe in incoming_swipes:
        if swipe.user is None or await _is_blocked(db, user_id, swipe.user_id):
            continue
        items.append(
            {
                "id": swipe.id,
                "peer": _build_peer_payload(swipe.user, current_user),
                "context_property": _build_property_context(swipe.context_property),
                "created_at": swipe.created_at,
            }
        )
    return items


async def list_matches(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    current_user = await db.get(User, user_id)
    stmt = (
        select(UserMatch)
        .options(selectinload(UserMatch.context_property))
        .where(
            or_(UserMatch.user_one_id == user_id, UserMatch.user_two_id == user_id),
            UserMatch.status == UserMatchStatus.active,
        )
        .order_by(UserMatch.created_at.desc())
    )
    matches = list((await db.execute(stmt)).scalars().all())
    if not matches:
        return []

    peer_ids = {
        match.user_two_id if match.user_one_id == user_id else match.user_one_id
        for match in matches
    }
    users = list((await db.execute(select(User).where(User.id.in_(peer_ids)))).scalars().all())
    user_map = {user.id: user for user in users}

    items: list[dict[str, Any]] = []
    for match in matches:
        peer_id = match.user_two_id if match.user_one_id == user_id else match.user_one_id
        peer = user_map.get(peer_id)
        if peer is None:
            continue
        items.append(
            {
                "id": match.id,
                "status": match.status,
                "peer": _build_peer_payload(peer, current_user),
                "context_property": _build_property_context(match.context_property),
                "created_at": match.created_at,
            }
        )
    return items


async def unmatch_user_pair(db: AsyncSession, user_id: int, other_user_id: int) -> dict[str, Any]:
    """Unmatch a pair without creating a hard block."""
    if user_id == other_user_id:
        raise BadRequestException(detail="Cannot unmatch yourself")
    other = await db.get(User, other_user_id)
    if other is None:
        raise BadRequestException(detail="User not found")

    user_one_id, user_two_id = _canonical_pair(user_id, other_user_id)
    match_stmt = select(UserMatch).where(
        UserMatch.user_one_id == user_one_id,
        UserMatch.user_two_id == user_two_id,
    )
    match = (await db.execute(match_stmt)).scalar_one_or_none()
    if match is None:
        raise BadRequestException(detail="Match not found")
    if match.status == UserMatchStatus.unmatched:
        return {"id": match.id, "status": match.status, "unmatched": True}

    match.status = UserMatchStatus.unmatched
    conversation_stmt = select(UserConversation).where(
        UserConversation.user_one_id == user_one_id,
        UserConversation.user_two_id == user_two_id,
    )
    conversation = (await db.execute(conversation_stmt)).scalar_one_or_none()
    if conversation:
        conversation.status = ConversationStatus.closed
    await db.flush()
    return {"id": match.id, "status": match.status, "unmatched": True}


async def unmatch_match(db: AsyncSession, user_id: int, match_id: int) -> dict[str, Any]:
    """Set a match to unmatched and close the associated conversation."""
    match = await db.get(UserMatch, match_id)
    if match is None:
        raise BadRequestException(detail="Match not found")
    if user_id not in {match.user_one_id, match.user_two_id}:
        raise BadRequestException(detail="Match not found")
    if match.status == UserMatchStatus.unmatched:
        raise BadRequestException(detail="Match is already unmatched")

    match.status = UserMatchStatus.unmatched

    # Close the associated conversation
    user_one_id, user_two_id = match.user_one_id, match.user_two_id
    conversation_stmt = select(UserConversation).where(
        UserConversation.user_one_id == user_one_id,
        UserConversation.user_two_id == user_two_id,
    )
    conversation = (await db.execute(conversation_stmt)).scalar_one_or_none()
    if conversation:
        conversation.status = ConversationStatus.closed

    await db.flush()
    return {"id": match.id, "status": match.status, "unmatched": True}
