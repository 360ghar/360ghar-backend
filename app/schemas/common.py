from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class PaginationParams(BaseModel):
    page: int = 1
    limit: int = 20
    
    def get_offset(self) -> int:
        return (self.page - 1) * self.limit

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool

class MessageResponse(BaseModel):
    message: str
    success: bool = True

class ErrorResponse(BaseModel):
    message: str
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class SearchParams(BaseModel):
    query: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: int = 5
    page: int = 1
    limit: int = 20

class AnalyticsData(BaseModel):
    user_id: int
    event_type: str
    event_data: Dict[str, Any]
    timestamp: datetime = datetime.utcnow()
    session_id: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None

class NotificationSettings(BaseModel):
    email_notifications: bool = True
    push_notifications: bool = True
    sms_notifications: bool = False
    visit_reminders: bool = True
    property_updates: bool = True
    promotional_emails: bool = False

class PrivacySettings(BaseModel):
    profile_visibility: str = "public"  # public, private
    location_sharing: bool = True
    contact_sharing: bool = True
    search_history_tracking: bool = True