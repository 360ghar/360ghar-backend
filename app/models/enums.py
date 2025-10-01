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

class BugType(str, Enum):
    ui_bug = "ui_bug"
    functionality_bug = "functionality_bug"
    performance_issue = "performance_issue"
    crash = "crash"
    feature_request = "feature_request"
    other = "other"

class BugSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

class BugStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"

class PageFormat(str, Enum):
    html = "html"
    markdown = "markdown"
    json = "json"

class ImageCategory(str, Enum):
    room = "room"
    hall = "hall"
    kitchen = "kitchen"
    bathroom = "bathroom"
    balcony = "balcony"
    terrace = "terrace"
    garden = "garden"
    parking = "parking"
    entrance = "entrance"
    exterior = "exterior"
    interior = "interior"
    others = "others"
