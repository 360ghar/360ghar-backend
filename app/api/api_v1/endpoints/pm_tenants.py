from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.schemas.pm_tenant import TenantDetail, TenantSummary
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.user import User as UserSchema
from app.services.pm_tenants import get_tenant_detail, list_tenants

router = APIRouter()


@router.get("", response_model=list[TenantSummary])
async def list_owner_tenants(
    owner_id: Optional[int] = Query(None, description="Owner id (agent/admin only)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_tenants(db, actor=current_user, owner_id=owner_id, limit=limit, offset=offset)
    return [TenantSummary(**r) for r in rows]


@router.get("/{tenant_user_id}", response_model=TenantDetail)
async def tenant_details(
    tenant_user_id: int,
    owner_id: Optional[int] = Query(None, description="Owner id (agent/admin only)"),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    res = await get_tenant_detail(db, actor=current_user, tenant_user_id=tenant_user_id, owner_id=owner_id)
    leases = [LeaseSchema.model_validate(l) for l in res["leases"]]
    return TenantDetail(
        user_id=res["user_id"],
        full_name=res.get("full_name"),
        phone=res.get("phone"),
        email=res.get("email"),
        leases=leases,
    )

