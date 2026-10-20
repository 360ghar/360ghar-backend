from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.base import Money


class RentRollItem(BaseModel):
    property_id: int
    title: str
    occupancy: Literal["occupied", "vacant"]
    tenant_user_id: int | None = None
    monthly_rent: Money | None = None
    lease_end_date: date | None = None


class IncomeReport(BaseModel):
    """start and end are inclusive calendar days in UTC."""

    total_income: Money
    start: date | None = None
    end: date | None = None


class ExpenseReport(BaseModel):
    total_expenses: Money
    start: date | None = None
    end: date | None = None


class PnLReport(BaseModel):
    total_income: Money
    total_expenses: Money
    net_income: Money
    start: date | None = None
    end: date | None = None


class OccupancyReport(BaseModel):
    total: int
    occupied: int
    vacant: int


class MaintenanceReport(BaseModel):
    total_requests: int
