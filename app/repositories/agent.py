from supabase import Client
from typing import Optional, List, Dict, Any
import anyio
from app.db.base import BaseRepository
from app.db.types import AgentDB

class AgentRepository(BaseRepository):
    """Repository for agent operations using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "agents")
    
    async def get_all_agents(self) -> List[AgentDB]:
        """Get all agents"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select("*").execute()
            )
            return result.data or []
        except Exception:
            return []
    
    async def get_active_agents(self) -> List[AgentDB]:
        """Get all active agents"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select("*").eq("is_active", True).execute()
            )
            return result.data or []
        except Exception:
            return []
    
    async def get_available_agents(self) -> List[AgentDB]:
        """Get all available agents (active and available)"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("*")
                    .eq("is_active", True)
                    .eq("is_available", True)
                    .execute()
                )
            )
            return result.data or []
        except Exception:
            return []
    
    async def get_agent_by_code(self, agent_code: str) -> Optional[AgentDB]:
        """Get agent by unique agent code"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("*")
                    .eq("agent_code", agent_code.upper())
                    .limit(1)
                    .execute()
                )
            )
            return result.data[0] if result.data else None
        except Exception:
            return None
    
    async def get_agent_with_least_users(self) -> Optional[AgentDB]:
        """Get available agent with least assigned users for load balancing"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("*")
                    .eq("is_active", True)
                    .eq("is_available", True)
                    .order("total_users_assigned")
                    .limit(1)
                    .execute()
                )
            )
            return result.data[0] if result.data else None
        except Exception:
            return None
    
    async def get_user_agent(self, user_id: int) -> Optional[AgentDB]:
        """Get the assigned agent for a user"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.client
                    .table("users")
                    .select("agents(*)")
                    .eq("id", user_id)
                    .execute()
                )
            )
            if result.data and result.data[0].get("agents"):
                return result.data[0]["agents"]
            return None
        except Exception:
            return None
    
    async def assign_agent_to_user(self, user_id: int, agent_id: int) -> bool:
        """Assign an agent to a user"""
        try:
            # Update user's agent_id
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.client
                    .table("users")
                    .update({"agent_id": agent_id})
                    .eq("id", user_id)
                    .execute()
                )
            )
            
            if result.data:
                # Increment agent's user count
                await self.increment_user_count(agent_id)
                return True
            return False
        except Exception:
            return False
    
    async def increment_user_count(self, agent_id: int) -> bool:
        """Increment the total_users_assigned count for an agent"""
        try:
            # First get current count
            agent = await self.get_by_id(agent_id)
            if not agent:
                return False
            
            new_count = agent.get("total_users_assigned", 0) + 1
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .update({"total_users_assigned": new_count})
                    .eq("id", agent_id)
                    .execute()
                )
            )
            return bool(result.data)
        except Exception:
            return False
    
    async def decrement_user_count(self, agent_id: int) -> bool:
        """Decrement the total_users_assigned count for an agent"""
        try:
            # First get current count
            agent = await self.get_by_id(agent_id)
            if not agent:
                return False
            
            current_count = agent.get("total_users_assigned", 0)
            new_count = max(0, current_count - 1)  # Don't go below 0
            
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .update({"total_users_assigned": new_count})
                    .eq("id", agent_id)
                    .execute()
                )
            )
            return bool(result.data)
        except Exception:
            return False
    
    async def get_agent_stats(self, agent_id: int) -> Dict[str, Any]:
        """Get statistics for an agent"""
        try:
            # Get user count assigned to this agent
            user_count_result = await anyio.to_thread.run_sync(
                lambda: (
                    self.client
                    .table("users")
                    .select("id", count="exact")
                    .eq("agent_id", agent_id)
                    .execute()
                )
            )
            
            # Get the agent data for other stats
            agent = await self.get_by_id(agent_id)
            if not agent:
                return {}
            
            current_users = user_count_result.count or 0
            max_users = agent.get("max_concurrent_users", 50)
            
            return {
                "total_users_assigned": agent.get("total_users_assigned", 0),
                "current_active_users": current_users,
                "total_interactions": agent.get("total_interactions", 0),
                "average_response_time_seconds": agent.get("average_response_time_seconds", 30),
                "user_satisfaction_rating": agent.get("user_satisfaction_rating", 0.0),
                "utilization_percentage": (current_users / max_users * 100) if max_users > 0 else 0,
                "max_concurrent_users": max_users,
                "is_available": agent.get("is_available", False),
                "queue_length": max(0, current_users - max_users) if current_users > max_users else 0
            }
        except Exception:
            return {}
    
    async def get_agents_by_specialization(self, specialization: str) -> List[AgentDB]:
        """Get agents that have a specific specialization"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("*")
                    .eq("is_active", True)
                    .contains("specializations", [specialization])
                    .execute()
                )
            )
            return result.data or []
        except Exception:
            return []
    
    async def get_agents_by_type(self, agent_type: str) -> List[AgentDB]:
        """Get agents by type (general, specialist, senior)"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .select("*")
                    .eq("is_active", True)
                    .eq("agent_type", agent_type)
                    .execute()
                )
            )
            return result.data or []
        except Exception:
            return []
    
    async def update_agent_availability(self, agent_id: int, is_available: bool) -> bool:
        """Update agent availability status"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .update({"is_available": is_available})
                    .eq("id", agent_id)
                    .execute()
                )
            )
            return bool(result.data)
        except Exception:
            return False
    
    async def update_last_active(self, agent_id: int) -> bool:
        """Update agent's last active timestamp"""
        try:
            from datetime import datetime
            result = await anyio.to_thread.run_sync(
                lambda: (
                    self.table
                    .update({"last_active_at": datetime.utcnow().isoformat()})
                    .eq("id", agent_id)
                    .execute()
                )
            )
            return bool(result.data)
        except Exception:
            return False
    
    async def get_workload_distribution(self) -> List[Dict[str, Any]]:
        """Get workload distribution across all active agents"""
        try:
            agents = await self.get_active_agents()
            workload = []
            
            for agent in agents:
                stats = await self.get_agent_stats(agent["id"])
                workload.append({
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "agent_code": agent["agent_code"],
                    "current_users": stats.get("current_active_users", 0),
                    "max_users": stats.get("max_concurrent_users", 50),
                    "utilization_percentage": stats.get("utilization_percentage", 0),
                    "is_available": agent.get("is_available", False),
                    "queue_length": stats.get("queue_length", 0)
                })
            
            return sorted(workload, key=lambda x: x["utilization_percentage"], reverse=True)
        except Exception:
            return []