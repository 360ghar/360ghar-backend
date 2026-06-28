from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.utils import utc_now


class MessageResponse(BaseModel):
    message: str
    success: bool = True

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
