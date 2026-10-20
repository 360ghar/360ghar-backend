"""Wave 3d: the rent-due reads of the MCP and agent tools use the late-fee function of the
daily job (``lifecycle.pending_late_fee``), so a fee shown before the job runs equals the
fee the job stores. The payment path uses the same function, so the balance a read shows
is a balance that can be paid.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.tool_ops.rent import compute_rent_due_items
from app.models.enums import RentChargeStatus
from app.services.pm.lifecycle import assess_overdue_charges, pending_late_fee
from app.services.pm.rent_rules import business_today
from tests.pm.test_pm_contract_wave3 import _client, _property, _user
from tests.pm.test_pm_round3_rent import _charge, _pay, _rent_lease

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 3, 20)  # the charge is due 2026-03-05; the grace period of 3 days ended 03-08


def _unit_charge(**overrides):
    values = {
        "status": RentChargeStatus.pending,
        "due_date": date(2026, 3, 5),
        "amount_due": Decimal("1500.30"),
        "late_fee_assessed": Decimal("0.00"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _unit_lease(**overrides):
    values = {
        "grace_period_days": 3,
        "late_fee_amount": Decimal("50.00"),
        "late_fee_percentage": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# The function (pure)
# ---------------------------------------------------------------------------


def test_fee_is_due_after_grace_with_a_balance():
    assert pending_late_fee(_unit_charge(), _unit_lease(), Decimal("0.00"), TODAY) == Decimal(
        "50.00"
    )


def test_fixed_amount_wins_and_a_percentage_rounds_to_cents():
    lease = _unit_lease(late_fee_amount=None, late_fee_percentage=2.5)
    charge = _unit_charge(amount_due=Decimal("1706.45"))
    assert pending_late_fee(charge, lease, Decimal("0.00"), TODAY) == Decimal("42.66")
    both = _unit_lease(late_fee_amount=Decimal("10.00"), late_fee_percentage=2.5)
    assert pending_late_fee(charge, both, Decimal("0.00"), TODAY) == Decimal("10.00")


@pytest.mark.parametrize(
    ("charge", "lease", "paid", "today"),
    [
        # inside the grace period
        (_unit_charge(), _unit_lease(grace_period_days=30), Decimal("0.00"), TODAY),
        # already assessed: once only
        (_unit_charge(late_fee_assessed=Decimal("50.00")), _unit_lease(), Decimal("0.00"), TODAY),
        # nothing owed before the fee
        (_unit_charge(), _unit_lease(), Decimal("1500.30"), TODAY),
        # waived and paid charges never get a fee
        (_unit_charge(status=RentChargeStatus.waived), _unit_lease(), Decimal("0.00"), TODAY),
        (_unit_charge(status=RentChargeStatus.paid), _unit_lease(), Decimal("0.00"), TODAY),
        # no late-fee policy on the lease
        (_unit_charge(), _unit_lease(late_fee_amount=None), Decimal("0.00"), TODAY),
    ],
)
def test_no_fee_when_the_rules_say_none(charge, lease, paid, today):
    assert pending_late_fee(charge, lease, paid, today) == Decimal("0.00")


# ---------------------------------------------------------------------------
# Read equals job: the fee shown before the job runs is the fee the job stores.
# ---------------------------------------------------------------------------


async def test_rent_due_shows_the_fee_the_job_will_store(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30", late_fee_amount="50.00")
    charge = await _charge(db_session, owner, lease)

    before = await compute_rent_due_items(db_session, owner_ids=[owner.id])
    await db_session.refresh(charge)
    assert charge.late_fee_assessed == Decimal("0.00")  # a read never writes the fee

    shown = next(i for i in before["items"] if i["id"] == charge.id)
    assert shown["late_fee"] == 50.0
    assert shown["amount_due"] == 1550.30
    assert shown["balance"] == 1550.30
    assert shown["status"] == "overdue"
    assert before["totals"]["total_due"] == 1550.30

    await assess_overdue_charges(db_session, today=business_today())
    after = await compute_rent_due_items(db_session, owner_ids=[owner.id])
    await db_session.refresh(charge)

    stored = next(i for i in after["items"] if i["id"] == charge.id)
    assert charge.late_fee_assessed == Decimal("50.00")
    assert stored == shown
    assert after["totals"] == before["totals"]


async def test_percentage_fee_read_equals_the_job_fee(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1706.45")
    lease.late_fee_percentage = 2.5
    await db_session.flush()
    charge = await _charge(db_session, owner, lease)

    before = await compute_rent_due_items(db_session, owner_ids=[owner.id])
    await assess_overdue_charges(db_session, today=business_today())
    await db_session.refresh(charge)

    shown = next(i for i in before["items"] if i["id"] == charge.id)
    assert charge.late_fee_assessed == Decimal("42.66")
    assert shown["late_fee"] == 42.66
    assert shown["balance"] == 1749.11


async def test_totals_add_the_fees_of_every_page(db_session):
    owner = await _user(db_session, name="Owner")
    first_prop = await _property(db_session, owner)
    second_prop = await _property(db_session, owner)
    first = await _rent_lease(
        db_session, owner, first_prop, rent="1000.00", late_fee_amount="25.00"
    )
    second = await _rent_lease(
        db_session, owner, second_prop, rent="2000.00", late_fee_amount="75.50"
    )
    await _charge(db_session, owner, first)  # generates the March charge of both leases

    page = await compute_rent_due_items(db_session, owner_ids=[owner.id], limit=1)

    assert len(page["items"]) == 1
    assert page["has_more"] is True
    # Both fees count in the total, not only the fee on the returned page.
    assert page["totals"]["total_due"] == 3100.50
    assert page["totals"]["charges_count"] == 2
    assert second.id != first.id


async def test_assessed_fee_is_not_added_twice(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30", late_fee_amount="50.00")
    charge = await _charge(db_session, owner, lease)
    await assess_overdue_charges(db_session, today=business_today())

    result = await compute_rent_due_items(db_session, owner_ids=[owner.id])

    shown = next(i for i in result["items"] if i["id"] == charge.id)
    assert shown["late_fee"] == 50.0
    assert shown["balance"] == 1550.30
    assert result["totals"]["total_due"] == 1550.30


async def test_job_assesses_a_stored_overdue_charge_that_has_no_fee_yet(db_session):
    """One rule for the job, the payment path and the reads: unpaid, past grace, no stored fee."""
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30", late_fee_amount="50.00")
    charge = await _charge(db_session, owner, lease)
    charge.status = RentChargeStatus.overdue
    await db_session.flush()

    first = await assess_overdue_charges(db_session, today=TODAY)
    second = await assess_overdue_charges(db_session, today=TODAY)
    await db_session.refresh(charge)

    assert (first["charges_overdue"], first["late_fees_assessed"]) == (0, 1)
    assert second["late_fees_assessed"] == 0
    assert charge.late_fee_assessed == Decimal("50.00")


# ---------------------------------------------------------------------------
# Payment path: the balance a read shows can be paid.
# ---------------------------------------------------------------------------


async def test_the_balance_shown_by_rent_due_can_be_paid(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30", late_fee_amount="50.00")
    charge = await _charge(db_session, owner, lease)

    shown = await compute_rent_due_items(db_session, owner_ids=[owner.id])
    balance = next(i for i in shown["items"] if i["id"] == charge.id)["balance"]
    assert balance == 1550.30

    async with await _client(test_app, owner) as client:
        too_much = await _pay(client, charge.id, "1550.31")
        exact = await _pay(client, charge.id, "1550.30")

    assert too_much.status_code == 400, too_much.text
    assert "exceeds outstanding balance (1550.30)" in too_much.json()["error"]["message"]
    assert exact.status_code == 201, exact.text
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.paid
    assert charge.late_fee_assessed == Decimal("50.00")


async def test_paying_only_the_rent_leaves_the_fee_as_the_balance(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30", late_fee_amount="50.00")
    charge = await _charge(db_session, owner, lease)

    async with await _client(test_app, owner) as client:
        paid = await _pay(client, charge.id, "1500.30")

    assert paid.status_code == 201, paid.text
    await db_session.refresh(charge)
    assert charge.late_fee_assessed == Decimal("50.00")
    assert charge.status == RentChargeStatus.overdue
    result = await compute_rent_due_items(db_session, owner_ids=[owner.id])
    shown = next(i for i in result["items"] if i["id"] == charge.id)
    assert shown["balance"] == 50.0
    assert result["totals"]["total_due"] == 50.0


# ---------------------------------------------------------------------------
# The tenant's MCP rent dues use the same function.
# ---------------------------------------------------------------------------


async def test_tenant_rent_dues_include_the_fee_the_job_will_store(db_session):
    from app.mcp.chatgpt.pm_tenant_tools import tenant_rent_dues
    from tests.unit.mcp.conftest import SessionContext

    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(
        db_session, owner, prop, rent="1500.30", tenant=tenant, late_fee_amount="50.00"
    )
    charge = await _charge(db_session, owner, lease)

    with (
        patch(
            "app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal",
            return_value=SessionContext(db_session),
        ),
        patch(
            "app.mcp.chatgpt.pm_tenant_tools._get_optional_user",
            new=AsyncMock(return_value=tenant),
        ),
    ):
        result = await tenant_rent_dues()

    data = result.structured_content
    row = next(c for c in data["charges"] if c["id"] == charge.id)
    assert row["late_fee"] == 50.0
    assert row["amount_due"] == 1550.30
    assert row["balance"] == 1550.30
    assert data["total_due"] == 1550.30
