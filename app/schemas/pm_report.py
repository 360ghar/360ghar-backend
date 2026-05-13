from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class RentRollItem(BaseModel):
    property_id: int
    title: str
    occupancy: str
    tenant_user_id: int | None = None
    monthly_rent: float | None = None
    lease_end_date: date | None = None


class IncomeReport(BaseModel):
    total_income: float
    start: datetime | None = None
    end: datetime | None = None


class ExpenseReport(BaseModel):
    total_expenses: float
    start: date | None = None
    end: date | None = None


class PnLReport(BaseModel):
    total_income: float
    total_expenses: float
    net_income: float
    start: date | None = None
    end: date | None = None


class OccupancyReport(BaseModel):
    total: int
    occupied: int
    vacant: int


class MaintenanceReport(BaseModel):
    total_requests: int

