import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.schemas.flatmates import (
    BlockCreate,
    BlockOut,
    CatalogEntry,
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
from app.schemas.user import User as UserSchema
from app.services.flatmates import (
    create_block,
    create_report,
    delete_block,
    get_bootstrap,
    get_conversation_summary,
    get_flatmates_profile,
    list_blocks,
    list_catalogs,
    list_conversations,
    list_discoverable_profiles,
    list_flatmates_notifications,
    list_incoming_likes,
    list_matches,
    list_messages,
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

router = APIRouter()


@router.get("/sse")
async def flatmates_sse(
    current_user: UserSchema = Depends(get_current_active_user),
):
    """SSE stream for flatmates real-time events."""
    from app.core.sse import sse_bus

    user_id = current_user.id
    queue = await sse_bus.subscribe(user_id)

    async def event_stream():
        try:
            yield "event: connected\ndata: {\"status\":\"ok\"}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    event_type = event.get("type", "update")
                    payload = json.dumps(event, default=str)
                    yield f"event: {event_type}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
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


@router.get("/bootstrap", response_model=FlatmatesBootstrap)
async def get_flatmates_bootstrap(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_bootstrap(db, current_user.id)


@router.get("/catalogs", response_model=list[CatalogEntry])
async def get_flatmates_catalogs(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    del current_user
    return await list_catalogs(db)


@router.get("/profile", response_model=FlatmatesProfile)
async def get_profile(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_flatmates_profile(db, current_user.id)


@router.put("/profile", response_model=FlatmatesProfile)
async def update_profile(
    payload: FlatmatesProfileUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await update_flatmates_profile(db, current_user.id, payload)


@router.get("/profiles", response_model=list[FlatmatesPeer])
async def get_discoverable_profiles(
    city: str | None = Query(default=None),
    budget_min: int | None = Query(default=None),
    budget_max: int | None = Query(default=None),
    move_in: str | None = Query(
        default=None,
        description="Move-in timeline: immediate, this_month, next_month, flexible",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_discoverable_profiles(
        db,
        current_user.id,
        city=city,
        budget_min=budget_min,
        budget_max=budget_max,
        move_in=move_in,
        limit=limit,
        offset=offset,
    )


@router.post("/swipes", response_model=SwipeResult)
async def swipe(
    payload: SwipeRequest,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await record_swipe(db, current_user.id, payload)


@router.get("/likes", response_model=list[IncomingLikeSummary])
async def get_incoming_likes(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_incoming_likes(db, current_user.id, limit=limit, offset=offset)


@router.post("/profile-views", response_model=ProfileViewEventOut)
async def record_profile_view(
    payload: ProfileViewEventCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await record_profile_view_event(db, current_user.id, payload)


@router.post("/listings/{listing_id}/society-tags/votes", response_model=SocietyTagVoteOut)
async def vote_society_tag(
    listing_id: int,
    payload: SocietyTagVoteCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await record_society_tag_vote(db, current_user.id, listing_id, payload)


@router.get("/conversations", response_model=list[ConversationSummary])
async def get_conversations(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_conversations(db, current_user.id)


@router.get("/conversations/{conversation_id}", response_model=ConversationSummary)
async def get_conversation_detail(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_conversation_summary(db, conversation_id, current_user.id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_conversation_messages(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_messages(db, conversation_id, current_user.id)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut)
async def post_conversation_message(
    conversation_id: int,
    payload: MessageCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await send_message(db, conversation_id, current_user.id, payload)


@router.get("/matches", response_model=list[MatchSummary])
async def get_matches(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_matches(db, current_user.id)


@router.put("/matches/{match_id}/unmatch")
async def unmatch(
    match_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await unmatch_match(db, current_user.id, match_id)


@router.get("/blocks")
async def get_blocked_users(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_blocks(db, current_user.id)


@router.delete("/blocks/{blocked_user_id}", response_model=dict[str, Any])
async def unblock_user(
    blocked_user_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await delete_block(db, current_user.id, blocked_user_id)


@router.post("/blocks", response_model=BlockOut | dict[str, Any])
async def block_user(
    payload: BlockCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.unmatch_only:
        return await unmatch_user_pair(db, current_user.id, payload.blocked_user_id)
    return await create_block(db, current_user.id, payload.blocked_user_id)


@router.post("/reports", response_model=ReportOut)
async def report_user(
    payload: ReportCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_report(db, current_user.id, payload)


@router.get("/notifications", response_model=list[FlatmatesNotificationOut])
async def get_flatmates_notifications(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_flatmates_notifications(db, current_user.id)


@router.put("/notifications", response_model=dict[str, Any])
async def mark_flatmates_notifications(
    payload: FlatmatesNotificationUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    del payload
    return await mark_all_flatmates_notifications_read(db, current_user.id)


@router.put("/notifications/{notification_id}", response_model=dict[str, Any])
async def mark_flatmates_notification(
    notification_id: str,
    payload: FlatmatesNotificationUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    del payload
    return await mark_flatmates_notification_read(db, current_user.id, notification_id)


@router.put("/visits/{visit_id}")
async def update_flatmate_visit(
    visit_id: int,
    payload: FlatmateVisitUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.flatmates import update_visit_status

    return await update_visit_status(db, current_user.id, visit_id, payload)


@router.post("/conversations/{conversation_id}/mark-read")
async def mark_conversation_as_read(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await mark_conversation_read(db, conversation_id, current_user.id)


@router.post("/conversations/{conversation_id}/qa")
@router.post("/conversations/{conversation_id}/qna")
async def save_qna_answers(
    conversation_id: int,
    payload: QnAAnswers,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await save_match_qna_answers(db, conversation_id, current_user.id, payload)
