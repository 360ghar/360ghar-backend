from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import LeaseStatus


class LeaseCreate(BaseModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    property_id: int
    tenant_user_id: int | None = None
    tenant_name: str | None = None
    tenant_phone: str | None = None
    tenant_email: str | None = None

    status: LeaseStatus = LeaseStatus.draft
    start_date: date
    end_date: date

    monthly_rent: float
    security_deposit: float

    late_fee_amount: float | None = None
    late_fee_percentage: float | None = None
    grace_period_days: int = 5
    payment_due_day: int = 1

    lease_terms: dict[str, Any] | None = None
    special_clauses: str | None = None
    lease_document_id: int | None = None


class Lease(BaseModel):
    id: int
    property_id: int
    owner_id: int
    tenant_user_id: int | None = None
    tenant_name: str | None = None
    tenant_phone: str | None = None
    tenant_email: str | None = None
    status: LeaseStatus
    start_date: date
    end_date: date
    monthly_rent: Decimal
    security_deposit: Decimal
    late_fee_amount: Decimal | None = None
    late_fee_percentage: float | None = None
    grace_period_days: int
    payment_due_day: int
    lease_terms: dict[str, Any] | None = None
    special_clauses: str | None = None
    signed_by_tenant_at: datetime | None = None
    signed_by_owner_at: datetime | None = None
    termination_date: date | None = None
    termination_reason: str | None = None
    lease_document_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("lease_terms", mode="before")
    @classmethod
    def ensure_dict(cls, v: Any) -> Any:
        if v is not None and not isinstance(v, dict):
            raise ValueError("lease_terms must be a JSON object, not a list")
        return v


class LeaseUploadSigned(BaseModel):
    lease_document_id: int
    signed_by_owner: bool = True
    signed_by_tenant: bool = False


class LeaseRenew(BaseModel):
    start_date: date
    end_date: date
    monthly_rent: float | None = None
    security_deposit: float | None = None
    make_active: bool = False


class LeaseTerminate(BaseModel):
    termination_date: date | None = None
    reason: str | None = None

