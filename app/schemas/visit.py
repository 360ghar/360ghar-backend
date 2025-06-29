from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.visit import VisitStatus

class RelationshipManagerBase(BaseModel):
    name: str
    email: EmailStr
    phone: str
    whatsapp_number: Optional[str] = None
    profile_image_url: Optional[str] = None
    bio: Optional[str] = None

class RelationshipManagerCreate(RelationshipManagerBase):
    employee_id: str
    department: str = "Customer Relations"
    experience_years: Optional[int] = None
    working_hours: Optional[str] = None

class RelationshipManager(RelationshipManagerBase):
    id: int
    employee_id: str
    department: str
    experience_years: Optional[int] = None
    is_active: bool
    working_hours: Optional[str] = None
    total_visits_handled: int
    customer_rating: Optional[str] = None
    
    class Config:
        from_attributes = True

class VisitBase(BaseModel):
    property_id: int
    scheduled_date: datetime
    visitor_name: str
    visitor_phone: str
    visitor_email: Optional[EmailStr] = None
    number_of_visitors: int = 1
    preferred_time_slot: Optional[str] = None
    special_requirements: Optional[str] = None

class VisitCreate(VisitBase):
    pass

class VisitUpdate(BaseModel):
    scheduled_date: Optional[datetime] = None
    status: Optional[VisitStatus] = None
    visitor_name: Optional[str] = None
    visitor_phone: Optional[str] = None
    visitor_email: Optional[EmailStr] = None
    number_of_visitors: Optional[int] = None
    preferred_time_slot: Optional[str] = None
    special_requirements: Optional[str] = None
    visit_notes: Optional[str] = None
    visitor_feedback: Optional[str] = None
    interest_level: Optional[str] = None
    follow_up_required: Optional[bool] = None
    follow_up_date: Optional[datetime] = None

class VisitReschedule(BaseModel):
    visit_id: int
    new_date: datetime
    reason: Optional[str] = None

class VisitCancel(BaseModel):
    visit_id: int
    reason: str

class Visit(VisitBase):
    id: int
    user_id: int
    relationship_manager_id: Optional[int] = None
    actual_date: Optional[datetime] = None
    status: VisitStatus
    visit_notes: Optional[str] = None
    visitor_feedback: Optional[str] = None
    interest_level: Optional[str] = None
    follow_up_required: bool
    follow_up_date: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    rescheduled_from: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    # Relationships
    relationship_manager: Optional[RelationshipManager] = None
    
    class Config:
        from_attributes = True

class VisitList(BaseModel):
    visits: list[Visit]
    total: int
    upcoming: int
    completed: int
    cancelled: int