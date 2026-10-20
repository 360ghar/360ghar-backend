"""PM residual pass, round 2: rent payment and overdue selection, lease creation through the PM
service (grace 0 kept, managed defaults, one occupying lease), the renew race, exact dashboard and
report totals, legacy due days, and owner contact on the list and agent views.

Each test names the reviewer item it covers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event, select, text

from app.core.exceptions import BadRequestException
from app.mcp.admin.agent_tools.leases import agent_leases_create
from app.mcp.tool_ops.leases import create_lease as tool_create_lease
from app.mcp.tool_ops.rent import record_lease_rent_payment
from app.models.agents import Agent
from app.models.enums import (
    AgentType,
    ExpenseCategory,
    ExperienceLevel,
    LeaseStatus,
    PaymentMethod,
    RentChargeStatus,
    RentPaymentStatus,
    UserRole,
)
from app.models.pm_finance import Expense, RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.services.pm.rent_rules import money as real_money
from app.services.pm_dashboard import get_dashboard_overview
from app.services.pm_leases import renew_lease
from app.services.pm_rent import generate_rent_charges, list_rent_charges
from app.services.pm_reports import expense_report, income_report, pnl_report
from tests.pm.test_pm_contract_wave3 import _client, _lease, _property, _user
from tests.pm.test_pm_round3_rent import _rent_lease

pytestmark = pytest.mark.asyncio

MARCH = date(2026, 3, 1)  # due 2026-03-05, far past the grace period
APRIL = date(2026, 4, 1)  # due 2026-04-05, also past the grace period


async def _two_charges(db, owner, lease):
    """Generate March and April charges for one lease. Returns (march, april)."""
    await generate_rent_charges(db, actor=owner, owner_id=owner.id, start_month=MARCH, months=2)
    rows = (
        (await db.execute(select(RentCharge).where(RentCharge.lease_id == lease.id)))
        .scalars()
        .all()
    )
    by_month = {row.billing_month: row for row in rows}
    return by_month[MARCH], by_month[APRIL]


def _settled(owner, lease, charge_id: int, amount: str) -> RentPayment:
    return RentPayment(
        charge_id=charge_id,
        lease_id=lease.id,
        property_id=lease.property_id,
        owner_id=owner.id,
        tenant_user_id=None,
        paid_at=datetime(2026, 3, 6, tzinfo=UTC),
        amount_paid=Decimal(amount),
        status=RentPaymentStatus.settled,
    )


# ---------------------------------------------------------------------------
# be-pm-21 follow-up: a payment through the MCP and agent path settles the oldest unpaid
# charge, including a stored overdue one. No later charge changes.
# ---------------------------------------------------------------------------


async def test_record_payment_settles_a_stored_overdue_oldest_charge(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    march, april = await _two_charges(db_session, owner, lease)
    march.status = RentChargeStatus.overdue  # the daily job stored it
    await db_session.flush()

    payment = await record_lease_rent_payment(
        db_session,
        actor=owner,
        lease_id=lease.id,
        amount=500.10,
        paid_at=datetime(2026, 4, 2, tzinfo=UTC),
        payment_method=PaymentMethod.cash,
    )
    await db_session.refresh(march)
    await db_session.refresh(april)

    assert payment.charge_id == march.id
    assert march.status == RentChargeStatus.overdue  # 1000.20 still owed, past grace
    assert april.status == RentChargeStatus.pending
    later_payments = (
        (await db_session.execute(select(RentPayment).where(RentPayment.charge_id == april.id)))
        .scalars()
        .all()
    )
    assert later_payments == []


async def test_record_payment_skips_a_repaid_overdue_charge(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    march, april = await _two_charges(db_session, owner, lease)
    march.status = RentChargeStatus.overdue  # stored before the balance was cleared
    db_session.add(_settled(owner, lease, march.id, "1500.30"))
    await db_session.flush()

    payment = await record_lease_rent_payment(
        db_session,
        actor=owner,
        lease_id=lease.id,
        amount=1500.30,
        paid_at=datetime(2026, 4, 2, tzinfo=UTC),
        payment_method=PaymentMethod.cash,
    )

    assert payment.charge_id == april.id


# ---------------------------------------------------------------------------
# be-pm-6 follow-up: status=overdue lists only charges that still owe money.
# ---------------------------------------------------------------------------


async def test_overdue_filter_skips_a_stored_overdue_charge_with_no_balance(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    march, april = await _two_charges(db_session, owner, lease)
    march.status = RentChargeStatus.overdue
    april.status = RentChargeStatus.overdue
    db_session.add(_settled(owner, lease, march.id, "1500.30"))  # March is repaid
    await db_session.flush()

    items, _, total = await list_rent_charges(
        db_session,
        actor=owner,
        status=RentChargeStatus.overdue,
        cursor_payload={},
        with_total=True,
    )

    assert [row["charge"].id for row in items] == [april.id]
    assert total == 1
    # The unfiltered list still shows the repaid charge as paid.
    everything, _, _ = await list_rent_charges(db_session, actor=owner, cursor_payload={})
    shown = {row["charge"].id: row["status"] for row in everything}
    assert shown[march.id] == RentChargeStatus.paid


# ---------------------------------------------------------------------------
# admin-pm-12, be-pm-8, be-pm-10 (AI and MCP create): one lease write path, the PM service.
# ---------------------------------------------------------------------------


async def test_tool_create_keeps_grace_zero_and_the_managed_due_day(db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    prop.payment_due_day = 15
    prop.grace_period_days = 7
    await db_session.flush()

    result = await tool_create_lease(
        db_session,
        actor=owner,
        property_id=prop.id,
        tenant_user_id=tenant.id,
        start_date="2027-01-01",
        end_date="2027-12-31",
        monthly_rent=20000,
        security_deposit=40000,
        grace_period_days=0,
        terms="No pets",
    )

    assert "error" not in result, result
    lease = await db_session.get(Lease, result["lease"]["id"])
    assert lease.grace_period_days == 0
    assert lease.payment_due_day == 15
    assert lease.status == LeaseStatus.active
    assert lease.lease_terms == {"terms": "No pets"}


async def test_tool_create_without_grace_takes_the_managed_grace(db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    prop.grace_period_days = 7
    await db_session.flush()

    result = await tool_create_lease(
        db_session,
        actor=owner,
        property_id=prop.id,
        tenant_user_id=tenant.id,
        start_date="2027-01-01",
        end_date="2027-12-31",
        monthly_rent=20000,
    )

    assert "error" not in result, result
    lease = await db_session.get(Lease, result["lease"]["id"])
    assert lease.grace_period_days == 7


async def test_tool_create_refuses_a_second_occupying_lease(db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    await _lease(db_session, owner, prop, tenant)  # active: occupies the unit

    result = await tool_create_lease(
        db_session,
        actor=owner,
        property_id=prop.id,
        tenant_user_id=tenant.id,
        start_date="2027-01-01",
        end_date="2027-12-31",
        monthly_rent=20000,
    )

    assert result["error"] is True
    assert "already has an active lease" in result["message"]


async def test_admin_agent_tool_creates_the_lease_and_returns_it(db_session):
    admin = await _user(db_session, role=UserRole.admin.value, name="Admin")
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    prop.payment_due_day = 10
    await db_session.flush()

    async def _db():
        yield db_session

    with (
        patch("app.mcp.admin.agent_tools.leases.get_db", _db),
        patch("app.mcp.admin.agent_tools.leases._get_user", new=AsyncMock(return_value=admin)),
    ):
        result = await agent_leases_create(
            property_id=prop.id,
            tenant_user_id=tenant.id,
            start_date="2027-01-01",
            end_date="2027-12-31",
            monthly_rent=20000,
            security_deposit=40000,
            grace_period_days=0,
        )

    assert result["ok"] is True, result
    lease = await db_session.get(Lease, result["data"]["lease"]["id"])
    assert lease is not None
    assert lease.owner_id == owner.id
    assert lease.grace_period_days == 0
    assert lease.payment_due_day == 10


# ---------------------------------------------------------------------------
# Renew race (be-pm-17 follow-up): the pre-check misses a lease that becomes active before the
# new lease is inserted. The index refuses the insert, and the service maps it to 400.
# ---------------------------------------------------------------------------


async def test_renew_maps_a_concurrent_occupying_lease_to_400(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    old = await _lease(db_session, owner, prop, None)  # active: the lease being renewed
    rival = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        status=LeaseStatus.draft,
        start_date=date(2026, 6, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=Decimal("20000.00"),
        security_deposit=Decimal("0.00"),
        grace_period_days=5,
        payment_due_day=5,
    )
    db_session.add(rival)
    await db_session.flush()
    await db_session.refresh(rival)

    def _rival_becomes_active_after_the_pre_check(session, flush_context, instances):
        # The first flush of renew retires the old lease. Another request then activates
        # the rival before the new lease is inserted.
        if old.status == LeaseStatus.renewed and rival.status == LeaseStatus.draft:
            rival.status = LeaseStatus.active

    event.listen(db_session.sync_session, "before_flush", _rival_becomes_active_after_the_pre_check)
    try:
        with patch("app.services.pm_leases.OCCUPIED_LEASE_STATUSES", []):
            with pytest.raises(BadRequestException) as exc_info:
                await renew_lease(
                    db_session,
                    actor=owner,
                    lease_id=old.id,
                    start_date=date(2028, 1, 1),
                    end_date=date(2029, 1, 1),
                    make_active=True,
                )
    finally:
        event.remove(
            db_session.sync_session,
            "before_flush",
            _rival_becomes_active_after_the_pre_check,
        )

    assert exc_info.value.status_code == 400
    assert "concurrent conflict" in exc_info.value.detail


# ---------------------------------------------------------------------------
# be-pm-42 follow-up and r3-est-b-20 / r3-est-b-16 neighbours: generation clamps legacy due days.
# ---------------------------------------------------------------------------


async def test_generation_clamps_legacy_due_days_outside_1_to_28(db_session):
    # Rows written before the CHECK constraint can hold a day of 0 or 40.
    await db_session.execute(
        text("ALTER TABLE leases DROP CONSTRAINT leases_payment_due_day_range")
    )
    owner = await _user(db_session, name="Owner")
    low_prop = await _property(db_session, owner)
    high_prop = await _property(db_session, owner)
    low = Lease(
        property_id=low_prop.id,
        owner_id=owner.id,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=Decimal("20000.00"),
        security_deposit=Decimal("0.00"),
        grace_period_days=5,
        payment_due_day=0,
    )
    high = Lease(
        property_id=high_prop.id,
        owner_id=owner.id,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=Decimal("20000.00"),
        security_deposit=Decimal("0.00"),
        grace_period_days=5,
        payment_due_day=40,
    )
    db_session.add_all([low, high])
    await db_session.flush()

    result = await generate_rent_charges(
        db_session, actor=owner, owner_id=owner.id, start_month=MARCH, months=1
    )

    assert result["created"] == 2
    low_charge = (
        await db_session.execute(select(RentCharge).where(RentCharge.lease_id == low.id))
    ).scalar_one()
    high_charge = (
        await db_session.execute(select(RentCharge).where(RentCharge.lease_id == high.id))
    ).scalar_one()
    assert low_charge.due_date == date(2026, 3, 1)
    assert high_charge.due_date == date(2026, 3, 28)


# ---------------------------------------------------------------------------
# Dashboard and report totals with cents (reviewer item 6). The sums are Decimal in SQL, so each
# raw value reaches money() as a Decimal, and the totals are exact.
# ---------------------------------------------------------------------------


async def test_dashboard_and_report_totals_are_exact_with_cents(db_session):
    owner = await _user(db_session, name="Owner")
    big_prop = await _property(db_session, owner)
    small_prop = await _property(db_session, owner)
    big = await _rent_lease(db_session, owner, big_prop, rent="1500.30")
    small = await _rent_lease(db_session, owner, small_prop, rent="0.10")
    big_charge, small_charge = await _charges_for(db_session, owner, big, small)

    now = datetime.now(UTC)
    db_session.add_all(
        [
            _settled_at(owner, big, big_charge.id, "1500.20", now),
            _settled_at(owner, small, small_charge.id, "0.10", now),
            Expense(
                property_id=big_prop.id,
                owner_id=owner.id,
                category=ExpenseCategory.other,
                amount=Decimal("0.10"),
                expense_date=now.date() + timedelta(days=3),
            ),
            Expense(
                property_id=big_prop.id,
                owner_id=owner.id,
                category=ExpenseCategory.other,
                amount=Decimal("1500.30"),
                expense_date=now.date() + timedelta(days=5),
            ),
        ]
    )
    await db_session.flush()

    with patch("app.services.pm_dashboard.money", side_effect=real_money) as spy:
        overview = await get_dashboard_overview(db_session, actor=owner)
    raw_values = [c.args[0] for c in spy.call_args_list]
    assert raw_values
    assert all(isinstance(value, Decimal) for value in raw_values)

    assert overview["monthly_revenue_current"] == Decimal("1500.30")
    assert overview["monthly_revenue_previous"] == Decimal("0.00")
    assert overview["outstanding_rent_total"] == Decimal("0.10")
    assert overview["upcoming_expenses_total"] == Decimal("1500.40")

    with patch("app.services.pm_reports.money", side_effect=real_money) as report_spy:
        income = await income_report(db_session, actor=owner)
        expenses = await expense_report(db_session, actor=owner)
        pnl = await pnl_report(db_session, actor=owner)
    report_values = [c.args[0] for c in report_spy.call_args_list]
    assert report_values
    assert all(isinstance(value, Decimal) for value in report_values)

    assert income["total_income"] == Decimal("1500.30")
    assert expenses["total_expenses"] == Decimal("1500.40")
    assert pnl["total_income"] == Decimal("1500.30")
    assert pnl["total_expenses"] == Decimal("1500.40")
    assert pnl["net_income"] == Decimal("-0.10")


async def _charges_for(db, owner, big, small):
    """March charges for two leases: 1500.30 and 0.10."""
    await generate_rent_charges(db, actor=owner, owner_id=owner.id, start_month=MARCH, months=1)
    rows = (
        (await db.execute(select(RentCharge).where(RentCharge.billing_month == MARCH)))
        .scalars()
        .all()
    )
    by_lease = {row.lease_id: row for row in rows}
    return by_lease[big.id], by_lease[small.id]


def _settled_at(owner, lease, charge_id: int, amount: str, paid_at: datetime) -> RentPayment:
    return RentPayment(
        charge_id=charge_id,
        lease_id=lease.id,
        property_id=lease.property_id,
        owner_id=owner.id,
        tenant_user_id=None,
        paid_at=paid_at,
        amount_paid=Decimal(amount),
        status=RentPaymentStatus.settled,
    )


# ---------------------------------------------------------------------------
# be-pm-25 follow-up: owner contact on the list route and for the assigned agent.
# ---------------------------------------------------------------------------


async def test_owner_contact_is_hidden_on_the_list_and_for_the_assigned_agent(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    own_agent = Agent(
        name="Own agent",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.intermediate,
    )
    db_session.add(own_agent)
    await db_session.flush()
    assigned = await _user(db_session, role=UserRole.agent.value, name="Assigned agent")
    assigned.agent_id = own_agent.id
    owner.agent_id = own_agent.id
    prop = await _property(db_session, owner)
    prop.owner_contact = "+919811111111"
    await db_session.flush()
    await db_session.refresh(owner)
    await db_session.refresh(assigned)

    with patch("app.services.visibility.settings.COMPANY_CONTACT_NUMBER", "+911800000000"):
        async with await _client(test_app, owner) as client:
            own_list = await client.get("/api/v1/pm/properties")
        async with await _client(test_app, assigned) as client:
            agent_list = await client.get("/api/v1/pm/properties", params={"owner_id": owner.id})
            agent_detail = await client.get(f"/api/v1/pm/properties/{prop.id}")

    assert own_list.status_code == 200, own_list.text
    assert own_list.json()["items"][0]["owner_contact"] == "+919811111111"
    assert agent_list.status_code == 200, agent_list.text
    assert agent_list.json()["items"][0]["owner_contact"] == "+911800000000"
    assert agent_detail.status_code == 200, agent_detail.text
    assert agent_detail.json()["property"]["owner_contact"] == "+911800000000"


# ---------------------------------------------------------------------------
# admin-pm-12 test gap: grace 0 is kept on the PM lease create route.
# ---------------------------------------------------------------------------


async def test_pm_lease_create_route_keeps_grace_zero(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    prop.payment_due_day = 12
    prop.grace_period_days = 9
    await db_session.flush()
    body = {
        "property_id": prop.id,
        "status": "draft",
        "start_date": "2027-01-01",
        "end_date": "2027-12-31",
        "monthly_rent": 20000,
        "security_deposit": 40000,
        "grace_period_days": 0,
    }

    async with await _client(test_app, owner) as client:
        created = await client.post("/api/v1/pm/leases", json=body)

    assert created.status_code == 201, created.text
    assert created.json()["grace_period_days"] == 0
    assert created.json()["payment_due_day"] == 12  # the managed value, not sent
    stored = await db_session.get(Lease, created.json()["id"])
    assert stored is not None
    assert stored.grace_period_days == 0


# ---------------------------------------------------------------------------
# Open defect be-pm-21-status-filter: status=pending and status=partial use the read-time status,
# so a charge past its grace period (or already repaid) is not listed as pending.
# ---------------------------------------------------------------------------


async def test_pending_filter_uses_the_read_time_status(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    lease.end_date = date(2031, 12, 31)  # cover a billing month that is not due yet
    await db_session.flush()
    await generate_rent_charges(
        db_session, actor=owner, owner_id=owner.id, start_month=MARCH, months=1
    )  # stored pending, past grace
    await generate_rent_charges(
        db_session, actor=owner, owner_id=owner.id, start_month=date(2030, 1, 1), months=1
    )  # stored pending, not due yet
    rows = (
        (await db_session.execute(select(RentCharge).where(RentCharge.lease_id == lease.id)))
        .scalars()
        .all()
    )
    past_grace = next(r for r in rows if r.billing_month == MARCH)
    not_due = next(r for r in rows if r.billing_month == date(2030, 1, 1))

    pending, _, _ = await list_rent_charges(
        db_session, actor=owner, status=RentChargeStatus.pending, cursor_payload={}
    )
    overdue, _, _ = await list_rent_charges(
        db_session, actor=owner, status=RentChargeStatus.overdue, cursor_payload={}
    )

    assert [row["charge"].id for row in pending] == [not_due.id]
    assert [row["charge"].id for row in overdue] == [past_grace.id]
