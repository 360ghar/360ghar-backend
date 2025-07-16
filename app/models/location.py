from sqlalchemy import Column, Integer, String, Text, Float
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class Location(BaseModel):
    __tablename__ = "locations"
    
    name = Column(String, nullable=False, index=True)
    city = Column(String, nullable=False, index=True)
    state = Column(String, nullable=False)
    country = Column(String, nullable=False, default="India")
    pincode = Column(String, index=True)
    
    # Simple coordinate storage (we can upgrade to PostGIS later)
    latitude = Column(Float)
    longitude = Column(Float)
    
    # Address components
    locality = Column(String)  # Sector, Colony, etc.
    sub_locality = Column(String)  # Sub-area
    landmark = Column(String)
    full_address = Column(Text)
    
    # Additional metadata
    area_type = Column(String)  # residential, commercial, mixed
    development_status = Column(String)  # developed, under_development, planned
    
    # Relationships
    properties = relationship("Property", back_populates="location")