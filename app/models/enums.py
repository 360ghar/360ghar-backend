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

class UserRole(str, Enum):
    user = "user"
    agent = "agent"
    admin = "admin"


# --------------------
# Property Management
# --------------------

class ManagedPropertyStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class TenantStatus(str, Enum):
    applicant = "applicant"
    approved = "approved"
    active = "active"
    notice_period = "notice_period"
    vacated = "vacated"
    rejected = "rejected"


class LeaseStatus(str, Enum):
    draft = "draft"
    pending_signature = "pending_signature"
    active = "active"
    expiring_soon = "expiring_soon"
    expired = "expired"
    terminated = "terminated"
    renewed = "renewed"


class RentChargeStatus(str, Enum):
    pending = "pending"
    partial = "partial"
    paid = "paid"
    overdue = "overdue"
    waived = "waived"


class ExpenseCategory(str, Enum):
    maintenance = "maintenance"
    repairs = "repairs"
    insurance = "insurance"
    property_tax = "property_tax"
    hoa = "hoa"
    utilities = "utilities"
    marketing = "marketing"
    legal = "legal"
    other = "other"


class MaintenanceUrgency(str, Enum):
    emergency = "emergency"
    high = "high"
    medium = "medium"
    low = "low"


class MaintenanceCategory(str, Enum):
    plumbing = "plumbing"
    electrical = "electrical"
    hvac = "hvac"
    appliance = "appliance"
    structural = "structural"
    pest_control = "pest_control"
    cleaning = "cleaning"
    other = "other"


class MaintenanceRequestStatus(str, Enum):
    open = "open"
    in_review = "in_review"
    work_order_created = "work_order_created"
    resolved = "resolved"
    closed = "closed"


class WorkOrderStatus(str, Enum):
    created = "created"
    assigned = "assigned"
    in_progress = "in_progress"
    completed = "completed"
    closed = "closed"
    cancelled = "cancelled"


class DocumentType(str, Enum):
    lease_agreement = "lease_agreement"
    id_proof = "id_proof"
    address_proof = "address_proof"
    income_proof = "income_proof"
    inspection_report = "inspection_report"
    receipt = "receipt"
    invoice = "invoice"
    property_deed = "property_deed"
    insurance_policy = "insurance_policy"
    other = "other"


class InspectionType(str, Enum):
    move_in = "move_in"
    move_out = "move_out"
    routine = "routine"


class MessageThreadType(str, Enum):
    lease = "lease"
    maintenance = "maintenance"
    general = "general"


# --------------------
# 360 Virtual Tours
# --------------------

class TourStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class HotspotType(str, Enum):
    navigation = "navigation"
    info = "info"
    audio = "audio"
    video = "video"
    link = "link"
    custom = "custom"
