from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.enums import BugType, BugSeverity, BugStatus, PageFormat

# Bug Report Schemas
class BugReportCreate(BaseModel):
    source: str = Field(..., description="Source of the bug report (e.g., 'mobile', 'web', 'api')")
    bug_type: BugType = Field(..., description="Type of bug being reported")
    severity: BugSeverity = Field(..., description="Severity level of the bug")
    title: str = Field(..., min_length=1, max_length=200, description="Brief title of the bug")
    description: str = Field(..., min_length=1, description="Detailed description of the bug")
    steps_to_reproduce: Optional[str] = Field(None, description="Steps to reproduce the issue")
    expected_behavior: Optional[str] = Field(None, description="What should happen")
    actual_behavior: Optional[str] = Field(None, description="What actually happens")
    device_info: Optional[Dict[str, Any]] = Field(None, description="Device information (OS, version, model, etc.)")
    app_version: Optional[str] = Field(None, description="App version where bug was encountered")
    media_urls: Optional[List[str]] = Field(None, description="URLs to screenshots, videos, or other media")
    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the bug")

class BugReportUpdate(BaseModel):
    status: Optional[BugStatus] = Field(None, description="Update bug status")
    assigned_to: Optional[int] = Field(None, description="Assign bug to user ID")
    resolution: Optional[str] = Field(None, description="Resolution notes")
    tags: Optional[List[str]] = Field(None, description="Update tags")

class BugReportResponse(BaseModel):
    id: int
    user_id: Optional[int]
    source: str
    bug_type: BugType
    severity: BugSeverity
    status: BugStatus
    title: str
    description: str
    steps_to_reproduce: Optional[str]
    expected_behavior: Optional[str]
    actual_behavior: Optional[str]
    device_info: Optional[Dict[str, Any]]
    app_version: Optional[str]
    media_urls: Optional[List[str]]
    tags: Optional[List[str]]
    assigned_to: Optional[int]
    resolution: Optional[str]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

# Page Schemas
class PageCreate(BaseModel):
    unique_name: str = Field(..., min_length=1, max_length=100, description="Unique identifier for the page")
    title: str = Field(..., min_length=1, max_length=200, description="Page title")
    content: str = Field(..., description="Page content (HTML, Markdown, or JSON)")
    format: PageFormat = Field(default=PageFormat.html, description="Content format")
    custom_config: Optional[Dict[str, Any]] = Field(None, description="Custom configuration for clients")
    is_active: bool = Field(default=True, description="Whether the page is active")
    is_draft: bool = Field(default=False, description="Whether this is a draft version")
    is_private: bool = Field(default=True, description="Whether the page is private (not public)")

class PageUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="Page title")
    content: Optional[str] = Field(None, description="Page content")
    format: Optional[PageFormat] = Field(None, description="Content format")
    custom_config: Optional[Dict[str, Any]] = Field(None, description="Custom configuration")
    is_active: Optional[bool] = Field(None, description="Whether the page is active")
    is_draft: Optional[bool] = Field(None, description="Whether this is a draft version")
    is_private: Optional[bool] = Field(None, description="Whether the page is private (not public)")

class PageResponse(BaseModel):
    id: int
    unique_name: str
    title: str
    content: str
    format: PageFormat
    custom_config: Optional[Dict[str, Any]]
    is_active: bool
    is_draft: bool
    is_private: bool
    created_by: Optional[int]
    updated_by: Optional[int]
    view_count: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

class PagePublicResponse(BaseModel):
    """Response for public page access (without sensitive fields)"""
    unique_name: str
    title: str
    content: str
    format: PageFormat
    custom_config: Optional[Dict[str, Any]]
    view_count: int
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

# App Version Schemas
class AppVersionCreate(BaseModel):
    app: str = Field(..., description="App identifier (e.g., 'user', 'agent')")
    platform: str = Field(..., description="Platform (ios, android, web)")
    version: str = Field(..., description="Version string (e.g., '1.2.3')")
    build_number: Optional[int] = Field(None, description="Build number")
    release_notes: Optional[str] = Field(None, description="Release notes")
    download_url: Optional[str] = Field(None, description="Download URL for the app version")
    is_mandatory: bool = Field(default=False, description="Whether the version is mandatory")
    is_active: bool = Field(default=True, description="Whether this version is active")
    min_supported_version: Optional[str] = Field(None, description="Minimum supported version")

class AppVersionUpdate(BaseModel):
    release_notes: Optional[str] = Field(None, description="Release notes")
    download_url: Optional[str] = Field(None, description="Download URL")
    is_mandatory: Optional[bool] = Field(None, description="Whether the version is mandatory")
    is_active: Optional[bool] = Field(None, description="Whether this version is active")
    min_supported_version: Optional[str] = Field(None, description="Minimum supported version")

class AppVersionResponse(BaseModel):
    id: int
    app: str
    platform: str
    version: str
    build_number: Optional[int]
    release_notes: Optional[str]
    download_url: Optional[str]
    is_mandatory: bool
    is_active: bool
    min_supported_version: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

class AppVersionCheckRequest(BaseModel):
    app: str = Field(..., description="App identifier (e.g., 'user', 'agent')")
    platform: str = Field(..., description="Platform (ios, android, web)")
    current_version: str = Field(..., description="Current app version")
    build_number: Optional[int] = Field(None, description="Current build number")

class AppVersionCheckResponse(BaseModel):
    update_available: bool
    is_mandatory: bool = False
    latest_version: Optional[str] = None
    download_url: Optional[str] = None
    release_notes: Optional[str] = None
    min_supported_version: Optional[str] = None

# FAQ Schemas
class FAQCreate(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="FAQ question")
    answer: str = Field(..., min_length=1, description="FAQ answer")
    category: Optional[str] = Field(None, description="Category for filtering (e.g., platform, app segment)")
    tags: Optional[List[str]] = Field(None, description="Additional tags for filtering/search")
    display_order: Optional[int] = Field(default=None, description="Display order for sorting")
    is_active: bool = Field(True, description="Whether the FAQ is active")

class FAQUpdate(BaseModel):
    question: Optional[str] = Field(None, min_length=1, max_length=500)
    answer: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None

class FAQResponse(BaseModel):
    id: int
    question: str
    answer: str
    category: Optional[str]
    tags: Optional[List[str]]
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
