"""Shared list functions: real totals, one list key, and cursors bound to filters.

Each case uses more rows than the page limit, so a page length cannot pass for a total.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.core.exceptions import ValidationException
from app.mcp.tool_ops import get_rent_history, list_maintenance_requests
from app.models.enums import (
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    PaymentMethod,
    PropertyPurpose,
    PropertyType,
    RentChargeStatus,
    RentPaymentStatus,
)
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import decode_cursor


@pytest.fixture
async def tenant_world(db_session):
    owner = User(
        supabase_user_id="list-owner",
        phone="+919200000001",
        full_name="List Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    tenant = User(
        supabase_user_id="list-tenant",
        phone="+919200000002",
        full_name="List Tenant",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([owner, tenant])
    await db_session.flush()

    prop = Property(
        title="List Flat",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=20000,
        owner_id=owner.id,
        is_managed=True,
    )
    db_session.add(prop)
    await db_session.flush()

    lease = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=20000,
        security_deposit=20000,
    )
    db_session.add(lease)
    await db_session.flush()

    charge = RentCharge(
        lease_id=lease.id,
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id,
        billing_month=date(2026, 3, 1),
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        due_date=date(2026, 3, 1),
        amount_due=20000,
        status=RentChargeStatus.pending,
    )
    db_session.add(charge)
    await db_session.flush()

    for day, amount in ((1, 1000.10), (2, 2000.20), (3, 3000.30)):
        db_session.add(
            RentPayment(
                charge_id=charge.id,
                lease_id=lease.id,
                property_id=prop.id,
                owner_id=owner.id,
                tenant_user_id=tenant.id,
                paid_at=datetime(2026, 3, day, tzinfo=UTC),
                amount_paid=amount,
                payment_method=PaymentMethod.cash,
                status=RentPaymentStatus.settled,
            )
        )

    for index, status in enumerate(
        (
            MaintenanceRequestStatus.open,
            MaintenanceRequestStatus.open,
            MaintenanceRequestStatus.closed,
        )
    ):
        db_session.add(
            MaintenanceRequest(
                property_id=prop.id,
                owner_id=owner.id,
                tenant_user_id=tenant.id,
                category=MaintenanceCategory.plumbing,
                urgency=MaintenanceUrgency.medium,
                title=f"Request {index}",
                request_status=status,
            )
        )
    await db_session.flush()
    return SimpleNamespace(db=db_session, tenant=tenant)


@pytest.mark.asyncio
async def test_rent_history_page_has_no_total_until_asked(tenant_world):
    result = await get_rent_history(tenant_world.db, tenant_user_id=tenant_world.tenant.id, limit=2)

    assert "payments" not in result
    assert len(result["items"]) == 2
    assert result["total"] is None
    assert result["has_more"] is True
    assert result["next_cursor"] is not None


@pytest.mark.asyncio
async def test_rent_history_total_is_the_real_count_and_the_sum_is_not_the_page(tenant_world):
    result = await get_rent_history(
        tenant_world.db,
        tenant_user_id=tenant_world.tenant.id,
        limit=2,
        include_total=True,
    )

    assert result["total"] == 3
    # The sum covers all three payments, not the two on the page, rounded to 2 places.
    assert result["total_collected"] == 6000.6


@pytest.mark.asyncio
async def test_rent_history_second_page_returns_the_rest(tenant_world):
    first = await get_rent_history(tenant_world.db, tenant_user_id=tenant_world.tenant.id, limit=2)
    second = await get_rent_history(
        tenant_world.db,
        tenant_user_id=tenant_world.tenant.id,
        cursor_payload=decode_cursor(first["next_cursor"], {}),
        limit=2,
    )

    assert len(second["items"]) == 1
    assert second["has_more"] is False
    assert second["items"][0]["charge_id"] is not None
    assert second["items"][0]["amount_paid"] == 1000.1


@pytest.mark.asyncio
async def test_maintenance_list_total_is_the_matching_count(tenant_world):
    result = await list_maintenance_requests(
        tenant_world.db,
        tenant_user_id=tenant_world.tenant.id,
        limit=2,
        include_total=True,
    )

    assert "requests" not in result
    assert len(result["items"]) == 2
    assert result["total"] == 3
    assert result["has_more"] is True


@pytest.mark.asyncio
async def test_maintenance_list_total_counts_only_the_filter(tenant_world):
    result = await list_maintenance_requests(
        tenant_world.db,
        tenant_user_id=tenant_world.tenant.id,
        status="open",
        limit=1,
        include_total=True,
        filters={"status": "open"},
    )

    assert len(result["items"]) == 1
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_cursor_from_one_filter_is_rejected_for_another(tenant_world):
    first = await list_maintenance_requests(
        tenant_world.db,
        tenant_user_id=tenant_world.tenant.id,
        status="open",
        limit=1,
        filters={"status": "open"},
    )
    assert first["next_cursor"] is not None

    with pytest.raises(ValidationException) as raised:
        decode_cursor(first["next_cursor"], {"status": "completed"})

    assert raised.value.detail
