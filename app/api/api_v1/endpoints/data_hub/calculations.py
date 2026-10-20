"""Stamp duty and bank rate calculation endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.data_hub import BankRate, CircleRate
from app.schemas.data_hub import (
    StampDutyCalculationRequest,
    StampDutyCalculationResponse,
)
from app.services.data_hub.utils import (
    calculate_registration_fee,
    calculate_stamp_duty,
)

from .helpers import _STAMP_DUTY_RATES

router = APIRouter()


@router.post(
    "/calculator/stamp-duty",
    response_model=StampDutyCalculationResponse,
    summary="Calculate stamp duty",
)
async def calculator_stamp_duty(
    req: StampDutyCalculationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Calculate stamp duty and registration fee."""
    duty = calculate_stamp_duty(req.property_value, req.buyer_type)
    reg_fee = calculate_registration_fee(req.property_value)

    circle_rate_per_sqyd: float | None = None
    if req.sector:
        cr_result = await db.execute(
            select(CircleRate.rate_per_sqyd)
            .where(CircleRate.sector.ilike(f"%{req.sector}%"))
            .order_by(CircleRate.revision_year.desc())
            .limit(1)
        )
        cr_val = cr_result.scalar_one_or_none()
        circle_rate_per_sqyd = float(cr_val) if cr_val is not None else None

    bank_rate_result = await db.execute(
        select(BankRate.rate_value)
        .where(BankRate.rate_type == "home_loan_min")
        .order_by(BankRate.effective_date.desc())
        .limit(1)
    )
    bank_rate = bank_rate_result.scalar_one_or_none()

    return StampDutyCalculationResponse(
        property_value=req.property_value,
        circle_rate_per_sqyd=circle_rate_per_sqyd,
        stamp_duty_rate=_STAMP_DUTY_RATES.get(req.buyer_type, 7.0),
        stamp_duty_amount=duty,
        registration_fee=reg_fee,
        total_cost=duty + reg_fee,
        current_bank_rate=float(bank_rate) if bank_rate is not None else None,
    )
