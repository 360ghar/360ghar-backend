from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from app.models.models import Visit, Agent, User, Property
from app.schemas.visit import VisitCreate, VisitUpdate
from typing import Optional

async def create_visit(db: AsyncSession, user_id: int, visit: VisitCreate):
    """Create a new visit"""
    visit_data = visit.model_dump()
    visit_data["user_id"] = user_id
    
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
    upcoming = sum(1 for v in visits if v.status in ["scheduled", "confirmed"] and v.scheduled_date > now)
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
        Visit.status.in_(["scheduled", "confirmed"])
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
    """Cancel a visit"""
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()
    
    if visit:
        visit.status = "cancelled"
        visit.cancellation_reason = reason
        await db.flush()
        return True
    
    return False

async def reschedule_visit(db: AsyncSession, visit_id: int, new_date: datetime, reason: Optional[str] = None):
    """Reschedule a visit"""
    stmt = select(Visit).where(Visit.id == visit_id)
    result = await db.execute(stmt)
    visit = result.scalar_one_or_none()
    
    if visit:
        visit.rescheduled_from = visit.scheduled_date
        visit.scheduled_date = new_date
        visit.status = "rescheduled"
        if reason:
            visit.cancellation_reason = reason
        await db.flush()
        return True
    
    return False

async def get_agent_visits(db: AsyncSession, agent_id: int, page: int = 1, limit: int = 20):
    """Get visits handled by a specific agent"""
    offset = (page - 1) * limit
    
    stmt = select(Visit).options(
        selectinload(Visit.property).selectinload(Property.images),
        selectinload(Visit.property).selectinload(Property.property_amenities)
    ).where(Visit.agent_id == agent_id).offset(offset).limit(limit).order_by(Visit.scheduled_date.desc())
    result = await db.execute(stmt)
    visits = result.scalars().all()
    
    # Get total count
    count_stmt = select(Visit).where(Visit.agent_id == agent_id)
    count_result = await db.execute(count_stmt)
    total = len(count_result.scalars().all())
    
    return {
        "visits": visits,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit
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
