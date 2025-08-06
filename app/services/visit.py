from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from app.repositories.visit import VisitRepository
from app.schemas.visit import VisitCreate, VisitUpdate
from typing import Optional

async def create_visit(db: AsyncSession, user_id: int, visit: VisitCreate):
    visit_repo = VisitRepository(db)
    return await visit_repo.create_visit(user_id, visit)

async def get_visit(db: AsyncSession, visit_id: int):
    visit_repo = VisitRepository(db)
    return await visit_repo.get_with_rm(visit_id)

async def get_user_visits(db: AsyncSession, user_id: int):
    visit_repo = VisitRepository(db)
    return await visit_repo.get_user_visits(user_id)

async def get_user_upcoming_visits(db: AsyncSession, user_id: int):
    visit_repo = VisitRepository(db)
    return await visit_repo.get_user_upcoming_visits(user_id)

async def get_user_past_visits(db: AsyncSession, user_id: int):
    visit_repo = VisitRepository(db)
    return await visit_repo.get_user_past_visits(user_id)

async def update_visit(db: AsyncSession, visit_id: int, visit_update: VisitUpdate):
    visit_repo = VisitRepository(db)
    return await visit_repo.update_visit(visit_id, visit_update)

async def cancel_visit(db: AsyncSession, visit_id: int, reason: str):
    visit_repo = VisitRepository(db)
    return await visit_repo.cancel_visit(visit_id, reason)

async def reschedule_visit(db: AsyncSession, visit_id: int, new_date: datetime, reason: Optional[str] = None):
    visit_repo = VisitRepository(db)
    return await visit_repo.reschedule_visit(visit_id, new_date, reason)

async def get_user_relationship_manager(db: AsyncSession, user_id: int):
    visit_repo = VisitRepository(db)
    return await visit_repo.get_user_relationship_manager(user_id)

async def get_available_relationship_manager(db: AsyncSession):
    visit_repo = VisitRepository(db)
    return await visit_repo.get_available_relationship_manager()

async def create_relationship_manager(db: AsyncSession, rm_data: dict):
    visit_repo = VisitRepository(db)
    return await visit_repo.create_relationship_manager(rm_data)

async def get_all_relationship_managers(db: AsyncSession):
    visit_repo = VisitRepository(db)
    return await visit_repo.get_all_relationship_managers()

async def mark_visit_completed(db: AsyncSession, visit_id: int, notes: str = None, feedback: str = None):
    visit_repo = VisitRepository(db)
    return await visit_repo.mark_visit_completed(visit_id, notes, feedback)