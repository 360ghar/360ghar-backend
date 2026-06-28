from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BugSeverity, BugStatus, BugType, PageFormat


# Bug Report Schemas
class BugReportCreate(BaseModel):
    source: str = Field(..., description="Source of the bug report (e.g., 'mobile', 'web', 'api')")
    bug_type: BugType = Field(..., description="Type of bug being reported")
    severity: BugSeverity = Field(..., description="Severity level of the bug")
    title: str = Field(..., min_length=1, max_length=200, description="Brief title of the bug")
    description: str = Field(..., min_length=1, description="Detailed description of the bug")
    steps_to_reproduce: str | None = Field(None, description="Steps to reproduce the issue")
    expected_behavior: str | None = Field(None, description="What should happen")
    actual_behavior: str | None = Field(None, description="What actually happens")
    device_info: dict[str, Any] | None = Field(None, description="Device information (OS, version, model, etc.)")
    app_version: str | None = Field(None, description="App version where bug was encountered")
    media_urls: list[str] | None = Field(None, description="URLs to screenshots, videos, or other media")
    tags: list[str] | None = Field(None, description="Tags for categorizing the bug")

class BugReportUpdate(BaseModel):
    status: BugStatus | None = Field(None, description="Update bug status")
    assigned_to: int | None = Field(None, description="Assign bug to user ID")
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
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

# Page Schemas
class PageCreate(BaseModel):
    unique_name: str = Field(..., min_length=1, max_length=100, description="Unique identifier for the page")
    title: str = Field(..., min_length=1, max_length=200, description="Page title")
    content: str = Field(..., description="Page content (HTML, Markdown, or JSON)")
    format: PageFormat = Field(default=PageFormat.html, description="Content format")
    custom_config: dict[str, Any] | None = Field(None, description="Custom configuration for clients")
    is_active: bool = Field(default=True, description="Whether the page is active")
    is_draft: bool = Field(default=False, description="Whether this is a draft version")
    is_private: bool = Field(default=True, description="Whether the page is private (not public)")

class PageUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200, description="Page title")
    content: str | None = Field(None, description="Page content")
    format: PageFormat | None = Field(None, description="Content format")
    custom_config: dict[str, Any] | None = Field(None, description="Custom configuration")
    is_active: bool | None = Field(None, description="Whether the page is active")
    is_draft: bool | None = Field(None, description="Whether this is a draft version")
    is_private: bool | None = Field(None, description="Whether the page is private (not public)")

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
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

class PagePublicResponse(BaseModel):
    """Response for public page access (without sensitive fields)"""
    unique_name: str
    title: str
    content: str
    format: PageFormat
    custom_config: dict[str, Any] | None
    view_count: int
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

# App Version Schemas
class AppVersionCreate(BaseModel):
    app: str = Field(..., description="App identifier (e.g., 'user', 'agent')")
    platform: str = Field(..., description="Platform (ios, android, web)")
    version: str = Field(..., description="Version string (e.g., '1.2.3')")
    build_number: int | None = Field(None, description="Build number")
    release_notes: str | None = Field(None, description="Release notes")
    download_url: str | None = Field(None, description="Download URL for the app version")
    is_mandatory: bool = Field(default=False, description="Whether the version is mandatory")
    is_active: bool = Field(default=True, description="Whether this version is active")
    min_supported_version: str | None = Field(None, description="Minimum supported version")

class AppVersionUpdate(BaseModel):
    release_notes: str | None = Field(None, description="Release notes")
    download_url: str | None = Field(None, description="Download URL")
    is_mandatory: bool | None = Field(None, description="Whether the version is mandatory")
    is_active: bool | None = Field(None, description="Whether this version is active")
    min_supported_version: str | None = Field(None, description="Minimum supported version")

class AppVersionResponse(BaseModel):
    id: int
    app: str
    platform: str
    version: str
    build_number: int | None
    release_notes: str | None
    download_url: str | None
    is_mandatory: bool
    is_active: bool
    min_supported_version: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

class AppVersionCheckRequest(BaseModel):
    app: str = Field(..., description="App identifier (e.g., 'user', 'agent')")
    platform: str = Field(..., description="Platform (ios, android, web)")
    current_version: str = Field(..., description="Current app version")
    build_number: int | None = Field(None, description="Current build number")

class AppVersionCheckResponse(BaseModel):
    update_available: bool
    is_mandatory: bool = False
    latest_version: str | None = None
    download_url: str | None = None
    release_notes: str | None = None
    min_supported_version: str | None = None

# FAQ Schemas
class FAQCreate(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="FAQ question")
    answer: str = Field(..., min_length=1, description="FAQ answer")
    category: str | None = Field(None, description="Category for filtering (e.g., platform, app segment)")
    tags: list[str] | None = Field(None, description="Additional tags for filtering/search")
    display_order: int | None = Field(default=None, description="Display order for sorting")
    is_active: bool = Field(True, description="Whether the FAQ is active")

class FAQUpdate(BaseModel):
    question: str | None = Field(None, min_length=1, max_length=500)
    answer: str | None = Field(None, min_length=1)
    category: str | None = None
    tags: list[str] | None = None
    display_order: int | None = None
    is_active: bool | None = None

class FAQResponse(BaseModel):
    id: int
    question: str
    answer: str
    category: str | None
    tags: list[str] | None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
