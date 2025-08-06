from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, asc
from sqlalchemy.orm import selectinload, joinedload
from datetime import datetime
from app.repositories.base import BaseRepository
from app.models.visit import Visit, RelationshipManager, VisitStatus
from app.schemas.visit import VisitCreate, VisitUpdate

class VisitRepository(BaseRepository[Visit]):
    """Repository for visit-related database operations"""
    
    def __init__(self, session: AsyncSession):
        super().__init__(Visit, session)
    
    async def create_visit(self, user_id: int, visit: VisitCreate) -> Visit:
        """Create a new visit with automatic RM assignment"""
        # Assign a relationship manager (simple round-robin for now)
        rm = await self.get_available_relationship_manager()
        
        new_visit = Visit(
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
        
        self.session.add(new_visit)
        await self.session.flush()
        await self.session.refresh(new_visit)
        
        # Update RM's visit count
        if rm:
            rm.total_visits_handled += 1
            await self.session.flush()
        
        return new_visit
    
    async def get_with_rm(self, visit_id: int) -> Optional[Visit]:
        """Get visit with relationship manager details loaded"""
        return await self.get(
            visit_id,
            load_options=[joinedload(Visit.relationship_manager)]
        )
    
    async def get_user_visits(self, user_id: int) -> Dict[str, Any]:
        """Get all visits for a user with statistics"""
        visits_result = await self.session.execute(
            select(Visit)
            .options(joinedload(Visit.relationship_manager))
            .where(Visit.user_id == user_id)
            .order_by(desc(Visit.scheduled_date))
        )
        visits = visits_result.scalars().all()
        
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
    
    async def get_user_upcoming_visits(self, user_id: int) -> List[Visit]:
        """Get upcoming visits for a user"""
        result = await self.session.execute(
            select(Visit)
            .options(joinedload(Visit.relationship_manager))
            .where(
                and_(
                    Visit.user_id == user_id,
                    Visit.scheduled_date > datetime.now(),
                    Visit.status.in_([VisitStatus.SCHEDULED, VisitStatus.CONFIRMED])
                )
            ).order_by(asc(Visit.scheduled_date))
        )
        return result.scalars().all()
    
    async def get_user_past_visits(self, user_id: int) -> List[Visit]:
        """Get past visits for a user"""
        result = await self.session.execute(
            select(Visit)
            .options(joinedload(Visit.relationship_manager))
            .where(
                and_(
                    Visit.user_id == user_id,
                    Visit.status.in_([VisitStatus.COMPLETED, VisitStatus.CANCELLED])
                )
            ).order_by(desc(Visit.scheduled_date))
        )
        return result.scalars().all()
    
    async def update_visit(self, visit_id: int, visit_update: VisitUpdate) -> Optional[Visit]:
        """Update visit details"""
        visit = await self.get(visit_id)
        
        update_data = visit_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(visit, field):
                setattr(visit, field, value)
        
        await self.session.flush()
        await self.session.refresh(visit)
        return visit
    
    async def cancel_visit(self, visit_id: int, reason: str) -> bool:
        """Cancel a visit"""
        visit = await self.get(visit_id)
        visit.status = VisitStatus.CANCELLED
        visit.cancellation_reason = reason
        await self.session.flush()
        return True
    
    async def reschedule_visit(self, visit_id: int, new_date: datetime, reason: Optional[str] = None) -> bool:
        """Reschedule a visit to a new date"""
        visit = await self.get(visit_id)
        visit.rescheduled_from = visit.scheduled_date
        visit.scheduled_date = new_date
        visit.status = VisitStatus.RESCHEDULED
        if reason:
            visit.cancellation_reason = reason  # Using same field for reschedule reason
        await self.session.flush()
        return True
    
    async def mark_visit_completed(self, visit_id: int, notes: str = None, feedback: str = None) -> bool:
        """Mark visit as completed with optional notes and feedback"""
        visit = await self.get(visit_id)
        visit.status = VisitStatus.COMPLETED
        visit.actual_date = datetime.now()
        if notes:
            visit.visit_notes = notes
        if feedback:
            visit.visitor_feedback = feedback
        await self.session.flush()
        return True
    
    async def get_property_visits(self, property_id: int, status_filter: Optional[List[VisitStatus]] = None) -> List[Visit]:
        """Get all visits for a property"""
        query = select(Visit).options(
            joinedload(Visit.relationship_manager),
            joinedload(Visit.user)
        ).where(Visit.property_id == property_id)
        
        if status_filter:
            query = query.where(Visit.status.in_(status_filter))
        
        query = query.order_by(desc(Visit.scheduled_date))
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_rm_visits(
        self,
        rm_id: int,
        date_filter: Optional[datetime] = None,
        status_filter: Optional[List[VisitStatus]] = None
    ) -> List[Visit]:
        """Get all visits assigned to a relationship manager"""
        query = select(Visit).options(
            joinedload(Visit.user),
            joinedload(Visit.property)
        ).where(Visit.relationship_manager_id == rm_id)
        
        if date_filter:
            query = query.where(Visit.scheduled_date >= date_filter)
        
        if status_filter:
            query = query.where(Visit.status.in_(status_filter))
        
        query = query.order_by(asc(Visit.scheduled_date))
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    # Relationship Manager operations
    async def get_user_relationship_manager(self, user_id: int) -> Optional[RelationshipManager]:
        """Get the relationship manager for a user based on most recent visit"""
        # Get RM from user's most recent visit
        recent_visit_result = await self.session.execute(
            select(Visit).where(Visit.user_id == user_id).order_by(desc(Visit.created_at)).limit(1)
        )
        recent_visit = recent_visit_result.scalar_one_or_none()
        
        if recent_visit and recent_visit.relationship_manager_id:
            rm_result = await self.session.execute(
                select(RelationshipManager).where(RelationshipManager.id == recent_visit.relationship_manager_id)
            )
            return rm_result.scalar_one_or_none()
        
        # If no recent visit, assign a new RM
        return await self.get_available_relationship_manager()
    
    async def get_available_relationship_manager(self) -> Optional[RelationshipManager]:
        """Get the next available relationship manager using round-robin assignment"""
        result = await self.session.execute(
            select(RelationshipManager)
            .where(RelationshipManager.is_active == True)
            .order_by(asc(RelationshipManager.total_visits_handled))
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def create_relationship_manager(self, rm_data: dict) -> RelationshipManager:
        """Create a new relationship manager"""
        rm = RelationshipManager(**rm_data)
        self.session.add(rm)
        await self.session.flush()
        await self.session.refresh(rm)
        return rm
    
    async def get_all_relationship_managers(self, active_only: bool = True) -> List[RelationshipManager]:
        """Get all relationship managers"""
        query = select(RelationshipManager)
        if active_only:
            query = query.where(RelationshipManager.is_active == True)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_relationship_manager(self, rm_id: int) -> Optional[RelationshipManager]:
        """Get relationship manager by ID"""
        result = await self.session.execute(
            select(RelationshipManager).where(RelationshipManager.id == rm_id)
        )
        return result.scalar_one_or_none()
    
    async def update_relationship_manager(self, rm_id: int, rm_data: dict) -> Optional[RelationshipManager]:
        """Update relationship manager details"""
        rm = await self.get_relationship_manager(rm_id)
        if not rm:
            return None
        
        for field, value in rm_data.items():
            if hasattr(rm, field):
                setattr(rm, field, value)
        
        await self.session.flush()
        await self.session.refresh(rm)
        return rm
    
    async def get_rm_performance_stats(self, rm_id: int) -> Dict[str, Any]:
        """Get performance statistics for a relationship manager"""
        # Get all visits handled by this RM
        visits_result = await self.session.execute(
            select(Visit).where(Visit.relationship_manager_id == rm_id)
        )
        visits = visits_result.scalars().all()
        
        total_visits = len(visits)
        completed_visits = len([v for v in visits if v.status == VisitStatus.COMPLETED])
        cancelled_visits = len([v for v in visits if v.status == VisitStatus.CANCELLED])
        
        completion_rate = (completed_visits / total_visits * 100) if total_visits > 0 else 0
        
        return {
            "total_visits": total_visits,
            "completed_visits": completed_visits,
            "cancelled_visits": cancelled_visits,
            "completion_rate_percentage": round(completion_rate, 2)
        }