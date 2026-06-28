from datetime import date

import pytest

from app.models.agents import Agent
from app.models.enums import (
    AgentType,
    ExperienceLevel,
    LeaseStatus,
    PropertyPurpose,
    PropertyType,
)
from app.models.pm_leases import Lease
from app.models.properties import Amenity, Property, PropertyAmenity
from app.models.users import User
from app.services.pm_authz import assert_can_access_property


@pytest.mark.asyncio
async def test_pm_authz_owner_agent_tenant_property_access(db_session):
    agent_profile = Agent(
        name="RM 1",
        contact_number="9999999999",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.beginner,
        is_active=True,
        is_available=True,
    )
    db_session.add(agent_profile)
    await db_session.flush()

    owner = User(
        supabase_user_id="owner-supa",
        phone="+911111111111",
        full_name="Owner",
        role="user",
        agent_id=agent_profile.id,
        is_active=True,
        is_verified=True,
    )
    rm_user = User(
        supabase_user_id="rm-supa",
        phone="+922222222222",
        full_name="RM",
        role="agent",
        agent_id=agent_profile.id,
        is_active=True,
        is_verified=True,
    )
    tenant = User(
        supabase_user_id="tenant-supa",
        phone="+933333333333",
        full_name="Tenant",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([owner, rm_user, tenant])
    await db_session.flush()

    prop = Property(
        title="Test PM Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=25000,
        owner_id=owner.id,
        is_managed=True,
    )
    db_session.add(prop)
    await db_session.flush()

    amenity = Amenity(title="Gym", icon="dumbbell", category="fitness", is_active=True)
    db_session.add(amenity)
    await db_session.flush()
    prop_amenity = PropertyAmenity(property_id=prop.id, amenity_id=amenity.id)
    db_session.add(prop_amenity)
    await db_session.flush()

    lease = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id,
        status=LeaseStatus.active,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        monthly_rent=25000,
        security_deposit=50000,
        grace_period_days=5,
        payment_due_day=1,
    )
    db_session.add(lease)
    await db_session.flush()

    # Owner can access
    p1 = await assert_can_access_property(db_session, actor=owner, property_id=prop.id)
    assert p1.id == prop.id
    assert len(p1.property_amenities) == 1
    assert p1.property_amenities[0].amenity.title == "Gym"

    # RM can access (via owner.agent_id match)
    p2 = await assert_can_access_property(db_session, actor=rm_user, property_id=prop.id)
    assert p2.id == prop.id

    # Tenant can access only when allow_tenant=True
    p3 = await assert_can_access_property(
        db_session, actor=tenant, property_id=prop.id, allow_tenant=True
    )
    assert p3.id == prop.id

    from app.core.exceptions import InsufficientPermissionsError

    with pytest.raises(InsufficientPermissionsError):
        await assert_can_access_property(db_session, actor=tenant, property_id=prop.id, allow_tenant=False)
