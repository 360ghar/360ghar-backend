from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, db_enum
from app.models.enums import (
    AppKey,
    BugSeverity,
    BugStatus,
    BugType,
    DevicePlatform,
    PageFormat,
)

if TYPE_CHECKING:
    from app.models.users import User


class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "mobile", "web", "api"
    bug_type: Mapped[BugType] = mapped_column(db_enum(BugType, "bug_type"), nullable=False)
    severity: Mapped[BugSeverity] = mapped_column(
        db_enum(BugSeverity, "bug_severity"), nullable=False
    )
    status: Mapped[BugStatus] = mapped_column(
        db_enum(BugStatus, "bug_status"),
        default=BugStatus.open,
        server_default=text("'open'"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Text] = mapped_column(Text, nullable=False)
    steps_to_reproduce: Mapped[Text | None] = mapped_column(Text, nullable=True)
    expected_behavior: Mapped[Text | None] = mapped_column(Text, nullable=True)
    actual_behavior: Mapped[Text | None] = mapped_column(Text, nullable=True)
    device_info: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # OS, version, model, etc.
    app_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    media_urls: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )  # Screenshots, videos
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    resolution: Mapped[Text | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])
    assignee: Mapped[User | None] = relationship("User", foreign_keys=[assigned_to])


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    unique_name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[Text] = mapped_column(Text, nullable=False)
    format: Mapped[PageFormat] = mapped_column(
        db_enum(PageFormat, "page_format"), default=PageFormat.html
    )
    custom_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # Additional config for clients
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    # Pages are private by default; toggle false to make them publicly accessible
    is_private: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    updater: Mapped[User | None] = relationship("User", foreign_keys=[updated_by])


class AppVersion(Base):
    __tablename__ = "app_versions"
    # Enum columns stored as text. The CHECKs match migration 20261014002003.
    __table_args__ = (
        CheckConstraint(
            "app IN (" + ", ".join(f"'{key.value}'" for key in AppKey) + ")",
            name="app_versions_app_check",
        ),
        CheckConstraint(
            "platform IN (" + ", ".join(f"'{p.value}'" for p in DevicePlatform) + ")",
            name="app_versions_platform_check",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # AppKey values: ghar, estate, flatmates, stays.
    app: Mapped[str] = mapped_column(String, nullable=False)
    # DevicePlatform values: ios, android, web.
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    build_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_notes: Mapped[Text | None] = mapped_column(Text, nullable=True)
    download_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    min_supported_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class FAQ(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # Category can be used for platform/app segmentation (e.g., 'ios', 'android', 'web', 'agent', 'user')
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    display_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
