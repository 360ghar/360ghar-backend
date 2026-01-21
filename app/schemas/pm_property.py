from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.enums import ManagedPropertyStatus
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.property import Property as PropertySchema


class ManagedPropertyUpdate(BaseModel):
    management_status: Optional[ManagedPropertyStatus] = None
    payment_due_day: Optional[int] = Field(default=None, ge=1, le=28)
    grace_period_days: Optional[int] = Field(default=None, ge=0)
    late_fee_policy: Optional[Dict[str, Any]] = None
    images: Optional[List[str]] = None
    floor_plans: Optional[List[str]] = None


class ManagedPropertyDetail(BaseModel):
    property: PropertySchema
    active_lease: Optional[LeaseSchema] = None

