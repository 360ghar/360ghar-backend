from supabase import Client
from datetime import datetime
from app.repositories.visit import VisitRepository
from app.schemas.visit import VisitCreate, VisitUpdate
from app.services.agent import get_user_agent
from typing import Optional, Dict, Any

async def create_visit(supabase: Client, visit_data: VisitCreate):
    """Create a new visit with automatic agent assignment"""
    visit_repo = VisitRepository(supabase)
    
    # Ensure user has an agent assigned and get it
    user_agent = await get_user_agent(supabase, visit_data.user_id, auto_assign=True)
    if user_agent:
        visit_data.agent_id = user_agent.id
    
    return await visit_repo.create_visit_with_agent_assignment(visit_data)

async def get_visit(supabase: Client, visit_id: int):
    """Get visit by ID"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.get_by_id(visit_id)

async def get_user_visits(supabase: Client, user_id: int, page: int = 1, limit: int = 20, visit_type: Optional[str] = None):
    """Get user's visits with optional filter for upcoming or past visits"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.get_user_visits(user_id, page, limit, visit_type)

async def get_property_visits(supabase: Client, property_id: int, page: int = 1, limit: int = 20):
    """Get property's visits"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.get_property_visits(property_id, page, limit)

async def get_agent_visits(supabase: Client, agent_id: int, page: int = 1, limit: int = 20):
    """Get agent's visits"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.get_agent_visits(agent_id, page, limit)

async def update_visit_status(supabase: Client, visit_id: int, status: str):
    """Update visit status"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.update_visit_status(visit_id, status)

async def cancel_visit(supabase: Client, visit_id: int, reason: str):
    """Cancel a visit"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.cancel_visit(visit_id, reason)

async def reschedule_visit(supabase: Client, visit_id: int, new_date: str):
    """Reschedule a visit"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.reschedule_visit(visit_id, new_date)

async def get_available_agents(supabase: Client):
    """Get available agents"""
    from app.services.agent import get_available_agents
    return await get_available_agents(supabase)

async def assign_agent_to_visit(supabase: Client, visit_id: int, agent_id: int):
    """Assign agent to visit"""
    visit_repo = VisitRepository(supabase)
    return await visit_repo.update(visit_id, {"agent_id": agent_id})