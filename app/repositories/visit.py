from typing import Optional, Dict, Any
from supabase import Client
from app.db.base import BaseRepository
from app.core.supabase_client import execute_rpc
from app.db.types import VisitDB
from app.schemas.visit import VisitCreate
import anyio
from app.core.logging import get_logger

logger = get_logger(__name__)

class VisitRepository(BaseRepository):
    """Repository for visit operations using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "visits")
    
    async def create_visit(self, visit_data: VisitCreate) -> VisitDB:
        """Create a new visit"""
        data = visit_data.model_dump(exclude_unset=True)
        return await self.create(data)
    
    async def create_visit_with_agent_assignment(self, visit_data: VisitCreate) -> VisitDB:
        """Create a new visit with automatic agent assignment using atomic RPC"""
        try:
            # Try atomic RPC function first
            result = await execute_rpc(
                self.client,
                "create_visit_with_agent_assignment",
                {
                    "p_user_id": visit_data.user_id,
                    "p_property_id": visit_data.property_id,
                    "p_scheduled_date": visit_data.scheduled_date.isoformat(),
                    "p_special_requirements": visit_data.special_requirements
                }
            )
            
            if result:
                # Get the created visit
                visit_id = result
                return await self.get_by_id(visit_id)
        except Exception as e:
            logger.error(f"Failed to create visit via RPC: {str(e)}")
            # Fallback to manual creation with basic agent assignment
            
        # Fallback: manual agent assignment
        try:
            # Get next available agent manually
            agent_result = await execute_rpc(
                self.client,
                "get_next_available_agent",
                {}
            )
            
            if agent_result:
                visit_data.agent_id = agent_result
            
            return await self.create_visit(visit_data)
        except Exception as fallback_e:
            logger.error(f"Fallback visit creation failed: {str(fallback_e)}")
            # Create without agent assignment as last resort
            return await self.create_visit(visit_data)
    
    async def get_user_visits(
        self, 
        user_id: int, 
        page: int = 1, 
        limit: int = 20,
        visit_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get visits for a user with optional filter for upcoming or past visits"""
        filters = {"user_id": user_id}
        
        # Add additional filters based on visit_type
        if visit_type == "upcoming":
            # Use raw query for complex date filtering
            query = self.client.table(self.table_name).select("*, properties(*), agents(*)")
            query = query.eq("user_id", user_id)
            query = query.gte("scheduled_date", "now()")
            query = query.order("scheduled_date", desc=False)
            
            # Apply pagination
            start = (page - 1) * limit
            end = start + limit - 1
            query = query.range(start, end)
            
            result = await anyio.to_thread.run_sync(query.execute)
            return {
                "data": result.data,
                "count": len(result.data)
            }
        elif visit_type == "past":
            # Use raw query for complex date filtering
            query = self.client.table(self.table_name).select("*, properties(*), agents(*)")
            query = query.eq("user_id", user_id)
            query = query.lt("scheduled_date", "now()")
            query = query.order("scheduled_date", desc=True)
            
            # Apply pagination
            start = (page - 1) * limit
            end = start + limit - 1
            query = query.range(start, end)
            
            result = await anyio.to_thread.run_sync(query.execute)
            return {
                "data": result.data,
                "count": len(result.data)
            }
        else:
            # Default: return all visits
            return await self.get_multi(
                filters=filters,
                select="*, properties(*), agents(*)",
                page=page,
                limit=limit,
                sort_field="scheduled_date",
                sort_desc=True
            )
    
    async def get_property_visits(
        self, 
        property_id: int, 
        page: int = 1, 
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get visits for a property"""
        return await self.get_multi(
            filters={"property_id": property_id},
            select="*, users(*), agents(*)",
            page=page,
            limit=limit,
            sort_field="scheduled_date"
        )
    
    async def get_agent_visits(
        self, 
        agent_id: int, 
        page: int = 1, 
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get visits for an agent"""
        return await self.get_multi(
            filters={"agent_id": agent_id},
            select="*, users(*), properties(*)",
            page=page,
            limit=limit,
            sort_field="scheduled_date"
        )
    
    async def update_visit_status(
        self, 
        visit_id: int, 
        status: str
    ) -> Optional[VisitDB]:
        """Update visit status"""
        return await self.update(visit_id, {"status": status})
    
    async def cancel_visit(
        self, 
        visit_id: int, 
        reason: str
    ) -> Optional[VisitDB]:
        """Cancel a visit"""
        return await self.update(visit_id, {
            "status": "cancelled",
            "cancellation_reason": reason
        })
    
    async def reschedule_visit(
        self, 
        visit_id: int, 
        new_date: str
    ) -> Optional[VisitDB]:
        """Reschedule a visit"""
        # Get current visit to store original date
        current_visit = await self.get_by_id(visit_id)
        if not current_visit:
            return None
        
        return await self.update(visit_id, {
            "scheduled_date": new_date,
            "status": "rescheduled",
            "rescheduled_from": current_visit["scheduled_date"]
        })


