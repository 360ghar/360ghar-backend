"""A SAVEPOINT release must not drop the commit flag (contract-audit M1)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import _SESSION_NEEDS_COMMIT_KEY, _session_needs_commit
from app.models.bookings import Booking
from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType
from app.models.pm_finance import RentCharge
from app.models.pm_leases import Lease
from app.models.properties import Property, Visit
from app.models.users import User
from tests.regression.conftest import act_as


async def _commit(session: AsyncSession, *objs):
    session.add_all(objs)
    await session.commit()


def _user(tag: str) -> User:
    return User(
        supabase_user_id=f"sp-{tag}",
        phone=f"+91900{abs(hash(tag)) % 10**7:07d}",
        email=f"{tag}@example.com",
        full_name=tag,
        role="user",
        is_active=True,
        is_verified=True,
    )


@pytest.mark.asyncio
async def test_listener_keeps_flag_through_savepoint(real_engine, new_session):
    """flush -> begin_nested release keeps the flag; the outer commit clears it."""
    session = new_session
    await session.execute(text("SELECT 1"))
    session.add(_user("listener"))
    await session.flush()
    assert session.sync_session.info.get(_SESSION_NEEDS_COMMIT_KEY)

    async with session.begin_nested():
        await session.execute(text("SELECT 1"))
    assert session.sync_session.info.get(_SESSION_NEEDS_COMMIT_KEY)
    assert _session_needs_commit(session)

    await session.commit()
    assert not session.sync_session.info.get(_SESSION_NEEDS_COMMIT_KEY)

    session.add(_user("listener2"))
    await session.flush()
    assert session.sync_session.info.get(_SESSION_NEEDS_COMMIT_KEY)
    await session.rollback()
    assert not session.sync_session.info.get(_SESSION_NEEDS_COMMIT_KEY)


@pytest.mark.asyncio
async def test_post_visits_is_committed(real_app, real_client, new_session):
    owner, visitor = _user("v-owner"), _user("v-visitor")
    await _commit(new_session, owner, visitor)
    prop = Property(
        title="Visit Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
        owner_id=owner.id,
    )
    await _commit(new_session, prop)
    act_as(real_app, visitor)

    when = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    resp = await real_client.post(
        "/api/v1/visits",
        json={"property_id": prop.id, "scheduled_date": when.isoformat().replace("+00:00", "Z")},
    )
    assert resp.status_code == 201, resp.text
    visit_id = resp.json()["id"]

    assert await new_session.get(Visit, visit_id) is not None
    got = await real_client.get(f"/api/v1/visits/{visit_id}")
    assert got.status_code == 200, got.text


@pytest.mark.asyncio
async def test_post_bookings_idempotency_replay_one_row(real_app, real_client, new_session):
    owner, guest = _user("b-owner"), _user("b-guest")
    await _commit(new_session, owner, guest)
    prop = Property(
        title="Stay Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.short_stay,
        base_price=30000,
        daily_rate=2000,
        max_occupancy=4,
        owner_id=owner.id,
    )
    await _commit(new_session, prop)
    act_as(real_app, guest)

    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=10)
    body = {
        "property_id": prop.id,
        "check_in_date": start.isoformat().replace("+00:00", "Z"),
        "check_out_date": (start + timedelta(days=3)).isoformat().replace("+00:00", "Z"),
        "guests": 2,
        "primary_guest_name": "Rahul Sharma",
        "primary_guest_phone": "+919876543210",
        "primary_guest_email": "rahul@example.com",
    }
    headers = {"Idempotency-Key": "regression-key-1"}
    first = await real_client.post("/api/v1/bookings", json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = await real_client.post("/api/v1/bookings", json=body, headers=headers)
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]

    count = (await new_session.execute(select(func.count()).select_from(Booking))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_pm_generate_rent_charges_is_committed(real_app, real_client, new_session):
    owner, tenant = _user("r-owner"), _user("r-tenant")
    await _commit(new_session, owner, tenant)
    prop = Property(
        title="Rent Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
        owner_id=owner.id,
        is_managed=True,
    )
    await _commit(new_session, prop)
    lease = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id,
        status=LeaseStatus.active,
        start_date=date(2025, 1, 1),
        end_date=date(2035, 12, 31),
        monthly_rent=30000,
        security_deposit=60000,
        grace_period_days=5,
        payment_due_day=5,
    )
    await _commit(new_session, lease)
    act_as(real_app, owner)

    resp = await real_client.post(
        "/api/v1/pm/rent/charges/generate",
        json={"start_month": "2026-01-01", "months": 2},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 2

    count = (await new_session.execute(select(func.count()).select_from(RentCharge))).scalar_one()
    assert count == 2
