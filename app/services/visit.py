from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc, asc
from datetime import datetime
from app.models.visit import Visit, RelationshipManager, VisitStatus
from app.schemas.visit import VisitCreate, VisitUpdate
from typing import Optional

def create_visit(db: Session, user_id: int, visit: VisitCreate):
    # Assign a relationship manager (simple round-robin for now)
    rm = get_available_relationship_manager(db)
    
    db_visit = Visit(
        user_id=user_id,
        property_id=visit.property_id,
        relationship_manager_id=rm.id if rm else None,
        scheduled_date=visit.scheduled_date,
        visitor_name=visit.visitor_name,
        visitor_phone=visit.visitor_phone,
        visitor_email=visit.visitor_email,
        number_of_visitors=visit.number_of_visitors,
        preferred_time_slot=visit.preferred_time_slot,
        special_requirements=visit.special_requirements,
        status=VisitStatus.SCHEDULED
    )
    
    db.add(db_visit)
    db.commit()
    db.refresh(db_visit)
    
    # Update RM's visit count
    if rm:
        rm.total_visits_handled += 1
        db.commit()
    
    return db_visit

def get_visit(db: Session, visit_id: int):
    return db.query(Visit).options(
        joinedload(Visit.relationship_manager)
    ).filter(Visit.id == visit_id).first()

def get_user_visits(db: Session, user_id: int):
    visits = db.query(Visit).options(
        joinedload(Visit.relationship_manager)
    ).filter(Visit.user_id == user_id).order_by(desc(Visit.scheduled_date)).all()
    
    upcoming = [v for v in visits if v.scheduled_date > datetime.now() and v.status in [VisitStatus.SCHEDULED, VisitStatus.CONFIRMED]]
    completed = [v for v in visits if v.status == VisitStatus.COMPLETED]
    cancelled = [v for v in visits if v.status == VisitStatus.CANCELLED]
    
    return {
        "visits": visits,
        "total": len(visits),
        "upcoming": len(upcoming),
        "completed": len(completed),
        "cancelled": len(cancelled)
    }

def get_user_upcoming_visits(db: Session, user_id: int):
    return db.query(Visit).options(
        joinedload(Visit.relationship_manager)
    ).filter(
        and_(
            Visit.user_id == user_id,
            Visit.scheduled_date > datetime.now(),
            Visit.status.in_([VisitStatus.SCHEDULED, VisitStatus.CONFIRMED])
        )
    ).order_by(asc(Visit.scheduled_date)).all()

def get_user_past_visits(db: Session, user_id: int):
    return db.query(Visit).options(
        joinedload(Visit.relationship_manager)
    ).filter(
        and_(
            Visit.user_id == user_id,
            Visit.status.in_([VisitStatus.COMPLETED, VisitStatus.CANCELLED])
        )
    ).order_by(desc(Visit.scheduled_date)).all()

def update_visit(db: Session, visit_id: int, visit_update: VisitUpdate):
    db_visit = get_visit(db, visit_id)
    if not db_visit:
        return None
    
    update_data = visit_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_visit, field, value)
    
    db.commit()
    db.refresh(db_visit)
    return db_visit

def cancel_visit(db: Session, visit_id: int, reason: str):
    db_visit = get_visit(db, visit_id)
    if not db_visit:
        return False
    
    db_visit.status = VisitStatus.CANCELLED
    db_visit.cancellation_reason = reason
    
    db.commit()
    return True

def reschedule_visit(db: Session, visit_id: int, new_date: datetime, reason: Optional[str] = None):
    db_visit = get_visit(db, visit_id)
    if not db_visit:
        return False
    
    db_visit.rescheduled_from = db_visit.scheduled_date
    db_visit.scheduled_date = new_date
    db_visit.status = VisitStatus.RESCHEDULED
    if reason:
        db_visit.cancellation_reason = reason  # Using same field for reschedule reason
    
    db.commit()
    return True

def get_user_relationship_manager(db: Session, user_id: int):
    # Get RM from user's most recent visit
    recent_visit = db.query(Visit).filter(Visit.user_id == user_id).order_by(
        desc(Visit.created_at)
    ).first()
    
    if recent_visit and recent_visit.relationship_manager_id:
        return db.query(RelationshipManager).filter(
            RelationshipManager.id == recent_visit.relationship_manager_id
        ).first()
    
    # If no recent visit, assign a new RM
    return get_available_relationship_manager(db)

def get_available_relationship_manager(db: Session):
    # Simple round-robin assignment based on total visits handled
    return db.query(RelationshipManager).filter(
        RelationshipManager.is_active == True
    ).order_by(asc(RelationshipManager.total_visits_handled)).first()

def create_relationship_manager(db: Session, rm_data: dict):
    db_rm = RelationshipManager(**rm_data)
    db.add(db_rm)
    db.commit()
    db.refresh(db_rm)
    return db_rm

def get_all_relationship_managers(db: Session):
    return db.query(RelationshipManager).filter(
        RelationshipManager.is_active == True
    ).all()

def mark_visit_completed(db: Session, visit_id: int, notes: str = None, feedback: str = None):
    db_visit = get_visit(db, visit_id)
    if not db_visit:
        return False
    
    db_visit.status = VisitStatus.COMPLETED
    db_visit.actual_date = datetime.now()
    if notes:
        db_visit.visit_notes = notes
    if feedback:
        db_visit.visitor_feedback = feedback
    
    db.commit()
    return True