from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ManagedPropertyStatus
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.property import Property as PropertySchema


class ManagedPropertyUpdate(BaseModel):
    management_status: ManagedPropertyStatus | None = None
    payment_due_day: int | None = Field(default=None, ge=1, le=28)
    grace_period_days: int | None = Field(default=None, ge=0)
    late_fee_policy: dict[str, Any] | None = None
    images: list[str] | None = None
    floor_plans: list[str] | None = None


class ManagedPropertyDetail(BaseModel):
    property: PropertySchema
    active_lease: LeaseSchema | None = None

