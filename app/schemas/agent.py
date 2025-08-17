from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.db.types import AgentType, ExperienceLevel, ResponseStyle

class AgentBase(BaseModel):
    name: str
    agent_code: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    personality_traits: Optional[Dict[str, Any]] = {}
    specializations: Optional[List[str]] = []
    languages: Optional[List[str]] = ["english"]

class AgentCreate(AgentBase):
    agent_type: AgentType = AgentType.GENERAL
    experience_level: ExperienceLevel = ExperienceLevel.INTERMEDIATE
    max_concurrent_users: int = 50
    ai_model: str = "gpt-4"
    system_prompt: Optional[str] = None
    response_style: ResponseStyle = ResponseStyle.CONVERSATIONAL
    working_hours: Optional[Dict[str, Any]] = {
        "start": "09:00",
        "end": "18:00", 
        "timezone": "UTC"
    }

    @validator('agent_code')
    def validate_agent_code(cls, v):
        if not v.startswith('AGENT_'):
            raise ValueError('Agent code must start with "AGENT_"')
        if len(v) < 7:  # AGENT_ + at least 1 char
            raise ValueError('Agent code must be at least 7 characters')
        return v.upper()

    @validator('max_concurrent_users')
    def validate_max_users(cls, v):
        if v < 1 or v > 1000:
            raise ValueError('Max concurrent users must be between 1 and 1000')
        return v

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    personality_traits: Optional[Dict[str, Any]] = None
    specializations: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    agent_type: Optional[AgentType] = None
    experience_level: Optional[ExperienceLevel] = None
    max_concurrent_users: Optional[int] = None
    ai_model: Optional[str] = None
    system_prompt: Optional[str] = None
    response_style: Optional[ResponseStyle] = None
    is_active: Optional[bool] = None
    is_available: Optional[bool] = None
    working_hours: Optional[Dict[str, Any]] = None

    @validator('max_concurrent_users')
    def validate_max_users(cls, v):
        if v is not None and (v < 1 or v > 1000):
            raise ValueError('Max concurrent users must be between 1 and 1000')
        return v

class Agent(AgentBase):
    id: int
    agent_type: AgentType
    experience_level: ExperienceLevel
    max_concurrent_users: int
    ai_model: str
    system_prompt: Optional[str] = None
    response_style: ResponseStyle
    is_active: bool
    is_available: bool
    working_hours: Optional[Dict[str, Any]] = None
    total_users_assigned: int
    total_interactions: int
    average_response_time_seconds: int
    user_satisfaction_rating: float
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class AgentStats(BaseModel):
    total_users_assigned: int
    total_interactions: int
    average_response_time_seconds: int
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
    total_interactions: int
    average_response_time: float
    user_satisfaction_score: float
    successful_resolutions: int
    escalations: int
    active_users: int

class AgentWorkload(BaseModel):
    agent_id: int
    agent_name: str
    current_users: int
    max_users: int
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
    total_interactions_today: int
    average_response_time: float
    system_satisfaction_score: float
    agents_by_type: Dict[str, int]
    load_distribution: List[AgentWorkload]