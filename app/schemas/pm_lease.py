from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import LeaseStatus
from app.schemas.base import Money, UtcDateTime, WriteModel

CREATE_LEASE_STATUSES = (LeaseStatus.draft, LeaseStatus.pending_signature, LeaseStatus.active)


class LeaseCreate(WriteModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    property_id: int
    tenant_user_id: int | None = None
    tenant_name: str | None = None
    tenant_phone: str | None = None
    tenant_email: str | None = None

    status: LeaseStatus = LeaseStatus.draft
    start_date: date
    end_date: date

    monthly_rent: Annotated[Money, Field(gt=0)]
    security_deposit: Annotated[Money, Field(ge=0)]

    late_fee_amount: Annotated[Money | None, Field(ge=0)] = None
    late_fee_percentage: float | None = Field(default=None, ge=0, le=100)
    grace_period_days: int | None = Field(
        default=None, ge=0, description="Default: the managed property's grace period."
    )
    payment_due_day: int | None = Field(
        default=None, ge=1, le=28, description="Default: the managed property's due day."
    )

    lease_terms: dict[str, Any] | None = None
    special_clauses: str | None = None
    lease_document_id: int | None = None

    @field_validator("status")
    @classmethod
    def create_status_only(cls, value: LeaseStatus) -> LeaseStatus:
        # Ended leases come from renew, terminate and the daily job, never from create.
        if value not in CREATE_LEASE_STATUSES:
            raise ValueError("status must be draft, pending_signature or active")
        return value


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
    monthly_rent: Money
    security_deposit: Money
    late_fee_amount: Money | None = None
    late_fee_percentage: float | None = None
    grace_period_days: int
    payment_due_day: int
    lease_terms: dict[str, Any] | None = None
    special_clauses: str | None = None
    signed_by_tenant_at: UtcDateTime | None = None
    signed_by_owner_at: UtcDateTime | None = None
    termination_date: date | None = None
    termination_reason: str | None = None
    lease_document_id: int | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("lease_terms", mode="before")
    @classmethod
    def ensure_dict(cls, v: Any) -> Any:
        if v is not None and not isinstance(v, dict):
            raise ValueError("lease_terms must be a JSON object, not a list")
        return v


class LeaseUploadSigned(WriteModel):
    lease_document_id: int
    signed_by_owner: bool = True
    signed_by_tenant: bool = False


class LeaseRenew(WriteModel):
    start_date: date
    end_date: date
    monthly_rent: Annotated[Money | None, Field(gt=0)] = None
    security_deposit: Annotated[Money | None, Field(ge=0)] = None
    make_active: bool = False


class LeaseTerminate(WriteModel):
    termination_date: date | None = None
    reason: str | None = None
