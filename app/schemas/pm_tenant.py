from __future__ import annotations

from pydantic import BaseModel

from app.schemas.pm_lease import Lease as LeaseSchema


class TenantSummary(BaseModel):
    user_id: int
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    active_leases_count: int = 0


class TenantDetail(BaseModel):
    user_id: int
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    leases: list[LeaseSchema] = []

