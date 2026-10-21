from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.base import Money, UtcDateTime


class DashboardOverview(BaseModel):
    total_properties: int
    occupied_properties: int
    vacant_properties: int
    under_maintenance_properties: int
    monthly_revenue_current: Money
    monthly_revenue_previous: Money
    outstanding_rent_total: Money
    upcoming_expenses_total: Money


class ActivityItem(BaseModel):
    type: Literal["rent_payment", "maintenance_request", "lease"]
    at: UtcDateTime
    title: str
    description: str | None = None
    id: int | None = None
    property_id: int | None = None
    lease_id: int | None = None
    amount: Money | None = None
    status: str | None = None
