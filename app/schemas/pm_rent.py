from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PaymentMethod, RentChargeStatus, RentPaymentStatus
from app.schemas.base import Money, UtcDateTime, WriteModel


class RentChargeGenerateRequest(WriteModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    lease_id: int | None = None
    start_month: date | None = Field(
        default=None,
        description="First day of the first billing month, for example 2026-10-01. Default: this month.",
    )
    months: int = Field(default=1, ge=1, le=24)

    @field_validator("start_month")
    @classmethod
    def first_day_of_month(cls, value: date | None) -> date | None:
        if value is not None and value.day != 1:
            raise ValueError("start_month must be the first day of a month")
        return value


class RentChargeGenerateResult(BaseModel):
    """Summary of a generate run. Not a write body."""

    created: int
    skipped: int


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
    amount_due: Money
    late_fee_assessed: Money = 0.0
    status: RentChargeStatus
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)


class RentChargeWithTotals(BaseModel):
    charge: RentCharge
    amount_paid_total: Money
    amount_due_total: Money
    outstanding: Money


class RentPaymentCreate(WriteModel):
    """Record a payment. A tenant request creates a pending record; an owner, agent or admin request settles it."""

    charge_id: int
    amount_paid: Annotated[Money, Field(gt=0)]
    paid_at: UtcDateTime | None = None
    payment_method: PaymentMethod | None = None
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
    paid_at: UtcDateTime
    amount_paid: Money
    payment_method: PaymentMethod | None = None
    status: RentPaymentStatus
    reference: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)
