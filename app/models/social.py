import logging
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, TypeVar

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.database import Base
from app.models.enums import (
    UserMatchStatus,
    UserReportReason,
    UserReportStatus,
)

if TYPE_CHECKING:
    from app.models.properties import Property


logger = logging.getLogger(__name__)

SocialEnum = TypeVar("SocialEnum", bound=Enum)


class EnumStringType(TypeDecorator[str]):
    """Store str-backed enums as strings while validating ORM writes."""

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[SocialEnum], *, length: int = 32) -> None:
        self.enum_cls = enum_cls
        self.valid_values = frozenset(member.value for member in enum_cls)
        super().__init__(length=length)

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        if isinstance(value, str) and value in self.valid_values:
            return value
        allowed = ", ".join(sorted(self.valid_values))
        raise ValueError(
            f"Invalid {self.enum_cls.__name__} value {value!r}; expected one of: {allowed}"
        )

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        try:
            return self.enum_cls(value)
        except ValueError:
            logger.warning(
                "Unknown %s value %r in database; returning raw string. "
                "Run a data-cleaning pass to resolve.",
                self.enum_cls.__name__,
                value,
            )
            return value


def enum_check_constraint(column_name: str, enum_cls: type[SocialEnum], name: str) -> CheckConstraint:
    """Build a DB-level check constraint for a controlled enum value set."""
    quoted_values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column_name} IN ({quoted_values})", name=name)


class UserMatch(Base):
    __tablename__ = "user_matches"
    __table_args__ = (
        Index("idx_user_matches_unique_pair", "user_one_id", "user_two_id", unique=True),
        Index("idx_user_matches_status", "status"),
        enum_check_constraint("status", UserMatchStatus, "ck_user_matches_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_one_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_two_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    context_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[UserMatchStatus] = mapped_column(
        EnumStringType(UserMatchStatus), default=UserMatchStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )

    context_property: Mapped["Property | None"] = relationship(
        "Property",
        foreign_keys=[context_property_id],
    )


class FlatmateSuperLikeUsage(Base):
    __tablename__ = "flatmate_super_like_usage"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "target_user_id",
            "used_on",
            name="uq_flatmate_super_like_usage_target_day",
        ),
        Index("idx_flatmate_super_like_usage_user_day", "user_id", "used_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    used_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserBlock(Base):
    __tablename__ = "user_blocks"
    __table_args__ = (
        Index("idx_user_blocks_unique_pair", "blocker_user_id", "blocked_user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    blocker_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    blocked_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserReport(Base):
    __tablename__ = "user_reports"
    __table_args__ = (
        Index("idx_user_reports_reported_user", "reported_user_id", "status"),
        Index("idx_user_reports_reporter_user", "reporter_user_id", "created_at"),
        enum_check_constraint("reason", UserReportReason, "ck_user_reports_reason"),
        enum_check_constraint("status", UserReportStatus, "ck_user_reports_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reported_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[UserReportReason] = mapped_column(
        EnumStringType(UserReportReason), default=UserReportReason.other
    )
    status: Mapped[UserReportStatus] = mapped_column(
        EnumStringType(UserReportStatus), default=UserReportStatus.open
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )


class FlatmateProfileViewEvent(Base):
    __tablename__ = "flatmate_profile_view_events"
    __table_args__ = (
        Index("idx_flatmate_profile_views_viewer", "viewer_user_id", "created_at"),
        Index("idx_flatmate_profile_views_viewed", "viewed_user_id", "created_at"),
        Index("idx_flatmate_profile_views_property", "context_property_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    viewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    viewed_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    context_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(64), default="swipe_deck")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    scroll_depth_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppCatalog(Base):
    __tablename__ = "app_catalogs"
    __table_args__ = (
        Index("idx_app_catalogs_key", "key", unique=True),
        Index("idx_app_catalogs_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )


class MatchQnAAnswer(Base):
    __tablename__ = "match_qna_answers"
    __table_args__ = (
        Index("idx_match_qna_match", "match_id"),
        UniqueConstraint("match_id", "user_id", name="uq_match_qna_match_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("user_matches.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    q1: Mapped[str | None] = mapped_column(Text, nullable=True)
    q2: Mapped[str | None] = mapped_column(String(32), nullable=True)
    q3: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
