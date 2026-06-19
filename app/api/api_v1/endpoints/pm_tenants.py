from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.pm_tenant import TenantDetail, TenantSummary
from app.schemas.user import User as UserSchema
from app.services.pm_tenants import get_tenant_detail, list_tenants

router = APIRouter()


@router.get("", response_model=CursorPage[TenantSummary], summary="List owner tenants")
async def list_owner_tenants(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List owner tenants."""
    rows, next_payload, count_total = await list_tenants(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    items = [TenantSummary(**r) for r in rows]
    return build_cursor_page(items, limit=page.limit, next_payload=next_payload, total=count_total)


@router.get("/{tenant_user_id}", response_model=TenantDetail, summary="Get tenant details")
async def tenant_details(
    tenant_user_id: int,
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get tenant details."""
    res = await get_tenant_detail(db, actor=current_user, tenant_user_id=tenant_user_id, owner_id=owner_id)  # type: ignore[arg-type]
    leases = [LeaseSchema.model_validate(lease) for lease in res["leases"]]
    return TenantDetail(
        user_id=res["user_id"],
        full_name=res.get("full_name"),
        phone=res.get("phone"),
        email=res.get("email"),
        leases=leases,
    )

