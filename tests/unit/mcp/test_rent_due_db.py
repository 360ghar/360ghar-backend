"""Rent due and rent status read RentCharge rows, with totals over the full set (database-backed).

Frozen day: 2026-10-14 (business today). Grace period is 5 days.

Owner charges:
- A  due 10-01, pending, 25000         -> overdue (past grace), balance 25000
- B  due 10-01, paid, 1000 settled     -> paid, not unpaid
- C  due 10-10, pending, 15000         -> due now, not overdue (grace ends 10-15)
- D  due 11-01, pending, 30000         -> not due yet
- E  due 10-01, partial, 5000 settled  -> overdue, balance 20000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.tool_ops import rent as rent_tool_ops
from app.models.enums import (
    LeaseStatus,
    PaymentMethod,
    PropertyPurpose,
    PropertyType,
    RentChargeStatus,
    RentPaymentStatus,
)
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User
from app.services.pm.rent_due import list_rent_charge_page

TODAY = date(2026, 10, 14)


@pytest.fixture
async def rent_world(db_session):
    owner = User(
        supabase_user_id="rent-owner",
        phone="+919100000001",
        full_name="Rent Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    other_owner = User(
        supabase_user_id="rent-other",
        phone="+919100000002",
        full_name="Other Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    tenant = User(
        supabase_user_id="rent-tenant",
        phone="+919100000003",
        full_name="Tenant",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([owner, other_owner, tenant])
    await db_session.flush()

    prop = Property(
        title="Flat 1",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=25000,
        monthly_rent=25000,
        owner_id=owner.id,
        is_managed=True,
        latitude=12.97,
        longitude=77.59,
    )
    other_prop = Property(
        title="Flat 2",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=25000,
        monthly_rent=25000,
        owner_id=other_owner.id,
        is_managed=True,
        latitude=12.97,
        longitude=77.59,
    )
    db_session.add_all([prop, other_prop])
    await db_session.flush()

    lease = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=25000,
        security_deposit=50000,
        payment_due_day=1,
        grace_period_days=5,
    )
    other_lease = Lease(
        property_id=other_prop.id,
        owner_id=other_owner.id,
        tenant_user_id=tenant.id,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=25000,
        security_deposit=50000,
        payment_due_day=1,
        grace_period_days=5,
    )
    db_session.add_all([lease, other_lease])
    await db_session.flush()

    def _charge(
        month: date, due: date, amount: float, status: RentChargeStatus, *, target=lease, p=prop
    ):
        return RentCharge(
            lease_id=target.id,
            property_id=p.id,
            owner_id=target.owner_id,
            tenant_user_id=tenant.id,
            billing_month=month,
            period_start=month,
            period_end=month,
            due_date=due,
            amount_due=amount,
            status=status,
        )

    charge_a = _charge(date(2026, 10, 1), date(2026, 10, 1), 25000, RentChargeStatus.pending)
    charge_b = _charge(date(2026, 9, 1), date(2026, 10, 1), 1000, RentChargeStatus.paid)
    # billing_month is unique per lease, so each charge on the same lease has its own month.
    charge_c = _charge(date(2026, 10, 15), date(2026, 10, 10), 15000, RentChargeStatus.pending)
    charge_d = _charge(date(2026, 11, 1), date(2026, 11, 1), 30000, RentChargeStatus.pending)
    charge_e = _charge(date(2025, 12, 1), date(2026, 10, 1), 25000, RentChargeStatus.partial)
    charge_other = _charge(
        date(2026, 10, 1),
        date(2026, 10, 1),
        9999,
        RentChargeStatus.pending,
        target=other_lease,
        p=other_prop,
    )
    db_session.add_all([charge_a, charge_b, charge_c, charge_d, charge_e, charge_other])
    await db_session.flush()

    def _payment(charge, amount):
        return RentPayment(
            charge_id=charge.id,
            lease_id=charge.lease_id,
            property_id=charge.property_id,
            owner_id=charge.owner_id,
            tenant_user_id=charge.tenant_user_id,
            paid_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            amount_paid=amount,
            payment_method=PaymentMethod.upi,
            status=RentPaymentStatus.settled,
        )

    db_session.add_all([_payment(charge_b, 1000), _payment(charge_e, 5000)])
    await db_session.flush()

    return SimpleNamespace(
        db=db_session,
        owner=owner,
        other_owner=other_owner,
        charge_a=charge_a,
        charge_b=charge_b,
        charge_c=charge_c,
        charge_d=charge_d,
        charge_e=charge_e,
        charge_other=charge_other,
    )


async def _page_ids(world, **kwargs):
    """Walk every page with the keyset cursor. Returns (ids in order, last page totals)."""
    seen: list[int] = []
    cursor = None
    totals = None
    for _ in range(10):
        page = await list_rent_charge_page(
            world.db,
            cursor_payload=cursor,
            limit=2,
            today=TODAY,
            **kwargs,
        )
        seen.extend(item["id"] for item in page.items)
        totals = page.totals
        if page.next_payload is None:
            return seen, totals
        cursor = page.next_payload
    raise AssertionError("cursor did not end")


@pytest.mark.asyncio
async def test_rent_due_totals_cover_the_full_set_not_the_page(rent_world):
    page = await list_rent_charge_page(
        rent_world.db,
        owner_ids=[rent_world.owner.id],
        due_on_or_before=TODAY,
        limit=1,
        today=TODAY,
    )

    assert len(page.items) == 1
    assert page.totals == {
        "total_due": 60000.0,
        "total_paid": 5000.0,
        "overdue_count": 2,
        "charges_count": 3,
    }


@pytest.mark.asyncio
async def test_rent_due_pages_return_every_charge_once(rent_world):
    ids, totals = await _page_ids(
        rent_world,
        owner_ids=[rent_world.owner.id],
        due_on_or_before=TODAY,
    )

    expected = {rent_world.charge_a.id, rent_world.charge_c.id, rent_world.charge_e.id}
    assert set(ids) == expected
    assert len(ids) == len(expected)
    assert totals["charges_count"] == 3


@pytest.mark.asyncio
async def test_overdue_filter_applies_before_the_page_limit(rent_world):
    first = await list_rent_charge_page(
        rent_world.db,
        owner_ids=[rent_world.owner.id],
        due_on_or_before=TODAY,
        overdue_only=True,
        limit=1,
        today=TODAY,
    )
    assert [item["id"] for item in first.items] == [rent_world.charge_a.id]
    assert first.next_payload is not None

    ids, totals = await _page_ids(
        rent_world,
        owner_ids=[rent_world.owner.id],
        due_on_or_before=TODAY,
        overdue_only=True,
    )
    assert set(ids) == {rent_world.charge_a.id, rent_world.charge_e.id}
    assert totals == {
        "total_due": 45000.0,
        "total_paid": 5000.0,
        "overdue_count": 2,
        "charges_count": 2,
    }


@pytest.mark.asyncio
async def test_items_carry_the_pm_rule_status_and_balance(rent_world):
    page = await list_rent_charge_page(
        rent_world.db,
        owner_ids=[rent_world.owner.id],
        due_on_or_before=TODAY,
        limit=10,
        today=TODAY,
    )
    by_id = {item["id"]: item for item in page.items}

    assert by_id[rent_world.charge_a.id]["status"] == "overdue"
    assert by_id[rent_world.charge_a.id]["balance"] == 25000.0
    assert by_id[rent_world.charge_a.id]["grace_end"] == "2026-10-06"
    assert by_id[rent_world.charge_c.id]["status"] == "pending"
    assert by_id[rent_world.charge_c.id]["is_overdue"] is False
    assert by_id[rent_world.charge_e.id]["status"] == "overdue"
    assert by_id[rent_world.charge_e.id]["balance"] == 20000.0


@pytest.mark.asyncio
async def test_compute_rent_due_items_returns_totals_and_bound_cursor(rent_world):
    with patch.object(rent_tool_ops, "business_today", return_value=TODAY):
        first = await rent_tool_ops.compute_rent_due_items(
            rent_world.db,
            owner_ids=[rent_world.owner.id],
            limit=2,
            filters={"owner_id": None},
        )
        second = await rent_tool_ops.compute_rent_due_items(
            rent_world.db,
            owner_ids=[rent_world.owner.id],
            cursor_payload=None,
            limit=2,
            filters={"owner_id": None},
        )

    assert first["totals"]["total_due"] == 60000.0
    assert first["totals"]["overdue_count"] == 2
    assert "counts" not in first
    assert first["has_more"] is True and first["next_cursor"]
    assert len(first["items"]) == 2
    assert second["totals"] == first["totals"]


@pytest.mark.asyncio
async def test_owner_rent_status_pages_without_repeating_the_first_page(rent_world):
    """r2-widgets-mcp-12: following next_cursor must reach the end, not loop on page one."""
    from app.mcp.chatgpt import pm_rent_tools

    @asynccontextmanager
    async def _session():
        yield rent_world.db

    user = SimpleNamespace(id=rent_world.owner.id, role="user")
    seen: list[int] = []
    cursor = None
    totals = None
    for _ in range(10):
        with (
            patch.object(pm_rent_tools, "AsyncSessionLocal", side_effect=_session),
            patch.object(pm_rent_tools, "_get_optional_user", new=AsyncMock(return_value=user)),
            patch.object(pm_rent_tools, "get_widget_for_tool", return_value="ui://w.html"),
            patch("app.services.pm.rent_due.business_today", return_value=TODAY),
        ):
            result = await pm_rent_tools.owner_rent_status(limit=2, cursor=cursor)
        data = result.structured_content
        seen.extend(c["id"] for c in data["charges"])
        totals = data["totals"]
        if not data["has_more"]:
            break
        cursor = data["next_cursor"]
    else:
        raise AssertionError("owner_rent_status never reached the last page")

    unpaid = {
        rent_world.charge_a.id,
        rent_world.charge_c.id,
        rent_world.charge_d.id,
        rent_world.charge_e.id,
    }
    assert set(seen) == unpaid
    assert len(seen) == len(unpaid)
    assert totals == {
        "total_due": 90000.0,
        "total_paid": 5000.0,
        "overdue_count": 2,
        "charges_count": 4,
    }


@pytest.mark.asyncio
async def test_owner_rent_status_include_paid_adds_settled_charges(rent_world):
    from app.mcp.chatgpt import pm_rent_tools

    @asynccontextmanager
    async def _session():
        yield rent_world.db

    user = SimpleNamespace(id=rent_world.owner.id, role="user")
    with (
        patch.object(pm_rent_tools, "AsyncSessionLocal", side_effect=_session),
        patch.object(pm_rent_tools, "_get_optional_user", new=AsyncMock(return_value=user)),
        patch.object(pm_rent_tools, "get_widget_for_tool", return_value="ui://w.html"),
        patch("app.services.pm.rent_due.business_today", return_value=TODAY),
    ):
        result = await pm_rent_tools.owner_rent_status(include_paid=True, limit=50)

    data = result.structured_content
    assert data["totals"]["charges_count"] == 5
    assert rent_world.charge_b.id in {c["id"] for c in data["charges"]}
    assert rent_world.charge_other.id not in {c["id"] for c in data["charges"]}


@pytest.mark.asyncio
async def test_rest_charge_list_and_mcp_rent_due_agree_on_status_and_balance(rent_world):
    """be-pm-21: REST /pm/rent/charges and MCP rent-due give one status and balance per charge.

    Both read the stored status through effective_status, so a pending charge past grace
    shows as overdue on both. Neither adds a late fee that the daily job has not assessed.
    """
    from app.services import pm_rent

    with patch("app.services.pm_rent.business_today", return_value=TODAY):
        rest_items, _next, _total = await pm_rent.list_rent_charges(
            rent_world.db,
            actor=rent_world.owner,
            cursor_payload={},
            limit=50,
        )
    with patch.object(rent_tool_ops, "business_today", return_value=TODAY):
        mcp = await rent_tool_ops.compute_rent_due_items(
            rent_world.db,
            owner_ids=[rent_world.owner.id],
            limit=50,
            filters={"owner_id": None},
        )

    charge_id = rent_world.charge_a.id
    rest = next(item for item in rest_items if item["charge"].id == charge_id)
    mcp_item = next(item for item in mcp["items"] if item["id"] == charge_id)
    assert getattr(rest["status"], "value", rest["status"]) == "overdue"
    assert mcp_item["status"] == "overdue"
    assert float(rest["outstanding"]) == 25000.0
    assert mcp_item["balance"] == 25000.0
    assert mcp_item["amount_due"] == 25000.0
