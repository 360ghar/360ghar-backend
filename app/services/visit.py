from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload, aliased
from datetime import datetime, timezone
from app.models.properties import Visit, Property
from app.models.agents import Agent
from app.models.users import User
from app.schemas.visit import VisitCreate, VisitUpdate, Visit as VisitSchema
from typing import Optional

async def create_visit(db: AsyncSession, user_id: int, visit: VisitCreate):
    """Create a new visit"""
    visit_data = visit.model_dump()
    visit_data["user_id"] = user_id

    # Basic validation: scheduled date must be in the future
    scheduled_date = visit_data.get("scheduled_date")
    if scheduled_date is None:
        raise ValueError("scheduled_date is required")
    if scheduled_date.tzinfo is None:
        # Treat naive datetimes as UTC to avoid naive/aware comparison errors
        scheduled_date = scheduled_date.replace(tzinfo=timezone.utc)
        visit_data["scheduled_date"] = scheduled_date
    now = datetime.now(timezone.utc)
    if scheduled_date < now:
        raise ValueError("scheduled_date must be in the future")
    
    db_visit = Visit(**visit_data)
    db.add(db_visit)
    # Flush to assign PK, then re-select with eager-loaded relationships
    await db.flush()
    stmt = (
        select(Visit)
        .options(
            selectinload(Visit.property).selectinload(Property.images),
            selectinload(Visit.property).selectinload(Property.property_amenities),
        )
        .where(Visit.id == db_visit.id)
    )
    result = await db.execute(stmt)
    return result.scalar_one()

async def get_visit(db: AsyncSession, visit_id: int):
    """Get a visit by ID"""
    stmt = select(Visit).options(
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities)
    ).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_user_visits(db: AsyncSession, user_id: int):
    """Get all visits for a user"""
    stmt = select(Visit).options(
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities)
    ).where(Visit.user_id == user_id).order_by(Visit.scheduled_date.desc())
    result = await db.execute(stmt)
    visits = result.scalars().all()
    
    # Count visits by status
    now = datetime.now(timezone.utc)
    upcoming = sum(
        1
        for v in visits
        if v.status in ["scheduled", "confirmed", "rescheduled"] and v.scheduled_date > now
    )
    completed = sum(1 for v in visits if v.status == "completed")
    cancelled = sum(1 for v in visits if v.status == "cancelled")
    
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
    stmt = select(Visit).options(
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities)
    ).where(
        Visit.user_id == user_id,
        Visit.scheduled_date > now,
        Visit.status.in_(["scheduled", "confirmed", "rescheduled"])
    ).order_by(Visit.scheduled_date)
    result = await db.execute(stmt)
    visits = result.scalars().all()
    return {"visits": visits, "total": len(visits)}

async def get_user_past_visits(db: AsyncSession, user_id: int):
    """Get past visits for a user"""
    now = datetime.now(timezone.utc)
    stmt = select(Visit).options(
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities)
    ).where(
        Visit.user_id == user_id,
        Visit.scheduled_date < now
    ).order_by(Visit.scheduled_date.desc())
    result = await db.execute(stmt)
    visits = result.scalars().all()
    return {"visits": visits, "total": len(visits)}

async def update_visit(db: AsyncSession, visit_id: int, visit_update: VisitUpdate):
    """Update a visit"""
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()
    
    if visit:
        update_data = visit_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(visit, field, value)
        
        await db.flush()
        # Re-select with eager-loaded relationships to avoid async lazy-loads during serialization
        stmt = (
            select(Visit)
            .options(
                selectinload(Visit.property).selectinload(Property.images),
                selectinload(Visit.property).selectinload(Property.property_amenities),
            )
            .where(Visit.id == visit_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
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
    if visit.status in ["cancelled", "completed"]:
        return None

    visit.status = "cancelled"
    visit.cancellation_reason = reason
    await db.flush()

    # Re-select with eager-loaded relationships for serialization safety
    stmt = (
        select(Visit)
        .options(
            selectinload(Visit.property).selectinload(Property.images),
            selectinload(Visit.property).selectinload(Property.property_amenities),
        )
        .where(Visit.id == visit_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def reschedule_visit(db: AsyncSession, visit_id: int, new_date: datetime, reason: Optional[str] = None):
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
    if visit.status in ["cancelled", "completed"]:
        return None

    # Ensure new date is timezone-aware and in the future
    if new_date.tzinfo is None:
        new_date = new_date.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if new_date < now:
        return None

    visit.rescheduled_from = visit.scheduled_date
    visit.scheduled_date = new_date
    visit.status = "rescheduled"
    if reason:
        # Store reason; field name kept for compatibility
        visit.cancellation_reason = reason
    await db.flush()

    # Re-select with eager-loaded relationships for serialization safety
    stmt = (
        select(Visit)
        .options(
            selectinload(Visit.property).selectinload(Property.images),
            selectinload(Visit.property).selectinload(Property.property_amenities),
        )
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
        .options(
            selectinload(Visit.property).selectinload(Property.images),
            selectinload(Visit.property).selectinload(Property.property_amenities),
        )
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

async def mark_visit_completed(db: AsyncSession, visit_id: int, notes: str = None, feedback: str = None):
    """Mark a visit as completed"""
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()
    
    if visit:
        visit.status = "completed"
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
            Visit.status.in_(["scheduled", "confirmed", "rescheduled"]),
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
    status: Optional[str] = None,
    filter_agent_id: Optional[int] = None,
    property_id: Optional[int] = None,
    user_id: Optional[int] = None,
):
    """Global visit listing with optional filters and pagination.

    When filter_agent_id is provided, returns visits for users/properties assigned to that agent.
    """
    offset = (page - 1) * limit
    Owner = aliased(User)

    base = select(Visit).options(
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities),
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
