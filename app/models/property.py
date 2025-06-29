from sqlalchemy import Column, Integer, String, Text, Boolean, Float, JSON, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
import enum

class PropertyType(str, enum.Enum):
    HOUSE = "house"
    APARTMENT = "apartment"
    BUILDER_FLOOR = "builder_floor"
    ROOM = "room"

class PropertyPurpose(str, enum.Enum):
    BUY = "buy"
    RENT = "rent"
    SHORT_STAY = "short_stay"

class PropertyStatus(str, enum.Enum):
    AVAILABLE = "available"
    SOLD = "sold"
    RENTED = "rented"
    UNDER_OFFER = "under_offer"
    MAINTENANCE = "maintenance"

class Property(BaseModel):
    __tablename__ = "properties"
    
    title = Column(String, nullable=False)
    description = Column(Text)
    property_type = Column(Enum(PropertyType), nullable=False)
    purpose = Column(Enum(PropertyPurpose), nullable=False)
    status = Column(Enum(PropertyStatus), default=PropertyStatus.AVAILABLE)
    
    # Location reference
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    
    # Pricing
    base_price = Column(Float, nullable=False)  # Main price
    price_per_sqft = Column(Float)  # For buy properties
    monthly_rent = Column(Float)  # For rent properties
    daily_rate = Column(Float)  # For short stay properties
    security_deposit = Column(Float)
    maintenance_charges = Column(Float)
    
    # Property details
    area_sqft = Column(Float)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    balconies = Column(Integer)
    parking_spaces = Column(Integer)
    floor_number = Column(Integer)
    total_floors = Column(Integer)
    age_of_property = Column(Integer)  # in years
    
    # For short stay properties
    max_occupancy = Column(Integer)
    minimum_stay_days = Column(Integer, default=1)
    
    # Amenities and features
    amenities = Column(JSON)  # Array of amenity names
    features = Column(JSON)  # Additional features
    
    # Media
    main_image_url = Column(String)
    virtual_tour_url = Column(String)  # 360 tour URL
    
    # Availability and booking
    is_available = Column(Boolean, default=True)
    available_from = Column(String)  # Date string
    calendar_data = Column(JSON)  # For short stay availability calendar
    
    # SEO and search
    tags = Column(JSON)  # Search tags
    search_keywords = Column(Text)
    
    # Owner/Builder information
    owner_name = Column(String)
    owner_contact = Column(String)
    builder_name = Column(String)
    
    # Performance metrics
    view_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    interest_count = Column(Integer, default=0)
    
    # Relationships
    location = relationship("Location", back_populates="properties")
    images = relationship("PropertyImage", back_populates="property", cascade="all, delete-orphan")
    swipes = relationship("UserSwipe", back_populates="property")
    favorites = relationship("UserFavorite", back_populates="property")
    visits = relationship("Visit", back_populates="property")
    bookings = relationship("Booking", back_populates="property")

class PropertyImage(BaseModel):
    __tablename__ = "property_images"
    
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    image_url = Column(String, nullable=False)
    caption = Column(String)
    display_order = Column(Integer, default=0)
    is_main_image = Column(Boolean, default=False)
    
    # Relationships
    property = relationship("Property", back_populates="images")