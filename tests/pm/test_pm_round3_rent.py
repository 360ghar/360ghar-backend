"""PM residual pass: exact rent money (blocker), read-time and stored overdue (be-pm-6),
rent-due rows from RentCharge (be-pm-21). Each test names the finding it covers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.mcp.tool_ops.rent import compute_rent_due_items
from app.models.enums import LeaseStatus, RentChargeStatus, RentPaymentStatus
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.services.pm.lifecycle import assess_overdue_charges
from app.services.pm_rent import generate_rent_charges
from tests.pm.test_pm_contract_wave3 import _client, _property, _user

pytestmark = pytest.mark.asyncio

CHARGE_MONTH = date(2026, 3, 1)  # due 2026-03-05, far past the grace period


async def _rent_lease(
    db,
    owner,
    prop,
    *,
    rent: str,
    tenant=None,
    grace: int = 5,
    late_fee_amount: str | None = None,
) -> Lease:
    lease = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id if tenant else None,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=Decimal(rent),
        security_deposit=Decimal("0.00"),
        grace_period_days=grace,
        payment_due_day=5,
        late_fee_amount=Decimal(late_fee_amount) if late_fee_amount else None,
    )
    db.add(lease)
    await db.flush()
    await db.refresh(lease)
    return lease


async def _charge(db, owner, lease) -> RentCharge:
    await generate_rent_charges(
        db, actor=owner, owner_id=owner.id, start_month=CHARGE_MONTH, months=1
    )
    return (
        await db.execute(
            select(RentCharge).where(
                RentCharge.lease_id == lease.id, RentCharge.billing_month == CHARGE_MONTH
            )
        )
    ).scalar_one()


async def _pay(client, charge_id: int, amount: str):
    return await client.post(
        "/api/v1/pm/rent/payments", json={"charge_id": charge_id, "amount_paid": float(amount)}
    )


# ---------------------------------------------------------------------------
# Blocker: rent balances are exact. Float sums rejected a valid last payment and left
# fully paid charges overdue.
# ---------------------------------------------------------------------------


async def test_split_payments_settle_a_charge_with_cents_exactly(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    charge = await _charge(db_session, owner, lease)

    async with await _client(test_app, owner) as client:
        first = await _pay(client, charge.id, "500.10")
        second = await _pay(client, charge.id, "500.10")
        # The last 500.10 is the exact remaining balance. Float arithmetic refused it.
        third = await _pay(client, charge.id, "500.10")

    assert [first.status_code, second.status_code, third.status_code] == [201, 201, 201]
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.paid


async def test_three_way_split_of_1706_45_is_paid_and_never_reads_overdue(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1706.45")
    charge = await _charge(db_session, owner, lease)

    async with await _client(test_app, owner) as client:
        for amount in ("1599.96", "53.90", "52.59"):
            response = await _pay(client, charge.id, amount)
            assert response.status_code == 201, response.text

        charges = await client.get("/api/v1/pm/rent/charges", params={"lease_id": lease.id})
        overdue = await client.get(
            "/api/v1/pm/rent/charges", params={"lease_id": lease.id, "status": "overdue"}
        )

    assert charges.status_code == 200, charges.text
    row = charges.json()["items"][0]
    assert row["charge"]["status"] == "paid"
    assert row["outstanding"] == 0.0
    assert row["amount_paid_total"] == 1706.45
    assert overdue.status_code == 200, overdue.text
    assert overdue.json()["items"] == []
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.paid


async def test_overpayment_by_one_cent_is_refused(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    charge = await _charge(db_session, owner, lease)

    async with await _client(test_app, owner) as client:
        assert (await _pay(client, charge.id, "1500.20")).status_code == 201
        refused = await _pay(client, charge.id, "0.11")
        exact = await _pay(client, charge.id, "0.10")

    assert refused.status_code == 400, refused.text
    assert "exceeds outstanding balance (0.10)" in refused.json()["error"]["message"]
    assert exact.status_code == 201, exact.text


async def test_tenant_claim_settles_to_an_exact_balance(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30", tenant=tenant)
    charge = await _charge(db_session, owner, lease)

    async with await _client(test_app, tenant) as tenant_client:
        claim = await _pay(tenant_client, charge.id, "1000.20")
    assert claim.status_code == 201, claim.text
    assert claim.json()["status"] == "pending"
    await db_session.refresh(charge)
    assert charge.status != RentChargeStatus.paid

    async with await _client(test_app, owner) as owner_client:
        settled = await owner_client.post(f"/api/v1/pm/rent/payments/{claim.json()['id']}/settle")
        rest = await _pay(owner_client, charge.id, "500.10")
    assert settled.status_code == 200, settled.text
    assert rest.status_code == 201, rest.text
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.paid


# ---------------------------------------------------------------------------
# be-pm-6: overdue is derived on read, and the daily job stores it once. A stored overdue
# charge that is already repaid is corrected to paid.
# ---------------------------------------------------------------------------


async def test_unpaid_charge_past_grace_reads_overdue_before_the_job_runs(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    charge = await _charge(db_session, owner, lease)
    assert charge.status == RentChargeStatus.pending  # stored value, before the job

    async with await _client(test_app, owner) as client:
        response = await client.get(
            "/api/v1/pm/rent/charges", params={"lease_id": lease.id, "status": "overdue"}
        )
    assert response.status_code == 200, response.text
    assert [i["charge"]["id"] for i in response.json()["items"]] == [charge.id]


async def test_daily_job_stores_overdue_and_assesses_the_fee_once(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30", late_fee_amount="50.00")
    charge = await _charge(db_session, owner, lease)

    first = await assess_overdue_charges(db_session, today=date(2026, 3, 20))
    second = await assess_overdue_charges(db_session, today=date(2026, 3, 20))
    await db_session.refresh(charge)

    assert first["charges_overdue"] == 1
    assert first["late_fees_assessed"] == 1
    assert second["charges_overdue"] == 0
    assert second["late_fees_assessed"] == 0
    assert charge.status == RentChargeStatus.overdue
    assert charge.late_fee_assessed == Decimal("50.00")


async def test_job_corrects_a_stored_overdue_charge_that_is_already_repaid(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    charge = await _charge(db_session, owner, lease)
    # Rows written before exact money math: overdue stored, balance already cleared.
    charge.status = RentChargeStatus.overdue
    db_session.add(
        RentPayment(
            charge_id=charge.id,
            lease_id=lease.id,
            property_id=prop.id,
            owner_id=owner.id,
            tenant_user_id=None,
            paid_at=datetime(2026, 3, 6, tzinfo=UTC),
            amount_paid=Decimal("1500.30"),
            status=RentPaymentStatus.settled,
        )
    )
    await db_session.flush()

    stats = await assess_overdue_charges(db_session, today=date(2026, 3, 20))
    await db_session.refresh(charge)

    assert stats["charges_settled"] == 1
    assert charge.status == RentChargeStatus.paid


# ---------------------------------------------------------------------------
# be-pm-21: the MCP rent-due tool reads RentCharge rows through the PM rules. Due date,
# grace end, late fee and balance come from the charge, not from lease math.
# ---------------------------------------------------------------------------


async def test_rent_due_lists_charge_rows_with_their_late_fee(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(
        db_session, owner, prop, rent="1500.30", grace=3, late_fee_amount="50.00"
    )
    charge = await _charge(db_session, owner, lease)
    await assess_overdue_charges(db_session, today=date(2026, 3, 20))

    result = await compute_rent_due_items(db_session, owner_ids=[owner.id])

    item = next(i for i in result["items"] if i["id"] == charge.id)
    assert item["due_date"] == "2026-03-05"
    assert item["grace_end"] == "2026-03-08"
    assert item["is_overdue"] is True
    assert item["late_fee"] == 50.00
    assert item["balance"] == 1550.30
    assert result["totals"]["total_due"] == 1550.30


async def test_rent_due_skips_a_charge_that_is_fully_paid(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _rent_lease(db_session, owner, prop, rent="1500.30")
    charge = await _charge(db_session, owner, lease)
    db_session.add(
        RentPayment(
            charge_id=charge.id,
            lease_id=lease.id,
            property_id=prop.id,
            owner_id=owner.id,
            paid_at=datetime(2026, 3, 6, tzinfo=UTC),
            amount_paid=Decimal("1500.30"),
            status=RentPaymentStatus.settled,
        )
    )
    await db_session.flush()

    result = await compute_rent_due_items(db_session, owner_ids=[owner.id])

    assert all(i["id"] != charge.id for i in result["items"])
