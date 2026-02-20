
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Float, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum
from typing import Optional, List
from datetime import datetime
from app.core.database import Base
from app.models.enums import AgentType, ExperienceLevel

class AgentInteraction(Base):
    """Track all interactions between agents and users."""
    __tablename__ = "agent_interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("agents.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(50), nullable=False)  # chat, call, email
    message: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_time_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_satisfaction: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="interactions")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    contact_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    languages: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    agent_type: Mapped[AgentType] = mapped_column(SQLEnum(AgentType, name='agent_type'), nullable=False)
    experience_level: Mapped[ExperienceLevel] = mapped_column(SQLEnum(ExperienceLevel, name='experience_level'), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    working_hours: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    total_users_assigned: Mapped[int] = mapped_column(Integer, default=0)
    user_satisfaction_rating: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)
    
    users: Mapped[List["User"]] = relationship(back_populates="agent")
    visits: Mapped[List["Visit"]] = relationship(back_populates="agent")
    interactions: Mapped[List["AgentInteraction"]] = relationship(back_populates="agent")
