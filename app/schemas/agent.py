from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.enums import AgentType, ExperienceLevel

class AgentBase(BaseModel):
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    languages: Optional[List[str]] = ["english"]

class AgentCreate(AgentBase):
    agent_type: AgentType = AgentType.general
    experience_level: ExperienceLevel = ExperienceLevel.intermediate
    working_hours: Optional[Dict[str, Any]] = {
        "start": "09:00",
        "end": "18:00", 
        "timezone": "UTC"
    }


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    languages: Optional[List[str]] = None
    agent_type: Optional[AgentType] = None
    experience_level: Optional[ExperienceLevel] = None
    is_active: Optional[bool] = None
    is_available: Optional[bool] = None
    working_hours: Optional[Dict[str, Any]] = None

class Agent(AgentBase):
    id: int
    agent_type: AgentType
    experience_level: ExperienceLevel
    is_active: bool
    is_available: bool
    working_hours: Optional[Dict[str, Any]] = None
    total_users_assigned: int
    user_satisfaction_rating: float
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class AgentStats(BaseModel):
    total_users_assigned: int
    user_satisfaction_rating: float
    active_conversations: int
    daily_interactions: int
    weekly_interactions: int
    efficiency_score: float

class AgentWithStats(Agent):
    stats: AgentStats

class AgentAssignment(BaseModel):
    user_id: int
    agent: Agent
    assigned_at: datetime
    assignment_reason: Optional[str] = "auto_assigned"
    
    class Config:
        from_attributes = True

class AgentInteraction(BaseModel):
    id: int
    user_id: int
    agent_id: int
    interaction_type: str  # chat, call, email, etc.
    message: str
    response: Optional[str] = None
    response_time_seconds: Optional[int] = None
    user_satisfaction: Optional[int] = None  # 1-5 rating
    created_at: datetime
    
    class Config:
        from_attributes = True

class AgentPerformanceMetrics(BaseModel):
    agent_id: int
    date: datetime
    user_satisfaction_score: float
    successful_resolutions: int
    escalations: int
    active_users: int

class AgentWorkload(BaseModel):
    agent_id: int
    agent_name: str
    current_users: int
    utilization_percentage: float
    is_available: bool
    queue_length: int

class AgentCapabilities(BaseModel):
    agent_id: int
    can_handle_bookings: bool = True
    can_handle_property_search: bool = True
    can_handle_visits: bool = True
    can_handle_complaints: bool = True
    can_escalate_to_human: bool = True
    supported_languages: List[str] = ["english"]
    working_hours: Dict[str, Any] = {
        "start": "09:00",
        "end": "18:00",
        "timezone": "UTC"
    }

# System-level schemas
class AgentSystemStats(BaseModel):
    total_agents: int
    active_agents: int
    total_users_served: int
    system_satisfaction_score: float
    agents_by_type: Dict[str, int]
    load_distribution: List[AgentWorkload]