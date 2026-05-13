from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import ManagedPropertyStatus, UserRole
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


@router.post("", response_model=PropertySchema)
async def create_pm_property(
    property_data: PropertyCreate,
    owner_id: int | None = Query(None, description="Owner id (admin/agent only)"),
    management_status: ManagedPropertyStatus = Query(ManagedPropertyStatus.active),
    payment_due_day: int = Query(1, ge=1, le=28),
    grace_period_days: int = Query(5, ge=0, le=365),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
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


@router.get("", response_model=list[PropertySchema])
async def list_pm_properties(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    occupancy: str | None = Query(None, description="occupied|vacant"),
    q: str | None = Query(None, description="Search by title/address"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    props = await list_managed_properties(
        db,
        actor=current_user,
        owner_id=owner_id,
        occupancy=occupancy,
        q=q,
        limit=limit,
        offset=offset,
    )
    return [PropertySchema.model_validate(p) for p in props]


@router.get("/{property_id}", response_model=ManagedPropertyDetail)
async def get_pm_property(
    property_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    res = await get_managed_property_detail(db, actor=current_user, property_id=property_id)
    return {
        "property": PropertySchema.model_validate(res["property"]),
        "active_lease": (res["active_lease"] and res["active_lease"]),
    }


@router.patch("/{property_id}", response_model=PropertySchema)
async def update_pm_property(
    property_id: int,
    payload: ManagedPropertyUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
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

