
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.core.database import Base
from app.models.enums import (
    AuthMethod,
    Cleanliness,
    FlatmatesMode,
    FlatmatesProfileStatus,
    FoodHabits,
    GuestsPolicy,
    SleepSchedule,
    SmokingDrinking,
    UserRole,
    WorkStyle,
)

if TYPE_CHECKING:
    from app.models.agents import Agent
    from app.models.bookings import Booking
    from app.models.payments import PaymentMethod
    from app.models.properties import Property, Visit
    from app.models.tours import Tour


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Email is the canonical identity-linking key: unique when present.
        # Mirrors migration 20260606000000 (uq_users_email partial unique index).
        Index(
            "uq_users_email",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supabase_user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # RBAC role for the user
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole, name='user_role'), default=UserRole.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Last auth method used (mirrors client login state-machine). TEXT + CHECK
    # constraint in the DB (see migration 20260606000000), typed via AuthMethod.
    last_auth_method: Mapped[AuthMethod | None] = mapped_column(String, nullable=True)
    last_auth_method_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    preferences: Mapped[dict | None] = mapped_column(JSON, default=dict)
    current_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    notification_settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    privacy_settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    flatmates_mode: Mapped[FlatmatesMode | None] = mapped_column(SQLEnum(FlatmatesMode, name='flatmates_mode'), nullable=True)
    flatmates_profile_status: Mapped[FlatmatesProfileStatus] = mapped_column(SQLEnum(FlatmatesProfileStatus, name='flatmates_profile_status'), default=FlatmatesProfileStatus.draft)
    flatmates_onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    stays_onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    estate_onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    ghar360_onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    flatmates_bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    flatmates_budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    flatmates_budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    flatmates_move_in_timeline: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flatmates_city: Mapped[str | None] = mapped_column(String, nullable=True)
    flatmates_locality: Mapped[str | None] = mapped_column(String, nullable=True)
    flatmates_sleep_schedule: Mapped[SleepSchedule | None] = mapped_column(SQLEnum(SleepSchedule, name="flatmates_sleep_schedule_type"), nullable=True)
    flatmates_cleanliness: Mapped[Cleanliness | None] = mapped_column(SQLEnum(Cleanliness, name="flatmates_cleanliness_type"), nullable=True)
    flatmates_food_habits: Mapped[FoodHabits | None] = mapped_column(SQLEnum(FoodHabits, name="flatmates_food_habits_type"), nullable=True)
    flatmates_smoking_drinking: Mapped[SmokingDrinking | None] = mapped_column(SQLEnum(SmokingDrinking, name="flatmates_smoking_drinking_type"), nullable=True)
    flatmates_guests_policy: Mapped[GuestsPolicy | None] = mapped_column(SQLEnum(GuestsPolicy, name="flatmates_guests_policy_type"), nullable=True)
    flatmates_work_style: Mapped[WorkStyle | None] = mapped_column(SQLEnum(WorkStyle, name="flatmates_work_style_type"), nullable=True)
    flatmates_last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_seed_data: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    agent: Mapped[Agent | None] = relationship(back_populates="users")
    owned_properties: Mapped[list[Property]] = relationship(
        "Property",
        back_populates="owner",
        foreign_keys="Property.owner_id",
    )
    swipes: Mapped[list[UserSwipe]] = relationship(
        "UserSwipe",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserSwipe.user_id",
    )
    visits: Mapped[list[Visit]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Visit.user_id",
    )
    bookings: Mapped[list[Booking]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tours: Mapped[list[Tour]] = relationship("Tour", back_populates="user", cascade="all, delete-orphan")
    payment_methods: Mapped[list[PaymentMethod]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSearchHistory(Base):
    __tablename__ = "user_search_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    search_query: Mapped[str | None] = mapped_column(String, nullable=True)
    search_filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    search_location: Mapped[str | None] = mapped_column(String, nullable=True)
    search_radius: Mapped[int | None] = mapped_column(Integer, nullable=True)
    results_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_type: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSwipe(Base):
    __tablename__ = "user_swipes"
    __table_args__ = (
        Index('idx_user_swipes_unique', 'user_id', 'property_id', unique=True),
        Index('idx_user_swipes_target_user', 'user_id', 'target_user_id'),
        Index('idx_user_swipes_target_type', 'user_id', 'target_type'),
        Index(
            'idx_user_swipes_unique_target_user',
            'user_id', 'target_user_id',
            unique=True,
            postgresql_where=text('target_user_id IS NOT NULL'),
        ),
        Index('idx_user_swipes_created_at', 'created_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=True,
    )
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    context_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_type: Mapped[str] = mapped_column(String(20), default="property")
    swipe_action: Mapped[str] = mapped_column(String(20), default="like")
    is_liked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    user: Mapped[User] = relationship(back_populates="swipes", foreign_keys=[user_id])
    property: Mapped[Property | None] = relationship(
        back_populates="swipes",
        foreign_keys=[property_id],
    )
    target_user: Mapped[User | None] = relationship(foreign_keys=[target_user_id])
    context_property: Mapped[Property | None] = relationship(
        foreign_keys=[context_property_id],
    )
