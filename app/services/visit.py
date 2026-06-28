from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.config import settings
from app.core.exceptions import BadRequestException, ConflictException
from app.core.logging import get_logger
from app.models.conversations import Conversation, ConversationParticipant
from app.models.enums import (
    ConversationApp,
    ConversationStatus,
    UserMatchStatus,
    VisitContext,
    VisitStatus,
)
from app.models.properties import Property, PropertyAmenity, Visit
from app.models.social import UserMatch
from app.models.users import User
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.schemas.visit import Visit as VisitSchema
from app.schemas.visit import VisitCreate, VisitUpdate

logger = get_logger(__name__)


def _visit_load_options():
    return (
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        selectinload(Visit.counterparty_user),
        selectinload(Visit.agent),
    )


def _canonical_pair(user_id: int, other_user_id: int) -> tuple[int, int]:
    return (user_id, other_user_id) if user_id < other_user_id else (other_user_id, user_id)


async def _validate_flatmate_visit_context(
    db: AsyncSession,
    user_id: int,
    visit_data: dict,
) -> None:
    counterparty_user_id = visit_data.get("counterparty_user_id")
    if counterparty_user_id is None:
        raise BadRequestException(detail="counterparty_user_id is required for flatmate meetings")
    if counterparty_user_id == user_id:
        raise BadRequestException(detail="counterparty_user_id must be different from user_id")

    user_one_id, user_two_id = _canonical_pair(user_id, counterparty_user_id)
    authorized = False

    conversation_id = visit_data.get("conversation_id")
    if conversation_id is not None:
        # Verify the conversation exists, is active, and has both users as participants
        conv = await db.get(Conversation, conversation_id)
        if conv is None or conv.status != ConversationStatus.active.value:
            raise BadRequestException(detail="Invalid flatmate conversation")
        if conv.app != ConversationApp.flatmates:
            raise BadRequestException(detail="Conversation is not a flatmates conversation")
        participant_ids = {
            row.user_id
            for row in (
                await db.execute(
                    select(ConversationParticipant.user_id).where(
                        ConversationParticipant.conversation_id == conversation_id
                    )
                )
            ).all()
        }
        if {user_one_id, user_two_id} - participant_ids:
            raise BadRequestException(detail="Invalid flatmate conversation")
        authorized = True

    match_id = visit_data.get("match_id")
    if match_id is not None:
        match = (
            await db.execute(
                select(UserMatch).where(
                    UserMatch.id == match_id,
                    UserMatch.user_one_id == user_one_id,
                    UserMatch.user_two_id == user_two_id,
                    UserMatch.status == UserMatchStatus.active.value,
                )
            )
        ).scalar_one_or_none()
        if match is None:
            raise BadRequestException(detail="Invalid flatmate match")
        authorized = True

    if authorized:
        return

    from app.services.flatmates.conversations import find_1to1_conversation

    conversation = await find_1to1_conversation(db, user_id, counterparty_user_id)
    if (
        conversation is not None
        and conversation.status == ConversationStatus.active.value
    ):
        visit_data["conversation_id"] = conversation.id
        return

    match = (
        await db.execute(
            select(UserMatch).where(
                UserMatch.user_one_id == user_one_id,
                UserMatch.user_two_id == user_two_id,
                UserMatch.status == UserMatchStatus.active.value,
            )
        )
    ).scalar_one_or_none()
    if match is not None:
        visit_data["match_id"] = match.id
        return

    raise BadRequestException(detail="Flatmate meeting requires an active conversation or match")


async def _ensure_no_visit_conflict(
    db: AsyncSession,
    user_id: int,
    property_id: int,
    scheduled_date: datetime,
) -> None:
    """Raise ConflictException if the user already has an active visit overlapping
    the requested window **for the same property**.

    The Visit model has no explicit duration column, so each visit is treated as
    occupying a fixed-duration window (VISIT_DEFAULT_DURATION_MINUTES) starting at
    its scheduled_date. A configurable buffer (VISIT_CONFLICT_BUFFER_MINUTES) is
    applied to both sides of the overlap check. Cancelled and completed visits
    never conflict.

    Overlap is scoped to (user_id, property_id): a user may have concurrent
    visits for *different* properties, and an agent may show the same property
    to multiple users at the same time.
    """
    duration = timedelta(minutes=settings.VISIT_DEFAULT_DURATION_MINUTES)
    buffer = timedelta(minutes=settings.VISIT_CONFLICT_BUFFER_MINUTES)

    new_start = scheduled_date
    new_end = new_start + duration
    # Coarse window to limit the candidate set; the precise check runs in Python.
    window_start = new_start - duration - buffer
    window_end = new_end + buffer

    stmt = select(Visit).where(
        Visit.user_id == user_id,
        Visit.property_id == property_id,
        Visit.status.notin_([VisitStatus.cancelled, VisitStatus.completed]),
        Visit.scheduled_date >= window_start,
        Visit.scheduled_date <= window_end,
    )
    result = await db.execute(stmt)
    existing_visits = result.scalars().all()

    for existing in existing_visits:
        existing_start = existing.scheduled_date
        existing_end = existing_start + duration
        # Two intervals [a, b) and [c, d) overlap iff a < d and c < b.
        # Apply the buffer to both sides so back-to-back visits still conflict.
        if (existing_start - buffer) < new_end and (existing_end + buffer) > new_start:
            raise ConflictException(
                detail="You already have a visit scheduled that overlaps this time",
                error_code="VISIT_CONFLICT",
            )


async def create_visit(db: AsyncSession, user_id: int, visit: VisitCreate):
    """Create a new visit"""
    visit_data = visit.model_dump()
    visit_data["user_id"] = user_id

    # Basic validation: scheduled date must be in the future
    scheduled_date = visit_data.get("scheduled_date")
    if scheduled_date is None:
        raise BadRequestException(detail="scheduled_date is required")
    if scheduled_date.tzinfo is None:
        # Treat naive datetimes as UTC to avoid naive/aware comparison errors
        scheduled_date = scheduled_date.replace(tzinfo=timezone.utc)
        visit_data["scheduled_date"] = scheduled_date
    now = datetime.now(timezone.utc)
    if scheduled_date < now:
        raise BadRequestException(detail="scheduled_date must be in the future")
    if visit_data.get("visit_context") == VisitContext.flatmate_meet:
        await _validate_flatmate_visit_context(db, user_id, visit_data)
    elif visit_data.get("counterparty_user_id") is not None:
        raise BadRequestException(detail="counterparty_user_id is only supported for flatmate meetings")

    # --- Overlap detection: prevent double-booking the user ---
    property_id = visit_data["property_id"]
    await _ensure_no_visit_conflict(db, user_id, property_id, scheduled_date)

    db_visit = Visit(**visit_data)
    db.add(db_visit)
    await db.flush()
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(Visit.id == db_visit.id)
    )
    result = await db.execute(stmt)
    visit_obj = result.scalar_one()

    # --- Push notification on visit creation ---
    try:
        from app.services.push_notification import notify_visit_scheduled
        # Notify the counterparty (flatmate meet) or the property owner
        if visit_obj.counterparty_user_id:
            await notify_visit_scheduled(
                db,
                recipient_db_id=visit_obj.counterparty_user_id,
                property_title=visit_obj.property.title if visit_obj.property and visit_obj.property.title else "the property",
                scheduled_date=visit_obj.scheduled_date.isoformat(),
            )
    except Exception:
        pass  # best-effort; never block visit creation

    return visit_obj

async def get_visit(db: AsyncSession, visit_id: int):
    """Get a visit by ID"""
    stmt = select(Visit).options(*_visit_load_options()).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_user_visits(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list, dict | None, int | None]:
    """Get all visits for a user (keyset-paginated)."""
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(or_(Visit.user_id == user_id, Visit.counterparty_user_id == user_id))
    )
    count_total = None
    if with_total:
        count_total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    predicate = keyset_filter(Visit.scheduled_date, Visit.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Visit.scheduled_date.desc(), Visit.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].scheduled_date), rows[-1].id)
    return rows, next_payload, count_total

async def get_user_upcoming_visits(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list, dict | None, int | None]:
    """Get upcoming visits for a user (keyset-paginated)."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(
            or_(Visit.user_id == user_id, Visit.counterparty_user_id == user_id),
            Visit.scheduled_date > now,
            Visit.status.in_([VisitStatus.scheduled, VisitStatus.confirmed, VisitStatus.rescheduled])
        )
    )
    count_total = None
    if with_total:
        count_total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    predicate = keyset_filter(Visit.scheduled_date, Visit.id, cursor_payload, descending=False)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Visit.scheduled_date.asc(), Visit.id.asc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].scheduled_date), rows[-1].id)
    return rows, next_payload, count_total

async def get_user_past_visits(
    db: AsyncSession,
    user_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list, dict | None, int | None]:
    """Get past visits for a user (keyset-paginated)."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(
            or_(Visit.user_id == user_id, Visit.counterparty_user_id == user_id),
            Visit.scheduled_date < now
        )
    )
    count_total = None
    if with_total:
        count_total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    predicate = keyset_filter(Visit.scheduled_date, Visit.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Visit.scheduled_date.desc(), Visit.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].scheduled_date), rows[-1].id)
    return rows, next_payload, count_total

# Valid status transitions: only these changes are allowed via the generic update.
_VALID_STATUS_TRANSITIONS: dict[VisitStatus, set[VisitStatus]] = {
    VisitStatus.scheduled: {VisitStatus.confirmed, VisitStatus.cancelled},
    VisitStatus.confirmed: {VisitStatus.cancelled},
    VisitStatus.rescheduled: {VisitStatus.confirmed, VisitStatus.cancelled},
    # terminal states -- no further transitions allowed via update
    VisitStatus.completed: set(),
    VisitStatus.cancelled: set(),
}


async def update_visit(db: AsyncSession, visit_id: int, visit_update: VisitUpdate):
    """Update a visit.

    Status transitions are validated: cancelled/completed visits are terminal
    and cannot be changed, and only pre-defined transitions are allowed from
    active states.
    """
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()

    if not visit:
        return None

    update_data = visit_update.model_dump(exclude_unset=True)

    # --- Validate status transition ---
    new_status = update_data.get("status")
    if new_status is not None:
        # Allow idempotent updates (same status) — clients may re-confirm, etc.
        if new_status != visit.status:
            allowed = _VALID_STATUS_TRANSITIONS.get(visit.status, set())
            if new_status not in allowed:
                new_label = getattr(new_status, "value", new_status)
                raise BadRequestException(
                    detail=f"Cannot transition from '{visit.status.value}' to '{new_label}'"
                )

    old_status = visit.status
    for field, value in update_data.items():
        setattr(visit, field, value)

    await db.flush()
    # Re-select with eager-loaded relationships to avoid async lazy-loads during serialization
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(Visit.id == visit_id)
    )
    result = await db.execute(stmt)
    updated_visit = result.scalar_one_or_none()

    # --- Push notification on visit confirmation ---
    if new_status == VisitStatus.confirmed and old_status != VisitStatus.confirmed and updated_visit:
        try:
            from app.services.push_notification import notify_visit_confirmed
            scheduled_str = updated_visit.scheduled_date.isoformat() if updated_visit.scheduled_date else "TBD"
            prop_title = updated_visit.property.title if updated_visit.property and updated_visit.property.title else "the property"
            # Notify the visiting user
            await notify_visit_confirmed(
                db,
                recipient_db_id=updated_visit.user_id,
                property_title=prop_title,
                scheduled_date=scheduled_str,
            )
            # Notify the counterparty if present
            if updated_visit.counterparty_user_id:
                await notify_visit_confirmed(
                    db,
                    recipient_db_id=updated_visit.counterparty_user_id,
                    property_title=prop_title,
                    scheduled_date=scheduled_str,
                )
        except Exception:
            pass  # best-effort; never block visit update

    return updated_visit

async def cancel_visit(db: AsyncSession, visit_id: int, reason: str):
    """Cancel a visit and return the updated visit with relationships.

    Returns:
        Visit | None: Updated visit on success, None on failure/not found.
    """
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()

    if not visit:
        return None

    # Disallow cancellation for already cancelled or completed visits
    if visit.status in [VisitStatus.cancelled, VisitStatus.completed]:
        return None

    visit.status = VisitStatus.cancelled
    visit.cancellation_reason = reason
    await db.flush()

    # Re-select with eager-loaded relationships for serialization safety
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(Visit.id == visit_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def reschedule_visit(db: AsyncSession, visit_id: int, new_date: datetime, reason: str | None = None):
    """Reschedule a visit and return the updated visit with relationships.

    Returns:
        Visit | None: Updated visit on success, None on failure/not found.
    """
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()

    if not visit:
        return None

    # Disallow rescheduling for already cancelled or completed visits
    if visit.status in [VisitStatus.cancelled, VisitStatus.completed]:
        return None

    # Ensure new date is timezone-aware and in the future
    if new_date.tzinfo is None:
        new_date = new_date.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if new_date < now:
        return None

    visit.rescheduled_from = visit.scheduled_date
    visit.scheduled_date = new_date
    visit.status = VisitStatus.rescheduled
    if reason:
        # Store reason; field name kept for compatibility
        visit.cancellation_reason = reason
    await db.flush()

    # Re-select with eager-loaded relationships for serialization safety
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(Visit.id == visit_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_agent_visits(
    db: AsyncSession,
    agent_id: int,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[VisitSchema], dict | None, int | None]:
    """Get visits handled by a specific agent (keyset-paginated)."""
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(Visit.agent_id == agent_id)
    )

    count_total = None
    if with_total:
        count_stmt = select(func.count()).where(Visit.agent_id == agent_id)
        count_result = await db.execute(count_stmt)
        count_total = count_result.scalar_one()

    predicate = keyset_filter(Visit.scheduled_date, Visit.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Visit.scheduled_date.desc(), Visit.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].scheduled_date), rows[-1].id)

    items = [VisitSchema.model_validate(r, from_attributes=True) for r in rows]
    return items, next_payload, count_total

async def mark_visit_completed(db: AsyncSession, visit_id: int, notes: str | None = None, feedback: str | None = None):
    """Mark a visit as completed.

    Only visits in *scheduled*, *confirmed*, or *rescheduled* state may be
    marked as completed.  Already-completed or cancelled visits are rejected.

    Returns:
        True on success, False if the visit was not found or is in an
        invalid state.
    """
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()

    if not visit:
        return False

    completable_statuses = {VisitStatus.scheduled, VisitStatus.confirmed, VisitStatus.rescheduled}
    if visit.status not in completable_statuses:
        return False

    visit.status = VisitStatus.completed
    visit.actual_date = datetime.now(timezone.utc)
    if notes:
        visit.visit_notes = notes
    if feedback:
        visit.visitor_feedback = feedback
    await db.flush()
    return True

async def get_user_property_visit_stats(db: AsyncSession, user_id: int, property_id: int):
    """Return upcoming scheduled visit stats for a user on a given property.

    Calculates count of upcoming visits with status in [scheduled, confirmed, rescheduled]
    and returns the earliest upcoming date if present.
    """
    now = datetime.now(timezone.utc)
    # Filter upcoming and scheduled-like statuses
    stmt = (
        select(Visit.scheduled_date)
        .where(
            Visit.user_id == user_id,
            Visit.property_id == property_id,
            Visit.scheduled_date >= now,
            Visit.status.in_([VisitStatus.scheduled, VisitStatus.confirmed, VisitStatus.rescheduled]),
        )
        .order_by(Visit.scheduled_date.asc())
    )
    result = await db.execute(stmt)
    rows = result.fetchall()
    count = len(rows)
    next_date = rows[0][0] if count else None
    return {"count": count, "next_date": next_date}


async def get_all_visits(
    db: AsyncSession,
    *,
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    status: str | None = None,
    filter_agent_id: int | None = None,
    property_id: int | None = None,
    user_id: int | None = None,
) -> tuple[list, dict | None, int | None]:
    """Global visit listing with optional filters and keyset pagination."""
    Owner = aliased(User)

    stmt = select(Visit).options(*_visit_load_options())
    filters = []
    if status:
        filters.append(Visit.status == status)
    if property_id:
        filters.append(Visit.property_id == property_id)
    if user_id:
        filters.append(Visit.user_id == user_id)

    if filter_agent_id is not None:
        stmt = stmt.outerjoin(User, Visit.user_id == User.id).outerjoin(Property, Visit.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        filters.append(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id, Visit.agent_id == filter_agent_id))

    if filters:
        stmt = stmt.where(and_(*filters))

    count_total = None
    if with_total:
        count_total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    predicate = keyset_filter(Visit.scheduled_date, Visit.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Visit.scheduled_date.desc(), Visit.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_payload = keyset_payload(keyset_sort_value(rows[-1].scheduled_date), rows[-1].id)
    return rows, next_payload, count_total
