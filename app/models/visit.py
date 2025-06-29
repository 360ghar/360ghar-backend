from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean, Enum
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
import enum

class VisitStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"

class RelationshipManager(BaseModel):
    __tablename__ = "relationship_managers"
    
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=False)
    whatsapp_number = Column(String)
    profile_image_url = Column(String)
    bio = Column(Text)
    
    # Work details
    employee_id = Column(String, unique=True)
    department = Column(String, default="Customer Relations")
    experience_years = Column(Integer)
    
    # Availability
    is_active = Column(Boolean, default=True)
    working_hours = Column(String)  # JSON string of working hours
    
    # Performance metrics
    total_visits_handled = Column(Integer, default=0)
    customer_rating = Column(String)  # Average rating from customers
    
    # Relationships
    visits = relationship("Visit", back_populates="relationship_manager")

class Visit(BaseModel):
    __tablename__ = "visits"
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    relationship_manager_id = Column(Integer, ForeignKey("relationship_managers.id"))
    
    # Visit details
    scheduled_date = Column(DateTime, nullable=False)
    actual_date = Column(DateTime)  # When visit actually happened
    status = Column(Enum(VisitStatus), default=VisitStatus.SCHEDULED)
    
    # Contact information
    visitor_name = Column(String, nullable=False)
    visitor_phone = Column(String, nullable=False)
    visitor_email = Column(String)
    number_of_visitors = Column(Integer, default=1)
    
    # Visit preferences
    preferred_time_slot = Column(String)  # morning, afternoon, evening
    special_requirements = Column(Text)
    
    # Visit outcome
    visit_notes = Column(Text)  # RM's notes about the visit
    visitor_feedback = Column(Text)  # Visitor's feedback
    interest_level = Column(String)  # high, medium, low
    follow_up_required = Column(Boolean, default=False)
    follow_up_date = Column(DateTime)
    
    # Cancellation/Rescheduling
    cancellation_reason = Column(Text)
    rescheduled_from = Column(DateTime)  # Original date if rescheduled
    
    # Relationships
    user = relationship("User", back_populates="visits")
    property = relationship("Property", back_populates="visits")
    relationship_manager = relationship("RelationshipManager", back_populates="visits")