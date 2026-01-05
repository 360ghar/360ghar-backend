# Models package
# Import all models for easy access

from .users import User, UserSearchHistory, UserSwipe
from .agents import Agent
from .bookings import Booking
from .core import BugReport, Page, AppVersion, FAQ
from .properties import Property, PropertyImage, Amenity, PropertyAmenity, Visit
from .pm_documents import Document
from .pm_tenants import RentalApplicationForm, RentalApplication
from .pm_leases import Lease
from .pm_finance import RentCharge, RentPayment, Expense
from .pm_maintenance import MaintenanceRequest
from .pm_inspections import InspectionChecklist
from .tours import Tour, Scene, Hotspot, TourAnalyticsEvent
from .enums import *

__all__ = [
    # Users
    "User",
    "UserSearchHistory",
    "UserSwipe",

    # Agents
    "Agent",

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
]
