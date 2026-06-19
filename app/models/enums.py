"""
Enum definitions for database models
"""

from enum import Enum


class PropertyType(str, Enum):
    house = "house"
    apartment = "apartment"
    builder_floor = "builder_floor"
    room = "room"
    villa = "villa"
    plot = "plot"
    condo = "condo"
    penthouse = "penthouse"
    studio = "studio"
    loft = "loft"
    pg = "pg"
    flatmate = "flatmate"
    office = "office"
    shop = "shop"
    warehouse = "warehouse"


PG_FLATMATE_TYPES = {PropertyType.pg, PropertyType.flatmate}


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


class ListingGenderPreference(str, Enum):
    any = "any"
    male = "male"
    female = "female"


class ListingSharingType(str, Enum):
    private_room = "private_room"
    shared_room = "shared_room"
    master_bedroom = "master_bedroom"
    entire_flat = "entire_flat"


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
    scheduled = "requested"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    rescheduled = "reschedule_suggested"


class FlatmatesMode(str, Enum):
    room_poster = "room_poster"
    seeker = "seeker"
    co_hunter = "co_hunter"
    open_to_both = "open_to_both"


class FlatmatesProfileStatus(str, Enum):
    draft = "draft"
    pending_review = "pending_review"
    active = "active"
    paused = "paused"
    rejected = "rejected"


class SleepSchedule(str, Enum):
    early_bird = "early_bird"
    flexible = "flexible"
    night_owl = "night_owl"


class Cleanliness(str, Enum):
    minimal = "minimal"
    tidy = "tidy"
    spotless = "spotless"


class FoodHabits(str, Enum):
    vegetarian = "vegetarian"
    vegan = "vegan"
    non_vegetarian = "non_vegetarian"
    eggetarian = "eggetarian"
    no_preference = "no_preference"


class SmokingDrinking(str, Enum):
    neither = "neither"
    smoke_outside = "smoke_outside"
    drink_occasionally = "drink_occasionally"
    both_fine = "both_fine"


class GuestsPolicy(str, Enum):
    no_overnight_guests = "no_overnight_guests"
    occasional_ok = "occasional_ok"
    open_house = "open_house"


class WorkStyle(str, Enum):
    wfh = "wfh"
    office = "office"
    hybrid = "hybrid"


class SwipeTargetType(str, Enum):
    property = "property"
    user = "user"


class SwipeAction(str, Enum):
    pass_ = "pass"
    like = "like"
    super_like = "super_like"


class VisitContext(str, Enum):
    property_tour = "property_tour"
    flatmate_meet = "flatmate_meet"


class ConversationSource(str, Enum):
    listing_interest = "listing_interest"
    profile_match = "profile_match"


class ConversationStatus(str, Enum):
    active = "active"
    archived = "archived"
    blocked = "blocked"
    closed = "closed"


class UserMatchStatus(str, Enum):
    active = "active"
    unmatched = "unmatched"
    blocked = "blocked"


class MessageType(str, Enum):
    text = "text"
    image = "image"
    system = "system"
    visit_request = "visit_request"


class UserReportReason(str, Enum):
    spam = "spam"
    fake_profile = "fake_profile"
    abuse = "abuse"
    inappropriate = "inappropriate"
    other = "other"


class UserReportStatus(str, Enum):
    open = "open"
    reviewed = "reviewed"
    dismissed = "dismissed"
    actioned = "actioned"


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
    floor_plan = "floor_plan"


class UserRole(str, Enum):
    user = "user"
    agent = "agent"
    admin = "admin"


class AuthMethod(str, Enum):
    """Last authentication method used by a user.

    Mirrors the client-side login state-machine. Stored as a TEXT column with a
    DB-level CHECK constraint (see migration 20260606000000); not a PG enum.
    """

    google = "google"
    apple = "apple"
    email_password = "email_password"
    phone_password = "phone_password"
    phone_otp = "phone_otp"
    email_otp = "email_otp"


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


class PaymentMethod(str, Enum):
    cash = "cash"
    bank_transfer = "bank_transfer"
    upi = "upi"
    cheque = "cheque"
    online = "online"
    other = "other"


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


# --------------------
# 360 Virtual Tours
# --------------------


class TourStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class TourVisibility(str, Enum):
    """Tour visibility controls access permissions.

    - private: Only the owner can view the tour (requires authentication)
    - unlisted: Anyone with the link can view, but not indexed in public listings
    - public: Visible in public listings and searchable
    """

    private = "private"
    unlisted = "unlisted"
    public = "public"


class HotspotType(str, Enum):
    navigation = "navigation"
    info = "info"
    audio = "audio"
    video = "video"
    link = "link"
    custom = "custom"


# --------------------
# Data Hub
# --------------------


class ScraperStatus(str, Enum):
    running = "running"
    success = "success"
    partial = "partial"
    failed = "failed"


class AuctionSource(str, Enum):
    # Original
    sarfaesi = "sarfaesi"
    ibapi = "ibapi"
    mstc = "mstc"
    drt = "drt"
    ecourts = "ecourts"
    # Central / Quasi-Govt
    ibbi = "ibbi"
    baanknet = "baanknet"
    # Delhi
    dda = "dda"
    dfc_delhi = "dfc_delhi"
    # Gurugram / Haryana
    hsvp = "hsvp"
    hsvp_procure247 = "hsvp_procure247"
    dtcp = "dtcp"
    # Meerut / UP
    mda = "mda"
    yeida = "yeida"
    # Aggregators
    bank_eauctions = "bank_eauctions"
    eauctions_india = "eauctions_india"
    auction_bazaar = "auction_bazaar"
    eauction_dekho = "eauction_dekho"
    findauction = "findauction"
    findauction_prop = "findauction_prop"
    auction_tiger = "auction_tiger"
    # Individual Banks
    sbi = "sbi"
    pnb = "pnb"
    bob = "bob"
    canara = "canara"
    hdfc = "hdfc"
    icici = "icici"
    union = "union"
    yes_bank = "yes_bank"


class GazetteType(str, Enum):
    land_acquisition = "land_acquisition"
    rate_revision = "rate_revision"
    policy = "policy"
    clu_change = "clu_change"


class ComplaintNature(str, Enum):
    delay = "delay"
    quality = "quality"
    refund = "refund"
    compensation = "compensation"
    other = "other"


# --------------------
# Tour AI Jobs
# --------------------


class AIJobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AIJobType(str, Enum):
    scene_analysis = "scene_analysis"
    hotspot_generation = "hotspot_generation"
    floor_plan_processing = "floor_plan_processing"


class CustomDomainVerificationStatus(str, Enum):
    pending = "pending"
    verified = "verified"
    failed = "failed"


class CustomDomainSSLStatus(str, Enum):
    none = "none"
    pending = "pending"
    active = "active"
    failed = "failed"


class AgentInteractionType(str, Enum):
    chat = "chat"
    call = "call"
    email = "email"


# --------------------
# Flatmates Moderation
# --------------------


class ListingModerationStatus(str, Enum):
    """Status values stored in listing_preferences JSON for flatmate listings."""
    pending_review = "pending_review"
    live = "live"
    rejected = "rejected"


class ModerationAction(str, Enum):
    """Actions available when moderating a flatmate listing."""
    approve = "approve"
    reject = "reject"
    request_edit = "request_edit"


class ReportAction(str, Enum):
    """Actions available when moderating a user report."""
    dismiss = "dismiss"
    warn_user = "warn_user"
    suspend_user = "suspend_user"
    escalate = "escalate"


# --------------------
# Blog
# --------------------


class BlogPostStatus(str, Enum):
    """Lifecycle status for a blog post.

    - draft: not visible publicly (work in progress)
    - published: visible publicly
    - archived: hidden from public listings but retained
    - scheduled: will be auto-published at ``scheduled_at``
    """

    draft = "draft"
    published = "published"
    archived = "archived"
    scheduled = "scheduled"
