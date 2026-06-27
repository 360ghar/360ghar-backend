from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType, RentChargeStatus, UserRole
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def rent_owner(db_session) -> User:
    """A regular user who acts as a PM portfolio owner."""
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="rent_owner@example.com",
        phone="+919100000001",
        full_name="Rent Owner",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def rent_client(test_app, rent_owner) -> AsyncClient:
    """Authenticated client wired to rent_owner."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(rent_owner, from_attributes=True)

    async def override_get_current_user() -> UserSchema:
        return user_schema

    async def override_get_current_active_user() -> UserSchema:
        return user_schema

    async def override_get_current_user_optional() -> UserSchema:
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_rent_charges(db_session, rent_owner) -> list[RentCharge]:
    """Seed 3 rent charges with distinct due_dates for rent_owner."""
    prop = Property(
        title="Rent Charge Pagination Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
        owner_id=rent_owner.id,
        is_managed=True,
    )
    db_session.add(prop)
    await db_session.flush()

    lease = Lease(
        property_id=prop.id,
        owner_id=rent_owner.id,
        tenant_name="Test Tenant",
        tenant_phone="+919100000002",
        status=LeaseStatus.active,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        monthly_rent=20000.0,
        security_deposit=40000.0,
        grace_period_days=5,
        payment_due_day=5,
    )
    db_session.add(lease)
    await db_session.flush()

    charges = []
    # Seed 3 charges with distinct billing_month (and thus distinct due_date)
    for i in range(3):
        billing_month = date(2025, i + 1, 1)
        due_date = date(2025, i + 1, 5)
        charge = RentCharge(
            lease_id=lease.id,
            property_id=prop.id,
            owner_id=rent_owner.id,
            billing_month=billing_month,
            period_start=billing_month,
            period_end=date(2025, i + 1, 28),
            due_date=due_date,
            amount_due=20000.0,
            late_fee_assessed=0.0,
            status=RentChargeStatus.pending,
        )
        db_session.add(charge)
        await db_session.flush()
        await db_session.refresh(charge)
        charges.append(charge)

    return charges


@pytest_asyncio.fixture
async def seeded_rent_payments(db_session, rent_owner) -> list[RentPayment]:
    """Seed 3 rent payments for rent_owner (with required charge/lease/property FKs)."""
    prop = Property(
        title="Rent Payment Pagination Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
        owner_id=rent_owner.id,
        is_managed=True,
    )
    db_session.add(prop)
    await db_session.flush()

    lease = Lease(
        property_id=prop.id,
        owner_id=rent_owner.id,
        tenant_name="Payment Tenant",
        tenant_phone="+919100000003",
        status=LeaseStatus.active,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        monthly_rent=20000.0,
        security_deposit=40000.0,
        grace_period_days=5,
        payment_due_day=5,
    )
    db_session.add(lease)
    await db_session.flush()

    # One charge for all payments to reference
    charge = RentCharge(
        lease_id=lease.id,
        property_id=prop.id,
        owner_id=rent_owner.id,
        billing_month=date(2025, 1, 1),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        due_date=date(2025, 1, 5),
        amount_due=60000.0,
        late_fee_assessed=0.0,
        status=RentChargeStatus.partial,
    )
    db_session.add(charge)
    await db_session.flush()

    payments = []
    base_time = datetime(2025, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        payment = RentPayment(
            charge_id=charge.id,
            lease_id=lease.id,
            property_id=prop.id,
            owner_id=rent_owner.id,
            paid_at=base_time - timedelta(days=i),  # descending: newest first = day 10, 9, 8
            amount_paid=5000.0,
        )
        db_session.add(payment)
        await db_session.flush()
        await db_session.refresh(payment)
        payments.append(payment)

    return payments


# ---------------------------------------------------------------------------
# Rent Charges tests
# ---------------------------------------------------------------------------


async def test_charges_cursor_paginates(
    rent_client: AsyncClient, seeded_rent_charges: list[RentCharge]
) -> None:
    r1 = await rent_client.get("/api/v1/pm/rent/charges?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"] is not None

    r2 = await rent_client.get(f"/api/v1/pm/rent/charges?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None

    ids1 = {item["charge"]["id"] for item in body1["items"]}
    ids2 = {item["charge"]["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)  # no overlap across pages


async def test_charges_asc_order_earliest_first(
    rent_client: AsyncClient, seeded_rent_charges: list[RentCharge]
) -> None:
    """Page 1 should contain the earliest due_date items (ASC order)."""
    r = await rent_client.get("/api/v1/pm/rent/charges?limit=2")
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert len(items) == 2
    # Earliest due_date should be first
    due_dates = [item["charge"]["due_date"] for item in items]
    assert due_dates == sorted(due_dates)
    # Should be the two earliest of the 3 seeded charges
    seeded_due_dates = sorted(c.due_date.isoformat() for c in seeded_rent_charges)
    assert due_dates[0] == seeded_due_dates[0]
    assert due_dates[1] == seeded_due_dates[1]


async def test_charges_invalid_cursor_400(rent_client: AsyncClient) -> None:
    r = await rent_client.get("/api/v1/pm/rent/charges?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def test_charges_include_total(
    rent_client: AsyncClient, seeded_rent_charges: list[RentCharge]
) -> None:
    r = await rent_client.get("/api/v1/pm/rent/charges?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


# ---------------------------------------------------------------------------
# Rent Payments tests
# ---------------------------------------------------------------------------


async def test_payments_cursor_paginates(
    rent_client: AsyncClient, seeded_rent_payments: list[RentPayment]
) -> None:
    r1 = await rent_client.get("/api/v1/pm/rent/payments?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"] is not None

    r2 = await rent_client.get(f"/api/v1/pm/rent/payments?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None

    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)  # no overlap across pages


async def test_payments_invalid_cursor_400(rent_client: AsyncClient) -> None:
    r = await rent_client.get("/api/v1/pm/rent/payments?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def test_payments_desc_order_newest_first(
    rent_client: AsyncClient, seeded_rent_payments: list[RentPayment]
) -> None:
    """Page 1 should contain the newest paid_at items (DESC order)."""
    r = await rent_client.get("/api/v1/pm/rent/payments?limit=2")
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert len(items) == 2
    # Newest paid_at should be first
    paid_ats = [item["paid_at"] for item in items]
    assert paid_ats == sorted(paid_ats, reverse=True)
    # Should be the two newest of the 3 seeded payments
    seeded_paid_ats = sorted(
        (p.paid_at.isoformat().replace("+00:00", "Z") for p in seeded_rent_payments), reverse=True
    )
    assert paid_ats[0] == seeded_paid_ats[0]
    assert paid_ats[1] == seeded_paid_ats[1]


async def test_payments_include_total(
    rent_client: AsyncClient, seeded_rent_payments: list[RentPayment]
) -> None:
    r = await rent_client.get("/api/v1/pm/rent/payments?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3
