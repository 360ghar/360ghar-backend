from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.models.enums import AppKey, BugSeverity, BugStatus, BugType, DevicePlatform, PageFormat
from app.schemas.base import NotNullable, PatchModel, UtcDateTime, WriteModel


def _lower_platform(value: Any) -> Any:
    """Platforms are lowercase on the wire. Accept any case, then match the enum."""
    return value.strip().lower() if isinstance(value, str) else value


# Lengths follow the VARCHAR limits in supabase/migrations/20260621000001_core_identity.sql.
AppPlatform = Annotated[DevicePlatform, BeforeValidator(_lower_platform)]


# Bug Report Schemas
class BugReportCreate(WriteModel):
    source: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Source of the bug report (e.g., 'mobile', 'web', 'api')",
    )
    bug_type: BugType = Field(..., description="Type of bug being reported")
    severity: BugSeverity = Field(..., description="Severity level of the bug")
    title: str = Field(..., min_length=1, max_length=200, description="Brief title of the bug")
    description: str = Field(..., min_length=1, description="Detailed description of the bug")
    steps_to_reproduce: str | None = Field(None, description="Steps to reproduce the issue")
    expected_behavior: str | None = Field(None, description="What should happen")
    actual_behavior: str | None = Field(None, description="What actually happens")
    device_info: dict[str, Any] | None = Field(
        None, description="Device information (OS, version, model, etc.)"
    )
    app_version: str | None = Field(
        None, max_length=50, description="App version where bug was encountered"
    )
    media_urls: list[str] | None = Field(
        None, description="URLs to screenshots, videos, or other media"
    )
    tags: list[str] | None = Field(None, description="Tags for categorizing the bug")


class BugReportUpdate(PatchModel):
    status: Annotated[BugStatus | None, NotNullable] = Field(None, description="Update bug status")
    assigned_to: int | None = Field(
        None, description="Assign bug to a user ID with the admin or agent role"
    )
    resolution: str | None = Field(None, description="Resolution notes")
    tags: list[str] | None = Field(None, description="Update tags")


class BugReportResponse(BaseModel):
    id: int
    user_id: int | None
    source: str
    bug_type: BugType
    severity: BugSeverity
    status: BugStatus
    title: str
    description: str
    steps_to_reproduce: str | None
    expected_behavior: str | None
    actual_behavior: str | None
    device_info: dict[str, Any] | None
    app_version: str | None
    media_urls: list[str] | None
    tags: list[str] | None
    assigned_to: int | None
    resolution: str | None
    resolved_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None

    model_config = ConfigDict(from_attributes=True)


# Page Schemas
class PageCreate(WriteModel):
    unique_name: str = Field(
        ..., min_length=1, max_length=100, description="Unique identifier for the page"
    )
    title: str = Field(..., min_length=1, max_length=200, description="Page title")
    content: str = Field(..., description="Page content (HTML, Markdown, or JSON)")
    format: PageFormat = Field(default=PageFormat.html, description="Content format")
    custom_config: dict[str, Any] | None = Field(
        None, description="Custom configuration for clients"
    )
    is_active: bool = Field(default=True, description="Whether the page is active")
    is_draft: bool = Field(default=False, description="Whether this is a draft version")
    is_private: bool = Field(default=True, description="Whether the page is private (not public)")


class PageUpdate(PatchModel):
    title: Annotated[str | None, NotNullable] = Field(
        None, min_length=1, max_length=200, description="Page title"
    )
    content: Annotated[str | None, NotNullable] = Field(None, description="Page content")
    format: Annotated[PageFormat | None, NotNullable] = Field(None, description="Content format")
    custom_config: dict[str, Any] | None = Field(
        None, description="Custom configuration. Null clears it."
    )
    is_active: Annotated[bool | None, NotNullable] = Field(
        None, description="Whether the page is active"
    )
    is_draft: Annotated[bool | None, NotNullable] = Field(
        None, description="Whether this is a draft version"
    )
    is_private: Annotated[bool | None, NotNullable] = Field(
        None, description="Whether the page is private (not public)"
    )


class PageResponse(BaseModel):
    id: int
    unique_name: str
    title: str
    content: str
    format: PageFormat
    custom_config: dict[str, Any] | None
    is_active: bool
    is_draft: bool
    is_private: bool
    created_by: int | None
    updated_by: int | None
    view_count: int
    created_at: UtcDateTime
    updated_at: UtcDateTime | None

    model_config = ConfigDict(from_attributes=True)


class PagePublicResponse(BaseModel):
    """Response for public page access (without sensitive fields)"""

    unique_name: str
    title: str
    content: str
    format: PageFormat
    custom_config: dict[str, Any] | None
    view_count: int
    updated_at: UtcDateTime | None

    model_config = ConfigDict(from_attributes=True)


# App Version Schemas
class AppVersionCreate(WriteModel):
    app: AppKey = Field(..., description="App identifier: ghar, estate, flatmates or stays")
    platform: AppPlatform = Field(..., description="Platform (ios, android, web)")
    version: str = Field(
        ..., min_length=1, max_length=20, description="Version string (e.g., '1.2.3')"
    )
    build_number: int | None = Field(None, description="Build number")
    release_notes: str | None = Field(None, description="Release notes")
    download_url: str | None = Field(
        None, max_length=500, description="Download URL for the app version"
    )
    is_mandatory: bool = Field(default=False, description="Whether the version is mandatory")
    is_active: bool = Field(default=True, description="Whether this version is active")
    min_supported_version: str | None = Field(
        None, max_length=20, description="Minimum supported version"
    )


class AppVersionUpdate(PatchModel):
    app: Annotated[AppKey | None, NotNullable] = Field(
        None, description="App identifier: ghar, estate, flatmates or stays"
    )
    platform: Annotated[AppPlatform | None, NotNullable] = Field(
        None, description="Platform (ios, android, web)"
    )
    version: Annotated[str | None, NotNullable] = Field(
        None, min_length=1, max_length=20, description="Version string"
    )
    build_number: int | None = Field(None, description="Build number")
    release_notes: str | None = Field(None, description="Release notes")
    download_url: str | None = Field(None, max_length=500, description="Download URL")
    is_mandatory: Annotated[bool | None, NotNullable] = Field(
        None, description="Whether the version is mandatory"
    )
    is_active: Annotated[bool | None, NotNullable] = Field(
        None, description="Whether this version is active"
    )
    min_supported_version: str | None = Field(
        None, max_length=20, description="Minimum supported version"
    )


class AppVersionResponse(BaseModel):
    id: int
    app: AppKey
    platform: AppPlatform
    version: str
    build_number: int | None
    release_notes: str | None
    download_url: str | None
    is_mandatory: bool
    is_active: bool
    min_supported_version: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None

    model_config = ConfigDict(from_attributes=True)


class AppVersionCheckRequest(WriteModel):
    app: AppKey = Field(..., description="App identifier: ghar, estate, flatmates or stays")
    platform: AppPlatform = Field(..., description="Platform (ios, android, web)")
    current_version: str = Field(
        ..., min_length=1, max_length=20, description="Current app version"
    )
    build_number: int | None = Field(None, description="Current build number")


class AppVersionCheckResponse(BaseModel):
    update_available: bool
    is_mandatory: bool = False
    latest_version: str | None = None
    download_url: str | None = None
    release_notes: str | None = None
    min_supported_version: str | None = None


# FAQ Schemas
class FAQCreate(WriteModel):
    question: str = Field(..., min_length=1, max_length=500, description="FAQ question")
    answer: str = Field(..., min_length=1, description="FAQ answer")
    category: str | None = Field(
        None, max_length=100, description="Category for filtering (e.g., platform, app segment)"
    )
    tags: list[str] | None = Field(None, description="Additional tags for filtering/search")
    display_order: int = Field(default=0, description="Display order for sorting")
    is_active: bool = Field(True, description="Whether the FAQ is active")


class FAQUpdate(PatchModel):
    question: Annotated[str | None, NotNullable] = Field(None, min_length=1, max_length=500)
    answer: Annotated[str | None, NotNullable] = Field(None, min_length=1)
    category: str | None = Field(None, max_length=100)
    tags: list[str] | None = None
    display_order: Annotated[int | None, NotNullable] = None
    is_active: Annotated[bool | None, NotNullable] = None


class FAQResponse(BaseModel):
    id: int
    question: str
    answer: str
    category: str | None
    tags: list[str] | None
    display_order: int
    is_active: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime | None

    model_config = ConfigDict(from_attributes=True)
