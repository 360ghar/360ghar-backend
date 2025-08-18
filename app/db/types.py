"""
Legacy type definitions - DEPRECATED

All enum types have been moved to app.models.enums
All TypedDict definitions have been replaced by SQLAlchemy ORM models in app.models.models

This file is kept for backwards compatibility but will be removed in future versions.
Please use:
- app.models.enums for enum types
- app.models.models for ORM models
"""

# Re-export enums for backwards compatibility
from app.models.enums import *

# Legacy imports - use app.models.enums instead
from app.models.enums import (
    PropertyType,
    PropertyPurpose, 
    PropertyStatus,
    BookingStatus,
    PaymentStatus,
    VisitStatus,
    AgentType,
    ExperienceLevel,
)

__all__ = [
    'PropertyType',
    'PropertyPurpose',
    'PropertyStatus', 
    'BookingStatus',
    'PaymentStatus',
    'VisitStatus',
    'AgentType',
    'ExperienceLevel',
]