"""Lease list stats cover the whole owner scope, not one page (database-backed).

r2-widgets-mcp-11: an owner with more leases than one page must still see the full
active count and monthly rent in ``stats``.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.mcp.tool_ops import leases as lease_ops
from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User


@pytest.fixture
async def owner_with_leases(db_session):
    owner = User(
        supabase_user_id="lease-stats-owner",
        phone="+919200000001",
        full_name="Lease Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    tenant = User(
        supabase_user_id="lease-stats-tenant",
        phone="+919200000002",
        full_name="Lease Tenant",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([owner, tenant])
    await db_session.flush()

    def _prop(n: int) -> Property:
        return Property(
            title=f"Flat {n}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=20000,
            monthly_rent=20000,
            owner_id=owner.id,
            is_managed=True,
            latitude=12.97,
            longitude=77.59,
        )

    props = [_prop(n) for n in range(1, 5)]
    db_session.add_all(props)
    await db_session.flush()

    statuses = [LeaseStatus.active, LeaseStatus.active, LeaseStatus.active, LeaseStatus.terminated]
    rents = [10000, 12000, 15000, 99000]
    leases = []
    for prop, status, rent in zip(props, statuses, rents, strict=True):
        leases.append(
            Lease(
                property_id=prop.id,
                owner_id=owner.id,
                tenant_user_id=tenant.id,
                status=status,
                start_date=date(2026, 1, 1),
                end_date=date(2027, 12, 31),
                monthly_rent=rent,
                security_deposit=0,
                payment_due_day=1,
                grace_period_days=5,
            )
        )
    db_session.add_all(leases)
    await db_session.flush()
    return owner, db_session


@pytest.mark.asyncio
async def test_stats_cover_every_lease_when_the_list_is_paged(owner_with_leases):
    owner, db = owner_with_leases

    page = await lease_ops.list_leases(db, actor=owner, accessible_owner_ids=[owner.id], limit=1)

    assert len(page["leases"]) == 1
    assert page["has_more"] is True
    # Three active leases (10000 + 12000 + 15000); the terminated lease is not counted.
    assert page["stats"] == {"active_leases": 3, "total_monthly_rent": 37000.0}


@pytest.mark.asyncio
async def test_stats_ignore_the_status_filter_and_follow_the_scope(owner_with_leases):
    owner, db = owner_with_leases

    filtered = await lease_ops.list_leases(
        db,
        actor=owner,
        accessible_owner_ids=[owner.id],
        status=LeaseStatus.terminated.value,
        limit=10,
    )
    outside = await lease_ops.list_leases(db, actor=owner, accessible_owner_ids=[], limit=10)

    assert [item["status"] for item in filtered["leases"]] == ["terminated"]
    assert filtered["stats"]["active_leases"] == 3
    assert outside["stats"] == {"active_leases": 0, "total_monthly_rent": 0.0}
