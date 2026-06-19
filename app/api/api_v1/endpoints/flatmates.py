from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.api_v1.dependencies.auth import get_current_active_user, get_current_user_sse
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.flatmates import (
    BlockCreate,
    BlockedUserOut,
    BlockOut,
    CatalogEntry,
    ConversationCreate,
    ConversationSummary,
    FlatmatesBootstrap,
    FlatmatesNotificationOut,
    FlatmatesNotificationUpdate,
    FlatmatesPeer,
    FlatmatesProfile,
    FlatmatesProfileUpdate,
    FlatmateVisitUpdate,
    IncomingLikeSummary,
    MatchSummary,
    MessageCreate,
    MessageListResponse,
    MessageOut,
    ProfileViewEventCreate,
    ProfileViewEventOut,
    QnAAnswers,
    ReportCreate,
    ReportOut,
    SocietyTagVoteCreate,
    SocietyTagVoteOut,
    SwipeRequest,
    SwipeResult,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import User as UserSchema
from app.services.flatmates import (
    create_block,
    create_conversation_from_payload,
    create_report,
    delete_block,
    get_bootstrap,
    get_conversation_summary,
    get_flatmates_profile,
    get_profile_by_id,
    list_blocks,
    list_catalogs,
    list_conversations,
    list_discoverable_profiles,
    list_flatmates_notifications,
    list_incoming_likes,
    list_matches,
    list_messages,
    list_outgoing_likes,
    mark_all_flatmates_notifications_read,
    mark_conversation_read,
    mark_flatmates_notification_read,
    record_profile_view_event,
    record_society_tag_vote,
    record_swipe,
    save_match_qna_answers,
    send_message,
    unmatch_match,
    unmatch_user_pair,
    update_flatmates_profile,
)

logger = get_logger(__name__)

router = APIRouter()


@router.get("/sse", summary="Stream flatmates events (SSE)")
async def flatmates_sse(
    current_user: UserSchema = Depends(get_current_user_sse),
):
    """SSE stream for flatmates real-time events."""
    from app.core.sse import SSESubscriberLimitError, sse_bus

    user_id = current_user.id
    try:
        queue = await sse_bus.subscribe(user_id)
    except SSESubscriberLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many real-time subscribers. Please retry shortly.",
        ) from exc

    async def event_stream():
        try:
            yield "event: connected\ndata: {\"status\":\"ok\"}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=60)
                    await sse_bus.touch(queue)
                    event_type = event.get("type", "update")
                    payload = json.dumps(event, default=str)
                    yield f"event: {event_type}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    await sse_bus.touch(queue)
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await sse_bus.unsubscribe(user_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/bootstrap", response_model=FlatmatesBootstrap, summary="Get flatmates bootstrap")
async def get_flatmates_bootstrap(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get flatmates bootstrap."""
    return await get_bootstrap(db, current_user.id)


@router.get("/catalogs", response_model=list[CatalogEntry], summary="Get flatmates catalogs")
async def get_flatmates_catalogs(
    db: AsyncSession = Depends(get_db),
):
    """Get flatmates catalogs."""
    return await list_catalogs(db)


@router.get("/profile", response_model=FlatmatesProfile, summary="Get current flatmate profile")
async def get_profile(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current flatmate profile."""
    return await get_flatmates_profile(db, current_user.id)


@router.put("/profile", response_model=FlatmatesProfile, summary="Update flatmate profile")
async def update_profile(
    payload: FlatmatesProfileUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update flatmate profile."""
    return await update_flatmates_profile(db, current_user.id, payload)


@router.patch("/profile", response_model=FlatmatesProfile, summary="Patch flatmate profile")
async def patch_profile(
    payload: FlatmatesProfileUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch flatmate profile."""
    return await update_flatmates_profile(db, current_user.id, payload)


@router.post("/profile", response_model=FlatmatesProfile, summary="Create flatmate profile")
async def create_profile(
    payload: FlatmatesProfileUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create flatmate profile."""
    return await update_flatmates_profile(db, current_user.id, payload)


@router.get("/profiles/{user_id}", response_model=FlatmatesPeer, summary="Get flatmate profile by user")
async def get_user_profile(
    user_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get flatmate profile by user."""
    return await get_profile_by_id(db, user_id, current_user_id=current_user.id)


@router.get("/profiles", response_model=CursorPage[FlatmatesPeer], summary="Discover flatmate profiles")
async def get_discoverable_profiles(
    city: str | None = Query(default=None),
    budget_min: int | None = Query(default=None),
    budget_max: int | None = Query(default=None),
    move_in: str | None = Query(
        default=None,
        description="Move-in timeline: immediate, this_month, next_month, flexible",
    ),
    lat: float | None = Query(default=None, description="Latitude for geo filtering"),
    lng: float | None = Query(default=None, description="Longitude for geo filtering"),
    radius: float | None = Query(default=None, description="Radius in km for geo filtering"),
    non_negotiables: str | None = Query(
        default=None,
        description="Comma-separated non-negotiable deal-breakers",
    ),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Discover flatmate profiles."""
    parsed_non_neg: list[str] | None = None
    if non_negotiables:
        parsed_non_neg = [n.strip() for n in non_negotiables.split(",") if n.strip()]
    profiles, next_payload, total = await list_discoverable_profiles(
        db,
        current_user.id,
        city=city,
        budget_min=budget_min,
        budget_max=budget_max,
        move_in=move_in,
        lat=lat,
        lng=lng,
        radius=radius,
        non_negotiables_override=parsed_non_neg,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [FlatmatesPeer.model_validate(p) for p in profiles],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.post("/swipes", response_model=SwipeResult, summary="Swipe flatmate profile")
async def swipe(
    payload: SwipeRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Swipe flatmate profile."""
    return await record_swipe(db, current_user.id, payload)


@router.get("/likes", response_model=CursorPage[IncomingLikeSummary], summary="List incoming likes")
async def get_incoming_likes(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List incoming likes."""
    rows, next_payload, total = await list_incoming_likes(
        db,
        current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [IncomingLikeSummary.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.get("/outgoing-likes", response_model=CursorPage[IncomingLikeSummary], summary="List outgoing likes")
async def get_outgoing_likes(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List outgoing likes."""
    rows, next_payload, total = await list_outgoing_likes(
        db,
        current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [IncomingLikeSummary.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.post("/profile-views", response_model=ProfileViewEventOut, summary="Record profile view")
async def record_profile_view(
    payload: ProfileViewEventCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Record profile view."""
    return await record_profile_view_event(db, current_user.id, payload)


@router.post("/listings/{listing_id}/society-tags/votes", response_model=SocietyTagVoteOut, summary="Vote on society tag")
async def vote_society_tag(
    listing_id: int,
    payload: SocietyTagVoteCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Vote on society tag."""
    return await record_society_tag_vote(db, current_user.id, listing_id, payload)


@router.get("/conversations", response_model=CursorPage[ConversationSummary], summary="List conversations")
async def get_conversations(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversations."""
    rows, next_payload, total = await list_conversations(
        db,
        current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [ConversationSummary.model_validate(c) for c in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.post("/conversations", response_model=ConversationSummary, summary="Create conversation")
async def create_conversation(
    payload: ConversationCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create conversation."""
    return await create_conversation_from_payload(db, current_user.id, payload)


@router.get("/conversations/{conversation_id}", response_model=ConversationSummary, summary="Get conversation detail")
async def get_conversation_detail(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation detail."""
    return await get_conversation_summary(db, conversation_id, current_user.id)


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse, summary="List conversation messages")
async def get_conversation_messages(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversation messages."""
    messages = await list_messages(db, conversation_id, current_user.id)
    return MessageListResponse(messages=messages, total=len(messages), has_more=False)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, summary="Send conversation message")
async def post_conversation_message(
    conversation_id: int,
    payload: MessageCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Send conversation message."""
    return await send_message(db, conversation_id, current_user.id, payload)


@router.get("/matches", response_model=CursorPage[MatchSummary], summary="List matches")
async def get_matches(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List matches."""
    rows, next_payload, total = await list_matches(
        db,
        current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [MatchSummary.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.put("/matches/{match_id}/unmatch", summary="Unmatch conversation")
async def unmatch(
    match_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Unmatch conversation."""
    return await unmatch_match(db, current_user.id, match_id)


@router.get("/blocks", response_model=CursorPage[BlockedUserOut], summary="List blocked users")
async def get_blocked_users(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List blocked users."""
    rows, next_payload, total = await list_blocks(
        db,
        current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [BlockedUserOut.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.delete("/blocks/{blocked_user_id}", response_model=dict[str, Any], summary="Unblock user")
async def unblock_user(
    blocked_user_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Unblock user."""
    return await delete_block(db, current_user.id, blocked_user_id)


@router.post("/blocks", response_model=BlockOut | dict[str, Any], summary="Block user")
async def block_user(
    payload: BlockCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Block user."""
    if payload.unmatch_only:
        return await unmatch_user_pair(db, current_user.id, payload.blocked_user_id)
    return await create_block(db, current_user.id, payload.blocked_user_id)


@router.post("/reports", response_model=ReportOut, summary="Report user")
async def report_user(
    payload: ReportCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Report user."""
    return await create_report(db, current_user.id, payload)


@router.get("/notifications", response_model=CursorPage[FlatmatesNotificationOut], summary="List flatmates notifications")
async def get_flatmates_notifications(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List flatmates notifications."""
    rows, next_payload, total = await list_flatmates_notifications(
        db,
        current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [FlatmatesNotificationOut.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.put("/notifications", response_model=dict[str, Any], summary="Mark flatmates notifications")
async def mark_flatmates_notifications(
    payload: FlatmatesNotificationUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark flatmates notifications."""
    del payload
    return await mark_all_flatmates_notifications_read(db, current_user.id)


@router.put("/notifications/{notification_id}", response_model=dict[str, Any], summary="Mark flatmates notification")
async def mark_flatmates_notification(
    notification_id: str,
    payload: FlatmatesNotificationUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark flatmates notification."""
    del payload
    return await mark_flatmates_notification_read(db, current_user.id, notification_id)


@router.put("/visits/{visit_id}", summary="Update flatmate visit")
async def update_flatmate_visit(
    visit_id: int,
    payload: FlatmateVisitUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update flatmate visit."""
    from app.services.flatmates import update_visit_status

    return await update_visit_status(db, current_user.id, visit_id, payload)


@router.post("/conversations/{conversation_id}/mark-read", summary="Mark conversation as read")
async def mark_conversation_as_read(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark conversation as read."""
    return await mark_conversation_read(db, conversation_id, current_user.id)


@router.post("/conversations/{conversation_id}/qa", summary="Save Q&A answers")
@router.post("/conversations/{conversation_id}/qna", summary="Save Q&A answers")
async def save_qna_answers(
    conversation_id: int,
    payload: QnAAnswers,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Save Q&A answers."""
    return await save_match_qna_answers(db, conversation_id, current_user.id, payload)
