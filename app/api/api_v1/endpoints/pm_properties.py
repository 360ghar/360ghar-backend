from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import ManagedPropertyStatus, UserRole
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.pm_property import ManagedPropertyDetail, ManagedPropertyUpdate
from app.schemas.property import Property as PropertySchema
from app.schemas.property import PropertyCreate
from app.schemas.user import User as UserSchema
from app.services.pm_properties import (
    create_managed_property,
    get_managed_property_detail,
    list_managed_properties,
    update_managed_property,
)

router = APIRouter()


@router.post(
    "",
    response_model=PropertySchema,
    summary="Create managed property",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "value": {
                                "title": "2BHK Managed Apartment",
                                "property_type": "apartment",
                                "purpose": "rent",
                                "base_price": 50000,
                                "monthly_rent": 25000,
                                "city": "Bengaluru",
                                "locality": "Indiranagar",
                            }
                        },
                    }
                }
            }
        }
    },
)
async def create_pm_property(
    property_data: PropertyCreate,
    owner_id: int | None = Query(None, description="Owner id (admin/agent only)"),
    management_status: ManagedPropertyStatus = Query(ManagedPropertyStatus.active),
    payment_due_day: int = Query(1, ge=1, le=28),
    grace_period_days: int = Query(5, ge=0, le=365),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create managed property."""
    target_owner_id = current_user.id
    if owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    prop = await create_managed_property(
        db,
        actor=current_user,
        owner_id=target_owner_id,
        property_data=property_data,
        management_status=management_status,
        payment_due_day=payment_due_day,
        grace_period_days=grace_period_days,
    )
    return PropertySchema.model_validate(prop)


@router.get("", response_model=CursorPage[PropertySchema], summary="List managed properties")
async def list_pm_properties(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    occupancy: str | None = Query(None, description="occupied|vacant"),
    q: str | None = Query(None, description="Search by title/address"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List managed properties."""
    rows, next_payload, total = await list_managed_properties(
        db,
        actor=current_user,
        owner_id=owner_id,
        occupancy=occupancy,
        q=q,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [PropertySchema.model_validate(p) for p in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.get("/{property_id}", response_model=ManagedPropertyDetail, summary="Get managed property")
async def get_pm_property(
    property_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get managed property."""
    res = await get_managed_property_detail(db, actor=current_user, property_id=property_id)
    return {
        "property": PropertySchema.model_validate(res["property"]),
        "active_lease": LeaseSchema.model_validate(res["active_lease"]) if res["active_lease"] else None,
    }


@router.patch("/{property_id}", response_model=PropertySchema, summary="Update managed property")
async def update_pm_property(
    property_id: int,
    payload: ManagedPropertyUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update managed property."""
    prop = await update_managed_property(
        db,
        actor=current_user,
        property_id=property_id,
        management_status=payload.management_status,
        payment_due_day=payload.payment_due_day,
        grace_period_days=payload.grace_period_days,
        late_fee_policy=payload.late_fee_policy,
        images=payload.images,
        floor_plans=payload.floor_plans,
    )
    return PropertySchema.model_validate(prop)

