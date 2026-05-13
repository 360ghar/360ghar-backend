from __future__ import annotations

from pydantic import BaseModel


class DashboardOverview(BaseModel):
    total_properties: int
    occupied_properties: int
    vacant_properties: int
    under_maintenance_properties: int
    monthly_revenue_current: float
    monthly_revenue_previous: float
    outstanding_rent_total: float
    upcoming_expenses_total: float


class ActivityItem(BaseModel):
    type: str
    at: str
    id: int | None = None
    property_id: int | None = None
    lease_id: int | None = None
    amount: float | None = None
    status: str | None = None

