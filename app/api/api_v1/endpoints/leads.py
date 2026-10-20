"""
Public callback requests.

POST /leads: a visitor leaves a mobile number and an optional note for a property.
Works without sign-in; when a bearer token is present the lead is linked to the user.
GET /leads: admin reads the stored requests, newest first.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_admin, get_current_user_optional
from app.core.database import get_db
from app.middleware.rate_limit import EndpointRateLimiter
from app.models.users import User as UserModel
from app.schemas.lead import LeadCreate, LeadOut, LeadRead
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.services.lead import create_lead, list_leads

router = APIRouter()

_ip_limiter = EndpointRateLimiter(calls=10, period=60)
_phone_limiter = EndpointRateLimiter(calls=3, period=3600)


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Too many requests. Please try again later.",
        },
        headers={"Retry-After": str(retry_after)},
    )


@router.post(
    "",
    response_model=LeadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request a callback",
)
async def create_lead_endpoint(
    body: LeadCreate,
    request: Request,
    current_user: UserModel | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    """Leave a mobile number and a note. Rate limited per IP and per number."""
    if not await _ip_limiter.check_rate_limit(_ip_limiter.get_client_id(request), "POST:/leads"):
        raise _too_many(60)
    if not await _phone_limiter.check_rate_limit(f"phone:{body.phone}", "POST:/leads"):
        raise _too_many(3600)
    lead_id = await create_lead(db, body, current_user.id if current_user else None)
    return LeadOut(id=lead_id)


@router.get("", response_model=CursorPage[LeadRead], summary="List callback requests (admin)")
async def list_leads_endpoint(
    page: CursorParams = Depends(),
    current_user: UserModel = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Callback requests, newest first. Admin only. The list has no filters yet, so the
    cursor is bound to an empty filter set. include_total=true adds the total count."""
    binding: dict[str, Any] = {}
    rows, next_payload, total = await list_leads(
        db, page.decoded(binding), page.limit, with_total=page.include_total
    )
    return build_cursor_page(
        [LeadRead.model_validate(row) for row in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=binding,
    )
