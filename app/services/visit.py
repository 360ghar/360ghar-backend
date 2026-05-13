from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.exceptions import BadRequestException
from app.core.utils import make_tz_aware
from app.models.enums import ConversationStatus, UserMatchStatus, VisitContext, VisitStatus
from app.models.properties import Property, Visit
from app.models.social import UserConversation, UserMatch
from app.models.users import User
from app.schemas.visit import Visit as VisitSchema
from app.schemas.visit import VisitCreate, VisitUpdate


def _visit_load_options():
    return (
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities),
        selectinload(Visit.counterparty_user),
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
        conversation = (
            await db.execute(
                select(UserConversation).where(
                    UserConversation.id == conversation_id,
                    UserConversation.user_one_id == user_one_id,
                    UserConversation.user_two_id == user_two_id,
                    UserConversation.status == ConversationStatus.active.value,
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
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

    conversation = (
        await db.execute(
            select(UserConversation).where(
                UserConversation.user_one_id == user_one_id,
                UserConversation.user_two_id == user_two_id,
                UserConversation.status == ConversationStatus.active.value,
            )
        )
    ).scalar_one_or_none()
    if conversation is not None:
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

    db_visit = Visit(**visit_data)
    db.add(db_visit)
    # Flush to assign PK, then re-select with eager-loaded relationships
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

async def get_user_visits(db: AsyncSession, user_id: int):
    """Get all visits for a user"""
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(or_(Visit.user_id == user_id, Visit.counterparty_user_id == user_id))
        .order_by(Visit.scheduled_date.desc())
    )
    result = await db.execute(stmt)
    visits = result.scalars().all()

    # Count visits by status (handle tz-naive dates from DB)
    now = datetime.now(timezone.utc)
    upcoming = sum(
        1
        for v in visits
        if v.status in [VisitStatus.scheduled, VisitStatus.confirmed, VisitStatus.rescheduled] and v.scheduled_date is not None and (sd := make_tz_aware(v.scheduled_date)) is not None and sd > now
    )
    completed = sum(1 for v in visits if v.status == VisitStatus.completed)
    cancelled = sum(1 for v in visits if v.status == VisitStatus.cancelled)

    return {
        "visits": visits,
        "total": len(visits),
        "upcoming": upcoming,
        "completed": completed,
        "cancelled": cancelled
    }

async def get_user_upcoming_visits(db: AsyncSession, user_id: int):
    """Get upcoming visits for a user"""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(
            or_(Visit.user_id == user_id, Visit.counterparty_user_id == user_id),
            Visit.scheduled_date > now,
            Visit.status.in_([VisitStatus.scheduled, VisitStatus.confirmed, VisitStatus.rescheduled])
        )
        .order_by(Visit.scheduled_date)
    )
    result = await db.execute(stmt)
    visits = result.scalars().all()
    return {"visits": visits, "total": len(visits)}

async def get_user_past_visits(db: AsyncSession, user_id: int):
    """Get past visits for a user"""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(
            or_(Visit.user_id == user_id, Visit.counterparty_user_id == user_id),
            Visit.scheduled_date < now
        )
        .order_by(Visit.scheduled_date.desc())
    )
    result = await db.execute(stmt)
    visits = result.scalars().all()
    return {"visits": visits, "total": len(visits)}

async def update_visit(db: AsyncSession, visit_id: int, visit_update: VisitUpdate):
    """Update a visit"""
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()

    if visit:
        old_status = visit.status
        update_data = visit_update.model_dump(exclude_unset=True)
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
        new_status = update_data.get("status")
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

    return None

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

async def get_agent_visits(db: AsyncSession, agent_id: int, page: int = 1, limit: int = 20):
    """Get visits handled by a specific agent (paginated)."""
    offset = (page - 1) * limit

    # Page data
    stmt = (
        select(Visit)
        .options(*_visit_load_options())
        .where(Visit.agent_id == agent_id)
        .order_by(Visit.scheduled_date.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    # Convert to Pydantic models to ensure JSON serialization with generic PaginatedResponse
    items = [VisitSchema.model_validate(r, from_attributes=True) for r in rows]

    # Total count
    total_stmt = select(func.count(Visit.id)).where(Visit.agent_id == agent_id)
    total_result = await db.execute(total_stmt)
    total = int(total_result.scalar() or 0)

    total_pages = (total + limit - 1) // limit if limit else 1
    has_next = page < total_pages
    has_prev = page > 1 and total > 0

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev,
    }

async def mark_visit_completed(db: AsyncSession, visit_id: int, notes: str | None = None, feedback: str | None = None):
    """Mark a visit as completed"""
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()

    if visit:
        visit.status = VisitStatus.completed
        visit.actual_date = datetime.now(timezone.utc)
        if notes:
            visit.visit_notes = notes
        if feedback:
            visit.visitor_feedback = feedback
        await db.flush()
        return True

    return False

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
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    filter_agent_id: int | None = None,
    property_id: int | None = None,
    user_id: int | None = None,
):
    """Global visit listing with optional filters and pagination.

    When filter_agent_id is provided, returns visits for users/properties assigned to that agent.
    """
    offset = (page - 1) * limit
    Owner = aliased(User)

    base = select(Visit).options(
        *_visit_load_options(),
    )
    filters = []
    if status:
        filters.append(Visit.status == status)
    if property_id:
        filters.append(Visit.property_id == property_id)
    if user_id:
        filters.append(Visit.user_id == user_id)

    if filter_agent_id is not None:
        # Visits where the visiting user is assigned to agent OR the property's owner is assigned to agent
        base = base.outerjoin(User, Visit.user_id == User.id).outerjoin(Property, Visit.property_id == Property.id).outerjoin(Owner, Property.owner_id == Owner.id)
        filters.append(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))

    query = base
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(Visit.scheduled_date.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    items = [VisitSchema.model_validate(r, from_attributes=True) for r in rows]

    # Count total with same filters
    count_query = select(func.count(Visit.id))
    if filter_agent_id is not None:
        count_query = (
            count_query.outerjoin(User, Visit.user_id == User.id)
            .outerjoin(Property, Visit.property_id == Property.id)
            .outerjoin(Owner, Property.owner_id == Owner.id)
            .where(or_(User.agent_id == filter_agent_id, Owner.agent_id == filter_agent_id))
        )
    if status:
        count_query = count_query.where(Visit.status == status)
    if property_id:
        count_query = count_query.where(Visit.property_id == property_id)
    if user_id:
        count_query = count_query.where(Visit.user_id == user_id)

    count_result = await db.execute(count_query)
    total = int(count_result.scalar() or 0)

    total_pages = (total + limit - 1) // limit if limit else 1
    has_next = page < total_pages
    has_prev = page > 1 and total > 0

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev,
    }
