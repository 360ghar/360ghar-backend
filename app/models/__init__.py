# Models package
# Import all models for easy access

from .users import User, UserSearchHistory, UserSwipe
from .agents import Agent, AgentInteraction
from .bookings import Booking
from .core import BugReport, Page, AppVersion, FAQ
from .properties import Property, PropertyImage, Amenity, PropertyAmenity, Visit
from .blogs import BlogCategory, BlogTag, BlogPost, BlogPostCategory, BlogPostTag
from .pm_documents import Document
from .pm_tenants import RentalApplicationForm, RentalApplication
from .pm_leases import Lease
from .pm_finance import RentCharge, RentPayment, Expense
from .pm_maintenance import MaintenanceRequest
from .pm_inspections import InspectionChecklist
from .tours import (
    Tour, Scene, Hotspot, TourAnalyticsEvent,
    AIJob, MediaFile, UserSession, TourLocation,
    SearchIndex, CacheEntry, FloorPlan, TourBranding,
    CustomDomain, VideoMetadata,
)
from .ai_conversations import AIConversation, AIConversationMessage
from .data_hub import (
    CircleRate, ReraProject, BankAuction, AuctionAlert, BankRate,
    JamabandiCache, ZoningData, ColonyApproval, GazetteNotification,
    ReraComplaint, CourtAuction, NeighbourhoodScore, ScraperRun,
)
from .enums import *

__all__ = [
    # Users
    "User",
    "UserSearchHistory",
    "UserSwipe",

    # Agents
    "Agent",
    "AgentInteraction",

    # Bookings
    "Booking",

    # Core
    "BugReport",
    "Page",
    "AppVersion",
    "FAQ",

    # Properties
    "Property",
    "PropertyImage",
    "Amenity",
    "PropertyAmenity",
    "Visit",

    # Blogs
    "BlogCategory",
    "BlogTag",
    "BlogPost",
    "BlogPostCategory",
    "BlogPostTag",

    # Property Management
    "Document",
    "RentalApplicationForm",
    "RentalApplication",
    "Lease",
    "RentCharge",
    "RentPayment",
    "Expense",
    "MaintenanceRequest",
    "InspectionChecklist",

    # 360 Virtual Tours
    "Tour",
    "Scene",
    "Hotspot",
    "TourAnalyticsEvent",
    "AIJob",
    "MediaFile",
    "UserSession",
    "TourLocation",
    "SearchIndex",
    "CacheEntry",
    "FloorPlan",
    "TourBranding",
    "CustomDomain",
    "VideoMetadata",

    # AI Conversations
    "AIConversation",
    "AIConversationMessage",

    # Data Hub
    "CircleRate",
    "ReraProject",
    "BankAuction",
    "AuctionAlert",
    "BankRate",
    "JamabandiCache",
    "ZoningData",
    "ColonyApproval",
    "GazetteNotification",
    "ReraComplaint",
    "CourtAuction",
    "NeighbourhoodScore",
    "ScraperRun",
]
