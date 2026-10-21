from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import AgentType, ExperienceLevel
from app.schemas.base import Money, NotNullable, PatchModel, UtcDateTime, WriteModel


class AgentBase(BaseModel):
    name: str
    contact_number: str | None = None
    description: str | None = None
    avatar_url: str | None = None
    languages: list[str] | None = ["english"]


class AgentCreate(WriteModel, AgentBase):
    agent_type: AgentType = AgentType.general
    experience_level: ExperienceLevel = ExperienceLevel.intermediate
    working_hours: dict[str, Any] | None = {"start": "09:00", "end": "18:00", "timezone": "UTC"}


class AgentUpdate(PatchModel):
    """Partial update. Only fields the client sent are applied. Required fields reject null."""

    name: Annotated[str | None, NotNullable] = None
    contact_number: str | None = None
    description: str | None = None
    avatar_url: str | None = None
    languages: list[str] | None = None
    agent_type: Annotated[AgentType | None, NotNullable] = None
    experience_level: Annotated[ExperienceLevel | None, NotNullable] = None
    is_active: Annotated[bool | None, NotNullable] = None
    is_available: Annotated[bool | None, NotNullable] = None
    working_hours: dict[str, Any] | None = None


class AgentAvailabilityUpdate(WriteModel):
    is_available: bool


class Agent(AgentBase):
    id: int
    agent_type: AgentType
    experience_level: ExperienceLevel
    is_active: bool
    is_available: bool
    working_hours: dict[str, Any] | None = None
    total_users_assigned: int
    user_satisfaction_rating: float
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

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
    assigned_at: UtcDateTime
    assignment_reason: str | None = "auto_assigned"

    model_config = ConfigDict(from_attributes=True)


class AgentWorkload(BaseModel):
    agent_id: int
    agent_name: str
    current_users: int
    utilization_percentage: float
    is_available: bool
    queue_length: int


# System-level schemas
class AgentSystemStats(BaseModel):
    total_agents: int
    active_agents: int
    total_users_served: int
    system_satisfaction_score: float
    agents_by_type: dict[str, int]
    load_distribution: list[AgentWorkload]
    # Platform-wide aggregates consumed by the admin dashboard / analytics
    # (see services/agent/analytics.py get_system_stats for exact semantics).
    active_users: int
    properties_listed: int
    occupancy_rate: float
    total_bookings: int
    total_visits: int
    total_revenue: Money
