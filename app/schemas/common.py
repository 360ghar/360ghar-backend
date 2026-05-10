from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.utils import utc_now

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = 1
    limit: int = 20

    def get_offset(self) -> int:
        return (self.page - 1) * self.limit


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool


def make_paginated(items: list, total: int, page: int, limit: int) -> dict:
    """Build a paginated response dict with computed pagination metadata.

    Use this instead of hand-building pagination dicts in services.
    """
    total_pages = (total + limit - 1) // limit if limit else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }

class MessageResponse(BaseModel):
    message: str
    success: bool = True

class ErrorResponse(BaseModel):
    message: str
    error_code: str | None = None
    details: dict[str, Any] | None = None

class SearchParams(BaseModel):
    query: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: int = 5
    page: int = 1
    limit: int = 20

class AnalyticsData(BaseModel):
    user_id: int
    event_type: str
    event_data: dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)
    session_id: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None

class NotificationSettings(BaseModel):
    email_notifications: bool = True
    push_notifications: bool = True
    sms_notifications: bool = False
    visit_reminders: bool = True
    property_updates: bool = True
    promotional_emails: bool = False
    onboarding: bool = True
    digest: bool = True
    frequency: str | None = None
    quiet_hours: dict[str, str] | None = Field(default=None, alias="quietHours")
    categories: dict[str, bool] = Field(
        default_factory=lambda: {
            "promotions": True,
            "onboarding": True,
            "property_updates": True,
            "digest": True,
            "visit_reminders": True,
        }
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class PrivacySettings(BaseModel):
    profile_visibility: str = "public"  # public, private
    location_sharing: bool = True
    contact_sharing: bool = True
    search_history_tracking: bool = True


class AssignAgentPayload(BaseModel):
    """Payload for assigning an agent to a user."""
    agent_id: int
