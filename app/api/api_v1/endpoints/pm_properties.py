from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import InsufficientPermissionsError, client_input_error
from app.models.enums import UserRole
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.pm_property import (
    ManagedPropertyCreate,
    ManagedPropertyDetail,
    ManagedPropertyUpdate,
)
from app.schemas.property import Property as PropertySchema
from app.schemas.property import PropertyCreate
from app.schemas.user import User as UserSchema
from app.services.pm_properties import (
    create_managed_property,
    get_managed_property_detail,
    list_managed_properties,
    update_managed_property,
)
from app.services.visibility import Viewer, mask_owner_contact, mask_owner_contacts

router = APIRouter()

# Managed-only keys that stay out of the core listing create.
_PM_CREATE_FIELDS = {
    "owner_id",
    "management_status",
    "payment_due_day",
    "grace_period_days",
    "late_fee_policy",
}


@router.post(
    "",
    response_model=PropertySchema,
    status_code=status.HTTP_201_CREATED,
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
                                "payment_due_day": 5,
                                "grace_period_days": 5,
                                "management_status": "active",
                            }
                        },
                    }
                }
            }
        }
    },
)
async def create_pm_property(
    payload: ManagedPropertyCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create managed property. Owner, due day, grace period and status are body fields."""
    target_owner_id = current_user.id
    if payload.owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = payload.owner_id
        else:
            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    try:
        listing = PropertyCreate.model_validate(
            payload.model_dump(exclude=_PM_CREATE_FIELDS, exclude_unset=True)
        )
    except ValidationError as exc:
        raise client_input_error(exc, "body") from exc
    prop = await create_managed_property(
        db,
        actor=current_user,
        owner_id=target_owner_id,
        property_data=listing,
        management_status=payload.management_status,
        payment_due_day=payload.payment_due_day,
        grace_period_days=payload.grace_period_days,
        late_fee_policy=payload.late_fee_policy,
    )
    return PropertySchema.model_validate(mask_owner_contact(prop, Viewer.from_user(current_user)))


@router.get("", response_model=CursorPage[PropertySchema], summary="List managed properties")
async def list_pm_properties(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    occupancy: Literal["occupied", "vacant"] | None = Query(None, description="occupied|vacant"),
    q: str | None = Query(None, description="Search by title/address"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List managed properties."""
    filters = {"owner_id": owner_id, "occupancy": occupancy, "q": q}
    rows, next_payload, total = await list_managed_properties(
        db,
        actor=current_user,
        owner_id=owner_id,
        occupancy=occupancy,
        q=q,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    viewer = Viewer.from_user(current_user)
    return build_cursor_page(
        [PropertySchema.model_validate(p) for p in mask_owner_contacts(rows, viewer)],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.get("/{property_id}", response_model=ManagedPropertyDetail, summary="Get managed property")
async def get_pm_property(
    property_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get managed property."""
    res = await get_managed_property_detail(db, actor=current_user, property_id=property_id)
    viewer = Viewer.from_user(current_user)
    return ManagedPropertyDetail(
        property=PropertySchema.model_validate(mask_owner_contact(res["property"], viewer)),
        active_lease=LeaseSchema.model_validate(res["active_lease"])
        if res["active_lease"]
        else None,
    )


@router.patch("/{property_id}", response_model=PropertySchema, summary="Update managed property")
async def update_pm_property(
    property_id: int,
    payload: ManagedPropertyUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update managed property. Send only the keys to change. An explicit null clears a nullable field."""
    prop = await update_managed_property(
        db,
        actor=current_user,
        property_id=property_id,
        body=payload,
    )
    return PropertySchema.model_validate(mask_owner_contact(prop, Viewer.from_user(current_user)))
