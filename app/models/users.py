
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey, JSON, Text, Float, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from datetime import datetime
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    supabase_user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    profile_image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # RBAC role for the user: 'user' | 'agent' | 'admin'
    role: Mapped[str] = mapped_column(String(20), default='user')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[Optional[dict]] = mapped_column(JSON, default={})
    current_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notification_settings: Mapped[Optional[dict]] = mapped_column(JSON, default={})
    privacy_settings: Mapped[Optional[dict]] = mapped_column(JSON, default={})
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)
    
    # Relationships
    agent: Mapped[Optional["Agent"]] = relationship(back_populates="users")
    owned_properties: Mapped[List["Property"]] = relationship(
        "Property",
        back_populates="owner",
        foreign_keys="Property.owner_id",
    )
    swipes: Mapped[List["UserSwipe"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    visits: Mapped[List["Visit"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tours: Mapped[List["Tour"]] = relationship("Tour", back_populates="user", cascade="all, delete-orphan")


class UserSearchHistory(Base):
    __tablename__ = "user_search_history"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    search_query: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    search_filters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    search_location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    search_radius: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    results_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_location_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_location_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    search_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserSwipe(Base):
    __tablename__ = "user_swipes"
    __table_args__ = (
        Index('idx_user_swipes_unique', 'user_id', 'property_id', unique=True),
    )
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    is_liked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)
    
    user: Mapped["User"] = relationship(back_populates="swipes")
    property: Mapped["Property"] = relationship(back_populates="swipes")
