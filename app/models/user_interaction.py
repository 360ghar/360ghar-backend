from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.base import BaseModel

class UserSwipe(BaseModel):
    __tablename__ = "user_swipes"
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    is_liked = Column(Boolean, nullable=False)  # True for right swipe, False for left swipe
    swipe_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # Additional context
    user_location_lat = Column(String)  # User's location when swiped
    user_location_lng = Column(String)
    session_id = Column(String)  # Track swipe sessions
    
    # Relationships
    user = relationship("User", back_populates="swipes")
    property = relationship("Property", back_populates="swipes")

class UserFavorite(BaseModel):
    __tablename__ = "user_favorites"
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    is_favorite = Column(Boolean, default=True)
    notes = Column(Text)  # User's personal notes about the property
    
    # Relationships
    user = relationship("User", back_populates="favorites")
    property = relationship("Property", back_populates="favorites")

class UserSearchHistory(BaseModel):
    __tablename__ = "user_search_history"
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    search_query = Column(String)
    search_filters = Column(JSON)  # Store the complete filter object
    search_location = Column(String)  # Location searched
    search_radius = Column(Integer)  # Radius in km
    results_count = Column(Integer)  # Number of results returned
    
    # User's location during search
    user_location_lat = Column(String)
    user_location_lng = Column(String)
    
    # Search context
    search_type = Column(String)  # 'discover', 'explore', 'direct_search'
    session_id = Column(String)
    
    # Relationships
    user = relationship("User", back_populates="search_history")