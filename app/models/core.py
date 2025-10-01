
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum
from typing import Optional, List
from datetime import datetime
from app.core.database import Base
from app.models.enums import BugType, BugSeverity, BugStatus, PageFormat

class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # e.g., "mobile", "web", "api"
    bug_type: Mapped[BugType] = mapped_column(SQLEnum(BugType, name='bug_type'), nullable=False)
    severity: Mapped[BugSeverity] = mapped_column(SQLEnum(BugSeverity, name='bug_severity'), nullable=False)
    status: Mapped[BugStatus] = mapped_column(SQLEnum(BugStatus, name='bug_status'), default=BugStatus.open)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Text] = mapped_column(Text, nullable=False)
    steps_to_reproduce: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)
    expected_behavior: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)
    actual_behavior: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)
    device_info: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # OS, version, model, etc.
    app_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    media_urls: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)  # Screenshots, videos
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    assigned_to: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    assignee: Mapped[Optional["User"]] = relationship("User", foreign_keys=[assigned_to])

class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    unique_name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[Text] = mapped_column(Text, nullable=False)
    format: Mapped[PageFormat] = mapped_column(SQLEnum(PageFormat, name='page_format'), default=PageFormat.html)
    custom_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Additional config for clients
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    # Pages are private by default; toggle false to make them publicly accessible
    is_private: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationships
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    updater: Mapped[Optional["User"]] = relationship("User", foreign_keys=[updated_by])

class AppVersion(Base):
    __tablename__ = "app_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    app: Mapped[str] = mapped_column(String, nullable=False)  # app identifier (e.g., user, agent)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # ios, android, web
    version: Mapped[str] = mapped_column(String, nullable=False)
    build_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    release_notes: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)
    download_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    min_supported_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

class FAQ(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(String, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # Category can be used for platform/app segmentation (e.g., 'ios', 'android', 'web', 'agent', 'user')
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now(), nullable=True)
