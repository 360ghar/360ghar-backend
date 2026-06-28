from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RazorpayOrderRequest(BaseModel):
    booking_id: int


class RazorpayOrderResponse(BaseModel):
    order_id: str
    amount: float  # in rupees (client-facing)
    currency: str
    key_id: str | None
    booking_id: int
    notes: dict[str, str] = Field(default_factory=dict)


class RazorpayVerifyRequest(BaseModel):
    booking_id: int
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentMethodCreate(BaseModel):
    method_type: str = Field(..., description="card | upi | netbanking")
    brand: str | None = None
    last4: str | None = None
    razorpay_token: str | None = None
    razorpay_payment_id: str | None = None
    nickname: str | None = None
    is_default: bool = False


class PaymentMethodUpdate(BaseModel):
    nickname: str | None = None
    is_default: bool | None = None


class PaymentMethodOut(BaseModel):
    id: int
    method_type: str
    brand: str | None = None
    last4: str | None = None
    nickname: str | None = None
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
