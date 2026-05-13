from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import AgentType, ExperienceLevel


class AgentBase(BaseModel):
    name: str
    contact_number: str | None = None
    description: str | None = None
    avatar_url: str | None = None
    languages: list[str] | None = ["english"]

class AgentCreate(AgentBase):
    agent_type: AgentType = AgentType.general
    experience_level: ExperienceLevel = ExperienceLevel.intermediate
    working_hours: dict[str, Any] | None = {
        "start": "09:00",
        "end": "18:00",
        "timezone": "UTC"
    }


class AgentUpdate(BaseModel):
    name: str | None = None
    contact_number: str | None = None
    description: str | None = None
    avatar_url: str | None = None
    languages: list[str] | None = None
    agent_type: AgentType | None = None
    experience_level: ExperienceLevel | None = None
    is_active: bool | None = None
    is_available: bool | None = None
    working_hours: dict[str, Any] | None = None

class Agent(AgentBase):
    id: int
    agent_type: AgentType
    experience_level: ExperienceLevel
    is_active: bool
    is_available: bool
    working_hours: dict[str, Any] | None = None
    total_users_assigned: int
    user_satisfaction_rating: float
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

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
    assignment_reason: str | None = "auto_assigned"

    model_config = ConfigDict(from_attributes=True)

class AgentInteraction(BaseModel):
    id: int
    user_id: int
    agent_id: int
    interaction_type: str  # chat, call, email, etc.
    message: str
    response: str | None = None
    response_time_seconds: int | None = None
    user_satisfaction: int | None = None  # 1-5 rating
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

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
    supported_languages: list[str] = ["english"]
    working_hours: dict[str, Any] = {
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
    agents_by_type: dict[str, int]
    load_distribution: list[AgentWorkload]
