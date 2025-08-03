from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, JSON
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class User(BaseModel):
    __tablename__ = "users"
    
    # Supabase Auth integration
    supabase_user_id = Column(String, unique=True, index=True, nullable=False)  # UUID from Supabase Auth
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, unique=True, index=True)
    full_name = Column(String)
    date_of_birth = Column(Date)
    profile_image_url = Column(String)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
        
    # User preferences for property recommendations
    preferences = Column(JSON)  # Store filters like property_type, budget_range, location_preference etc.
    
    # Location data for geo-based recommendations
    current_latitude = Column(String)  # Store as string to avoid precision issues
    current_longitude = Column(String)
    preferred_locations = Column(JSON)  # Array of preferred location IDs or names
    
    # Notification settings
    notification_settings = Column(JSON, default={
        "email_notifications": True,
        "push_notifications": True,
        "sms_notifications": False
    })
    
    # Privacy settings
    privacy_settings = Column(JSON, default={
        "profile_visibility": "public",
        "location_sharing": True
    })
    
    # Relationships
    swipes = relationship("UserSwipe", back_populates="user")
    favorites = relationship("UserFavorite", back_populates="user")
    search_history = relationship("UserSearchHistory", back_populates="user")
    visits = relationship("Visit", back_populates="user")
    bookings = relationship("Booking", back_populates="user")