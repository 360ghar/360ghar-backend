from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
)
from app.core.database import get_db
from app.core.exceptions import BadRequestException
from app.core.logging import get_logger
from app.models.enums import ListingGenderPreference, VisitStatus
from app.models.users import User as UserModel
from app.schemas.flatmates import (
    BlockCreate,
    BlockedUserOut,
    BlockOut,
    CatalogEntry,
    CompatibilityBreakdown,
    ConversationCreate,
    ConversationQnAState,
    ConversationSummary,
    FlatmatesBootstrap,
    FlatmatesNotificationBulkUpdate,
    FlatmatesNotificationOut,
    FlatmatesNotificationUpdate,
    FlatmatesPeer,
    FlatmatesProfile,
    FlatmatesProfileUpdate,
    FlatmateVisitOut,
    FlatmateVisitUpdate,
    IncomingLikeSummary,
    MatchContactOut,
    MatchStatusOut,
    MatchSummary,
    MessageCreate,
    MessageOut,
    NotificationsMarkedRead,
    NotificationUnreadCount,
    OutgoingLikeSummary,
    ProfileViewEventCreate,
    ProfileViewEventOut,
    QnAAnswers,
    ReportCreate,
    ReportOut,
    SocietyTagVoteCreate,
    SocietyTagVoteOut,
    SwipeRequest,
    SwipeResult,
    UnmatchPairRequest,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import User as UserSchema
from app.services.flatmates import (
    count_unread_flatmates_notifications,
    create_block,
    create_conversation_from_payload,
    create_report,
    delete_block,
    get_bootstrap,
    get_conversation_summary,
    get_flatmates_profile,
    get_match_contact,
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
    load_visible_peer,
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
from app.services.flatmates.compatibility import calculate_compatibility

logger = get_logger(__name__)

router = APIRouter()


@router.get("/bootstrap", response_model=FlatmatesBootstrap, summary="Get flatmates bootstrap")
async def get_flatmates_bootstrap(
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get flatmates bootstrap."""
    return await get_bootstrap(db, current_user.id)


@router.get("/catalogs", response_model=CursorPage[CatalogEntry], summary="Get flatmates catalogs")
async def get_flatmates_catalogs(
    db: AsyncSession = Depends(get_db),
):
    """Get flatmates catalogs. The whole catalog list is one page."""
    catalogs = await list_catalogs(db)
    return build_cursor_page(catalogs, limit=len(catalogs), next_payload=None)


@router.get("/profile", response_model=FlatmatesProfile, summary="Get current flatmate profile")
async def get_profile(
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current flatmate profile."""
    return await get_flatmates_profile(db, current_user.id)


@router.put("/profile", response_model=FlatmatesProfile, summary="Update flatmate profile")
async def update_profile(
    payload: FlatmatesProfileUpdate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update flatmate profile."""
    return await update_flatmates_profile(db, current_user.id, payload)


@router.patch("/profile", response_model=FlatmatesProfile, summary="Patch flatmate profile")
async def patch_profile(
    payload: FlatmatesProfileUpdate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch flatmate profile."""
    return await update_flatmates_profile(db, current_user.id, payload)


@router.post(
    "/profile",
    response_model=FlatmatesProfile,
    status_code=201,
    summary="Create flatmate profile",
)
async def create_profile(
    payload: FlatmatesProfileUpdate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create flatmate profile."""
    return await update_flatmates_profile(db, current_user.id, payload)


@router.get(
    "/profiles/{user_id}", response_model=FlatmatesPeer, summary="Get flatmate profile by user"
)
async def get_user_profile(
    user_id: int,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get flatmate profile by user. Returns 404 unless the profile is visible to the caller."""
    return await get_profile_by_id(db, user_id, current_user_id=current_user.id)


@router.get(
    "/profiles/{user_id}/compatibility",
    response_model=CompatibilityBreakdown,
    summary="Get compatibility breakdown with a flatmate",
)
async def get_user_compatibility(
    user_id: int,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full compatibility breakdown between the current user and the peer."""
    if current_user.id == user_id:
        raise BadRequestException(
            detail="Cannot compute compatibility with yourself.",
            error_code="SELF_COMPATIBILITY",
        )

    peer = await load_visible_peer(db, current_user.id, user_id)

    result = calculate_compatibility(current_user, peer)
    return CompatibilityBreakdown(
        user_id=current_user.id,
        peer_id=user_id,
        overall_percentage=result["percentage"],
        color=result["color"],
        dimensions=result["dimensions"],
        summary=result["summary"],
    )


@router.get(
    "/profiles", response_model=CursorPage[FlatmatesPeer], summary="Discover flatmate profiles"
)
async def get_discoverable_profiles(
    city: str | None = Query(default=None),
    budget_min: int | None = Query(default=None),
    budget_max: int | None = Query(default=None),
    move_in: str | None = Query(
        default=None,
        description="Move-in timeline: immediate, this_month, next_month, flexible",
    ),
    age_min: int | None = Query(default=None, ge=18, le=100, description="Minimum age"),
    age_max: int | None = Query(default=None, ge=18, le=100, description="Maximum age"),
    lat: float | None = Query(default=None, description="Latitude for geo filtering"),
    lng: float | None = Query(default=None, description="Longitude for geo filtering"),
    radius: float | None = Query(default=None, description="Radius in km for geo filtering"),
    non_negotiables: str | None = Query(
        default=None,
        description="Comma-separated non-negotiable deal-breakers",
    ),
    gender_preference: ListingGenderPreference | None = Query(
        default=None,
        description="Candidate gender to show. any (or omitted) applies no filter.",
    ),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Discover flatmate profiles."""
    if age_min is not None and age_max is not None and age_max < age_min:
        raise BadRequestException(
            detail="age_max must be greater than or equal to age_min",
            error_code="INVALID_AGE_RANGE",
        )
    parsed_non_neg: list[str] | None = None
    if non_negotiables:
        parsed_non_neg = [n.strip() for n in non_negotiables.split(",") if n.strip()]
    gender = gender_preference.value if gender_preference is not None else None
    filters = {
        "city": city,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "move_in": move_in,
        "age_min": age_min,
        "age_max": age_max,
        "lat": lat,
        "lng": lng,
        "radius": radius,
        "non_negotiables": parsed_non_neg,
        "gender_preference": gender,
    }
    profiles, next_payload, total = await list_discoverable_profiles(
        db,
        current_user.id,
        city=city,
        budget_min=budget_min,
        budget_max=budget_max,
        move_in=move_in,
        age_min=age_min,
        age_max=age_max,
        lat=lat,
        lng=lng,
        radius=radius,
        non_negotiables_override=parsed_non_neg,
        gender_preference=gender,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [FlatmatesPeer.model_validate(p) for p in profiles],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.post(
    "/swipes", response_model=SwipeResult, status_code=201, summary="Swipe flatmate profile"
)
async def swipe(
    payload: SwipeRequest,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Swipe flatmate profile."""
    return await record_swipe(db, current_user.id, payload)


@router.get("/likes", response_model=CursorPage[IncomingLikeSummary], summary="List incoming likes")
async def get_incoming_likes(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
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


@router.get(
    "/outgoing-likes", response_model=CursorPage[OutgoingLikeSummary], summary="List outgoing likes"
)
async def get_outgoing_likes(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
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
        [OutgoingLikeSummary.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.post(
    "/profile-views",
    response_model=ProfileViewEventOut,
    status_code=201,
    summary="Record profile view",
)
async def record_profile_view(
    payload: ProfileViewEventCreate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Record profile view."""
    return await record_profile_view_event(db, current_user.id, payload)


@router.post(
    "/listings/{listing_id}/society-tags/votes",
    response_model=SocietyTagVoteOut,
    summary="Vote on society tag",
)
async def vote_society_tag(
    listing_id: int,
    payload: SocietyTagVoteCreate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Vote on society tag."""
    return await record_society_tag_vote(db, current_user.id, listing_id, payload)


@router.get(
    "/conversations", response_model=CursorPage[ConversationSummary], summary="List conversations"
)
async def get_conversations(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
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


@router.post(
    "/conversations",
    response_model=ConversationSummary,
    status_code=201,
    summary="Create conversation",
)
async def create_conversation(
    payload: ConversationCreate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create conversation."""
    return await create_conversation_from_payload(db, current_user.id, payload)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationSummary,
    summary="Get conversation detail",
)
async def get_conversation_detail(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation detail."""
    return await get_conversation_summary(db, conversation_id, current_user.id)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=CursorPage[MessageOut],
    summary="List conversation messages",
)
async def get_conversation_messages(
    conversation_id: int,
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversation messages, newest page first. The cursor is bound to this conversation.

    Without a cursor the newest page is returned and marks the peer's messages as read.
    Scroll-back pages (with a cursor) never change read state.
    """
    filters = {"conversation_id": conversation_id}
    messages, next_payload, total = await list_messages(
        db,
        conversation_id,
        current_user.id,
        limit=page.limit,
        cursor_payload=page.decoded(filters),
        with_total=page.include_total,
    )
    return build_cursor_page(
        [MessageOut.model_validate(m) for m in messages],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=201,
    summary="Send conversation message",
)
async def post_conversation_message(
    conversation_id: int,
    payload: MessageCreate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Send conversation message."""
    return await send_message(db, conversation_id, current_user.id, payload)


@router.get("/matches", response_model=CursorPage[MatchSummary], summary="List matches")
async def get_matches(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
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


@router.get(
    "/matches/{match_id}/contact",
    response_model=MatchContactOut,
    summary="Get the matched peer's phone number",
)
async def get_match_contact_detail(
    match_id: int,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the other user's phone for an active mutual match. Otherwise 404."""
    return await get_match_contact(db, current_user.id, match_id)


@router.put(
    "/matches/{match_id}/unmatch", response_model=MatchStatusOut, summary="Unmatch conversation"
)
async def unmatch(
    match_id: int,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Unmatch conversation."""
    return await unmatch_match(db, current_user.id, match_id)


@router.get("/blocks", response_model=CursorPage[BlockedUserOut], summary="List blocked users")
async def get_blocked_users(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
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


@router.delete("/blocks/{blocked_user_id}", status_code=204, summary="Unblock user")
async def unblock_user(
    blocked_user_id: int,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Unblock user."""
    await delete_block(db, current_user.id, blocked_user_id)


@router.post(
    "/blocks",
    response_model=BlockOut,
    status_code=201,
    summary="Block user",
)
async def block_user(
    payload: BlockCreate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Block user. Closes any active conversation and prevents future matching."""
    return await create_block(db, current_user.id, payload.blocked_user_id)


@router.post(
    "/unmatch",
    response_model=MatchStatusOut,
    summary="Unmatch a pair without blocking",
)
async def unmatch_pair(
    payload: UnmatchPairRequest,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Unmatch the pair and close their 1:1 conversation. Does not create a block."""
    return await unmatch_user_pair(db, current_user.id, payload.peer_user_id)


@router.post("/reports", response_model=ReportOut, status_code=201, summary="Report user")
async def report_user(
    payload: ReportCreate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Report user."""
    return await create_report(db, current_user.id, payload)


@router.get(
    "/notifications",
    response_model=CursorPage[FlatmatesNotificationOut],
    summary="List flatmates notifications",
)
async def get_flatmates_notifications(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_cached_active_user),
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


@router.get(
    "/notifications/unread-count",
    response_model=NotificationUnreadCount,
    summary="Count unread flatmates notifications",
)
async def get_flatmates_unread_count(
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Count unread flatmates notifications."""
    count = await count_unread_flatmates_notifications(db, current_user.id)
    return NotificationUnreadCount(unread_count=count)


@router.put(
    "/notifications",
    response_model=NotificationsMarkedRead,
    summary="Mark all flatmates notifications read",
)
async def mark_flatmates_notifications(
    payload: FlatmatesNotificationBulkUpdate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all flatmates notifications read."""
    del payload
    result = await mark_all_flatmates_notifications_read(db, current_user.id)
    return NotificationsMarkedRead(updated=result["updated"])


@router.put(
    "/notifications/{notification_id}",
    response_model=FlatmatesNotificationOut,
    summary="Set read state of a flatmates notification",
)
async def mark_flatmates_notification(
    notification_id: str,
    payload: FlatmatesNotificationUpdate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the read state of one notification (is_read true or false)."""
    row = await mark_flatmates_notification_read(
        db, current_user.id, notification_id, is_read=payload.is_read
    )
    return FlatmatesNotificationOut.model_validate(row)


@router.put("/visits/{visit_id}", response_model=FlatmateVisitOut, summary="Update flatmate visit")
async def update_flatmate_visit(
    visit_id: int,
    payload: FlatmateVisitUpdate,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update flatmate visit."""
    from app.services.flatmates import update_visit_status

    result = await update_visit_status(db, current_user.id, visit_id, payload)
    return FlatmateVisitOut(id=result["id"], status=VisitStatus(result["status"]))


@router.post(
    "/conversations/{conversation_id}/mark-read",
    status_code=204,
    summary="Mark conversation as read",
)
async def mark_conversation_as_read(
    conversation_id: int,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Mark conversation as read."""
    await mark_conversation_read(db, conversation_id, current_user.id)


@router.post(
    "/conversations/{conversation_id}/qna",
    response_model=ConversationQnAState,
    summary="Save Q&A answers",
)
async def save_qna_answers(
    conversation_id: int,
    payload: QnAAnswers,
    current_user: UserSchema = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Save Q&A answers. Requires an active match with the peer."""
    state = await save_match_qna_answers(db, conversation_id, current_user.id, payload)
    return ConversationQnAState.model_validate(state)
