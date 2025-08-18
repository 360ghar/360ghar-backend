"""
Enum definitions for database models
"""
from enum import Enum

class PropertyType(str, Enum):
    house = "house"
    apartment = "apartment"
    builder_floor = "builder_floor"
    room = "room"

class PropertyPurpose(str, Enum):
    buy = "buy"
    rent = "rent"
    short_stay = "short_stay"

class PropertyStatus(str, Enum):
    available = "available"
    sold = "sold"
    rented = "rented"
    under_offer = "under_offer"
    maintenance = "maintenance"

class BookingStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    checked_in = "checked_in"
    checked_out = "checked_out"
    cancelled = "cancelled"
    completed = "completed"

class PaymentStatus(str, Enum):
    pending = "pending"
    partial = "partial"
    paid = "paid"
    refunded = "refunded"
    failed = "failed"

class VisitStatus(str, Enum):
    scheduled = "scheduled"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    rescheduled = "rescheduled"

class AgentType(str, Enum):
    general = "general"
    specialist = "specialist"
    senior = "senior"

class ExperienceLevel(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    expert = "expert"
