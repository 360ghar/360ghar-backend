"""Circle rate endpoints."""


from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.data_hub import BankRate, CircleRate
from app.schemas.data_hub import (
    CircleRateListResponse,
    CircleRateResponse,
    StampDutyCalculationRequest,
    StampDutyCalculationResponse,
)
from app.services.data_hub.utils import (
    calculate_registration_fee,
    calculate_stamp_duty,
)

from .helpers import _STAMP_DUTY_RATES, _paginate, _safe_list_query

router = APIRouter()


@router.get("/circle-rates", response_model=CircleRateListResponse)
async def list_circle_rates(
    sector: str | None = Query(None),
    year: int | None = Query(None),
    property_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List circle rates with optional filters."""
    filters: list[Any] = []
    if sector:
        filters.append(CircleRate.sector.ilike(f"%{sector}%"))
    if year:
        filters.append(CircleRate.revision_year == year)
    if property_type:
        filters.append(CircleRate.property_type.ilike(f"%{property_type}%"))

    count_q = select(func.count()).select_from(CircleRate)
    data_q = select(CircleRate)
    if filters:
        count_q = count_q.where(and_(*filters))
        data_q = data_q.where(and_(*filters))

    offset = (page - 1) * limit
    rows, total, meta = await _safe_list_query(db, CircleRate, count_q, data_q, offset, limit, page)
    return {
        "items": rows,
        "meta": meta,
        **_paginate(total, page, limit),
    }


@router.get("/circle-rates/sectors", response_model=list[str])
async def list_circle_rate_sectors(db: AsyncSession = Depends(get_db)):
    """List distinct sector names from circle rates."""
    from sqlalchemy import distinct

    result = await db.execute(
        select(distinct(CircleRate.sector)).order_by(CircleRate.sector)
    )
    return [r for r in result.scalars().all() if r]


@router.post("/circle-rates/calculate-duty", response_model=StampDutyCalculationResponse)
async def calculate_duty_from_circle_rates(
    req: StampDutyCalculationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Calculate stamp duty and registration fee (also callable from /calculator/stamp-duty)."""
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


@router.get("/circle-rates/{slug}", response_model=CircleRateResponse)
async def get_circle_rate(slug: str, db: AsyncSession = Depends(get_db)):
    """Get a single circle rate entry by slug."""
    result = await db.execute(
        select(CircleRate).where(CircleRate.slug == slug)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Circle rate not found")
    return row
