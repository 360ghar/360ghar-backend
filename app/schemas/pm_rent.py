from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RentChargeStatus


class RentChargeGenerateRequest(BaseModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    lease_id: int | None = None
    start_month: date | None = None
    months: int = Field(default=1, ge=1, le=24)


class RentCharge(BaseModel):
    id: int
    lease_id: int
    property_id: int
    owner_id: int
    tenant_user_id: int | None = None
    billing_month: date
    period_start: date
    period_end: date
    due_date: date
    amount_due: float
    late_fee_assessed: float
    status: RentChargeStatus
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RentChargeWithTotals(BaseModel):
    charge: RentCharge
    amount_paid_total: float
    amount_due_total: float
    outstanding: float


class RentPaymentCreate(BaseModel):
    charge_id: int
    amount_paid: float = Field(gt=0)
    paid_at: datetime | None = None
    payment_method: str | None = None
    reference: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None


class RentPayment(BaseModel):
    id: int
    charge_id: int
    lease_id: int
    property_id: int
    owner_id: int
    tenant_user_id: int | None = None
    paid_at: datetime
    amount_paid: float
    payment_method: str | None = None
    reference: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

