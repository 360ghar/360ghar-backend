from datetime import date

import pytest
from sqlalchemy import select

from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType, RentChargeStatus
from app.models.pm_finance import RentCharge
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User
from app.services.pm_rent import generate_rent_charges, record_rent_payment


@pytest.mark.asyncio
async def test_generate_rent_charges_idempotent_and_payment_status(db_session):
    owner = User(
        supabase_user_id="owner-supa-2",
        phone="+944444444444",
        full_name="Owner 2",
        role="user",
        is_active=True,
        is_verified=True,
    )
    tenant = User(
        supabase_user_id="tenant-supa-2",
        phone="+955555555555",
        full_name="Tenant 2",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([owner, tenant])
    await db_session.flush()

    prop = Property(
        title="Rent Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
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
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        monthly_rent=30000,
        security_deposit=60000,
        grace_period_days=5,
        payment_due_day=5,
    )
    db_session.add(lease)
    await db_session.flush()

    res1 = await generate_rent_charges(
        db_session,
        actor=owner,
        owner_id=owner.id,
        start_month=date(2025, 1, 1),
        months=1,
    )
    assert res1["created"] == 1

    res2 = await generate_rent_charges(
        db_session,
        actor=owner,
        owner_id=owner.id,
        start_month=date(2025, 1, 1),
        months=1,
    )
    assert res2["created"] == 0
    assert res2["skipped"] == 1

    charge = (await db_session.execute(select(RentCharge))).scalars().first()
    assert charge is not None
    assert charge.status == RentChargeStatus.pending

    # Partial payment -> partial/overdue depending on due_date vs today; we assert non-paid
    await record_rent_payment(
        db_session,
        actor=owner,
        charge_id=charge.id,
        amount_paid=10000,
    )
    await db_session.refresh(charge)
    assert charge.status in {RentChargeStatus.partial, RentChargeStatus.overdue, RentChargeStatus.pending}

    # Pay the remaining 20000 -> paid
    await record_rent_payment(
        db_session,
        actor=tenant,
        charge_id=charge.id,
        amount_paid=20000,
    )
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.paid
