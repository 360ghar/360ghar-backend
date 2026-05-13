
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import AgentType, ExperienceLevel

if TYPE_CHECKING:
    from app.models.properties import Visit
    from app.models.users import User

class AgentInteraction(Base):
    """Track all interactions between agents and users."""
    __tablename__ = "agent_interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("agents.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(50), nullable=False)  # chat, call, email
    message: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    agent: Mapped[Agent] = relationship(back_populates="interactions")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    contact_number: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    languages: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    agent_type: Mapped[AgentType] = mapped_column(SQLEnum(AgentType, name='agent_type'), nullable=False)
    experience_level: Mapped[ExperienceLevel] = mapped_column(SQLEnum(ExperienceLevel, name='experience_level'), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    working_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_users_assigned: Mapped[int] = mapped_column(Integer, default=0)
    user_satisfaction_rating: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    users: Mapped[list[User]] = relationship(back_populates="agent")
    visits: Mapped[list[Visit]] = relationship(back_populates="agent")
    interactions: Mapped[list[AgentInteraction]] = relationship(back_populates="agent")
