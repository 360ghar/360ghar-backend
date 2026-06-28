"""
Sample data fixtures for testing.

Provides pre-built test data scenarios for common testing needs.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest_asyncio

from app.models.bookings import Booking
from app.models.enums import (
    BookingStatus,
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    PaymentStatus,
    PropertyPurpose,
    PropertyType,
    RentChargeStatus,
    UserRole,
)
from app.models.pm_finance import RentCharge
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Amenity, Property
from app.models.users import User
from tests.fixtures.factories import (
    AmenityFactory,
    BookingFactory,
    PropertyFactory,
    UserFactory,
)

if TYPE_CHECKING:
    from app.models.agents import Agent
    from app.models.properties import Visit
    from app.models.users import UserSwipe

# =============================================================================
# Property Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_property(db_session, test_user) -> Property:
    """
    Create a single test property owned by test_user.

    Returns:
        Property for rent in Mumbai
    """
    return await PropertyFactory.create(
        db_session,
        owner=test_user,
        title="Test Apartment",
        description="A beautiful 2BHK apartment for rent",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        monthly_rent=Decimal("50000"),
        city="Mumbai",
        locality="Andheri",
        bedrooms=2,
        bathrooms=2,
    )


@pytest_asyncio.fixture
async def test_short_stay_property(db_session, test_user) -> Property:
    """
    Create a short-stay property for booking tests.

    Returns:
        Property for short_stay with daily rate
    """
    return await PropertyFactory.create(
        db_session,
        owner=test_user,
        title="Vacation Stay Property",
        description="Perfect for short vacation stays",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.short_stay,
        daily_rate=Decimal("2000"),
        city="Mumbai",
        locality="Bandra",
        bedrooms=1,
        bathrooms=1,
    )


@pytest_asyncio.fixture
async def test_properties(db_session, test_user) -> list[Property]:
    """
    Create multiple properties for list/search tests.

    Returns:
        List of 5 properties with varied attributes
    """
    properties = []

    # Property 1: Apartment for rent
    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Modern Apartment in Andheri",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            monthly_rent=Decimal("45000"),
            city="Mumbai",
            locality="Andheri",
            latitude=19.1136,
            longitude=72.8697,
            bedrooms=2,
            bathrooms=2,
        )
    )

    # Property 2: House for buy
    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Spacious House in Bandra",
            property_type=PropertyType.house,
            purpose=PropertyPurpose.buy,
            base_price=Decimal("25000000"),
            city="Mumbai",
            locality="Bandra",
            latitude=19.0544,
            longitude=72.8406,
            bedrooms=4,
            bathrooms=3,
        )
    )

    # Property 3: Room for rent
    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Cozy Room in Powai",
            property_type=PropertyType.room,
            purpose=PropertyPurpose.rent,
            monthly_rent=Decimal("15000"),
            city="Mumbai",
            locality="Powai",
            latitude=19.1176,
            longitude=72.9060,
            bedrooms=1,
            bathrooms=1,
        )
    )

    # Property 4: Short stay apartment
    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Holiday Apartment in Colaba",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.short_stay,
            daily_rate=Decimal("3500"),
            city="Mumbai",
            locality="Colaba",
            latitude=18.9067,
            longitude=72.8147,
            bedrooms=2,
            bathrooms=1,
        )
    )

    # Property 5: Builder floor for buy
    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Builder Floor in Juhu",
            property_type=PropertyType.builder_floor,
            purpose=PropertyPurpose.buy,
            base_price=Decimal("35000000"),
            city="Mumbai",
            locality="Juhu",
            latitude=19.0989,
            longitude=72.8265,
            bedrooms=3,
            bathrooms=2,
        )
    )

    return properties


@pytest_asyncio.fixture
async def test_special_listing_properties(db_session, test_user) -> list[Property]:
    """
    Create PG, flatmate, and commercial listings for taxonomy tests.

    Returns:
        List of specialized listings that exercise expanded property types.
    """
    properties = []

    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Managed PG in Andheri",
            property_type=PropertyType.pg,
            purpose=PropertyPurpose.rent,
            monthly_rent=Decimal("18000"),
            city="Mumbai",
            locality="Andheri",
            latitude=19.1136,
            longitude=72.8697,
            bedrooms=1,
            bathrooms=1,
            max_occupancy=2,
            listing_preferences={
                "gender_preference": "female",
                "sharing_type": "shared_room",
            },
        )
    )

    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Flatmate Wanted in Powai",
            property_type=PropertyType.flatmate,
            purpose=PropertyPurpose.rent,
            monthly_rent=Decimal("22000"),
            city="Mumbai",
            locality="Powai",
            latitude=19.1176,
            longitude=72.9060,
            bedrooms=2,
            bathrooms=2,
            max_occupancy=2,
            listing_preferences={
                "gender_preference": "male",
                "sharing_type": "private_room",
            },
        )
    )

    properties.append(
        await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="Retail Shop in Bandra",
            property_type=PropertyType.shop,
            purpose=PropertyPurpose.rent,
            base_price=Decimal("125000"),
            city="Mumbai",
            locality="Bandra",
            latitude=19.0544,
            longitude=72.8406,
            bedrooms=None,
            bathrooms=1,
            area_sqft=Decimal("350"),
        )
    )

    return properties


# =============================================================================
# Booking Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_booking(
    db_session,
    test_user_2,
    test_short_stay_property,
) -> Booking:
    """
    Create a pending booking for test_user_2.

    Uses test_short_stay_property (owned by test_user).
    """
    return await BookingFactory.create(
        db_session,
        user=test_user_2,
        property_obj=test_short_stay_property,
        check_in_date=datetime.now(timezone.utc) + timedelta(days=7),
        check_out_date=datetime.now(timezone.utc) + timedelta(days=10),
        guests=2,
        booking_status=BookingStatus.pending,
    )


@pytest_asyncio.fixture
async def confirmed_booking(
    db_session,
    test_user_2,
    test_short_stay_property,
) -> Booking:
    """Create a confirmed and paid booking."""
    return await BookingFactory.create(
        db_session,
        user=test_user_2,
        property_obj=test_short_stay_property,
        check_in_date=datetime.now(timezone.utc) + timedelta(days=14),
        check_out_date=datetime.now(timezone.utc) + timedelta(days=17),
        guests=2,
        booking_status=BookingStatus.confirmed,
        payment_status=PaymentStatus.paid,
    )


@pytest_asyncio.fixture
async def test_bookings(
    db_session,
    test_user,
    test_short_stay_property,
) -> list[Booking]:
    """
    Create multiple bookings with different statuses.

    Returns:
        List of bookings: pending, confirmed, completed, cancelled
    """
    bookings = []

    # Pending booking
    bookings.append(
        await BookingFactory.create(
            db_session,
            user=test_user,
            property_obj=test_short_stay_property,
            check_in_date=datetime.now(timezone.utc) + timedelta(days=7),
            check_out_date=datetime.now(timezone.utc) + timedelta(days=10),
            booking_status=BookingStatus.pending,
        )
    )

    # Confirmed upcoming booking
    bookings.append(
        await BookingFactory.create(
            db_session,
            user=test_user,
            property_obj=test_short_stay_property,
            check_in_date=datetime.now(timezone.utc) + timedelta(days=14),
            check_out_date=datetime.now(timezone.utc) + timedelta(days=17),
            booking_status=BookingStatus.confirmed,
            payment_status=PaymentStatus.paid,
        )
    )

    # Completed past booking
    bookings.append(
        await BookingFactory.create(
            db_session,
            user=test_user,
            property_obj=test_short_stay_property,
            check_in_date=datetime.now(timezone.utc) - timedelta(days=30),
            check_out_date=datetime.now(timezone.utc) - timedelta(days=27),
            booking_status=BookingStatus.completed,
            payment_status=PaymentStatus.paid,
        )
    )

    # Cancelled booking
    bookings.append(
        await BookingFactory.create(
            db_session,
            user=test_user,
            property_obj=test_short_stay_property,
            check_in_date=datetime.now(timezone.utc) + timedelta(days=21),
            check_out_date=datetime.now(timezone.utc) + timedelta(days=24),
            booking_status=BookingStatus.cancelled,
        )
    )

    return bookings


# =============================================================================
# Amenity Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_amenities(db_session) -> list[Amenity]:
    """
    Create a set of common amenities.

    Returns:
        List of 10 amenities
    """
    amenities = []
    amenity_data = [
        ("Swimming Pool", "pool", "recreation"),
        ("Gym", "fitness", "recreation"),
        ("Parking", "car", "convenience"),
        ("24x7 Security", "shield", "safety"),
        ("Garden", "leaf", "recreation"),
        ("Club House", "home", "recreation"),
        ("Power Backup", "bolt", "convenience"),
        ("Lift", "elevator", "convenience"),
        ("Wi-Fi", "wifi", "convenience"),
        ("Air Conditioning", "snowflake", "convenience"),
    ]

    for title, icon, category in amenity_data:
        amenity = await AmenityFactory.create(
            db_session,
            title=title,
            icon=icon,
            category=category,
        )
        amenities.append(amenity)

    return amenities


# =============================================================================
# Complete Scenario Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def property_with_bookings(
    db_session,
    test_user,
    test_user_2,
) -> dict:
    """
    Create a complete scenario with property and multiple bookings.

    Returns:
        Dict with 'property', 'owner', 'guest', and 'bookings'
    """
    # Create property
    property_obj = await PropertyFactory.create(
        db_session,
        owner=test_user,
        title="Beachside Villa",
        purpose=PropertyPurpose.short_stay,
        daily_rate=Decimal("5000"),
    )

    # Create bookings by different user
    bookings = []

    # Upcoming booking
    bookings.append(
        await BookingFactory.create(
            db_session,
            user=test_user_2,
            property_obj=property_obj,
            check_in_date=datetime.now(timezone.utc) + timedelta(days=5),
            check_out_date=datetime.now(timezone.utc) + timedelta(days=8),
            booking_status=BookingStatus.confirmed,
        )
    )

    # Past booking
    bookings.append(
        await BookingFactory.create(
            db_session,
            user=test_user_2,
            property_obj=property_obj,
            check_in_date=datetime.now(timezone.utc) - timedelta(days=10),
            check_out_date=datetime.now(timezone.utc) - timedelta(days=7),
            booking_status=BookingStatus.completed,
        )
    )

    return {
        "property": property_obj,
        "owner": test_user,
        "guest": test_user_2,
        "bookings": bookings,
    }


# =============================================================================
# Property Management Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_tenant_user(db_session) -> User:
    """
    Create a test user with tenant role for PM testing.

    Returns:
        User object representing a tenant
    """
    return await UserFactory.create(
        db_session,
        email="tenant@example.com",
        phone="+919876543299",
        full_name="Test Tenant",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )


@pytest_asyncio.fixture
async def test_managed_property(db_session, test_user) -> Property:
    """
    Create a managed property for PM testing.

    Returns:
        Property marked as managed for rent collection
    """
    return await PropertyFactory.create(
        db_session,
        owner=test_user,
        title="Managed Rental Apartment",
        description="A managed 2BHK apartment for rent",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        monthly_rent=Decimal("50000"),
        city="Mumbai",
        locality="Andheri",
        bedrooms=2,
        bathrooms=2,
        is_managed=True,
    )


@pytest_asyncio.fixture
async def test_active_lease(
    db_session,
    test_user,
    test_tenant_user,
    test_managed_property,
) -> Lease:
    """
    Create an active lease for PM testing.

    Returns:
        Active lease between test_user (owner) and test_tenant_user
    """
    today = date.today()
    lease = Lease(
        property_id=test_managed_property.id,
        owner_id=test_user.id,
        tenant_user_id=test_tenant_user.id,
        tenant_name=test_tenant_user.full_name,
        tenant_phone=test_tenant_user.phone,
        tenant_email=test_tenant_user.email,
        status=LeaseStatus.active,
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=335),
        monthly_rent=50000.0,
        security_deposit=100000.0,
        late_fee_amount=500.0,
        grace_period_days=5,
        payment_due_day=1,
    )
    db_session.add(lease)
    await db_session.flush()
    await db_session.refresh(lease)
    return lease


@pytest_asyncio.fixture
async def test_rent_charge(
    db_session,
    test_user,
    test_tenant_user,
    test_managed_property,
    test_active_lease,
) -> RentCharge:
    """
    Create a rent charge for the current month.

    Returns:
        RentCharge for testing payment recording
    """
    today = date.today()
    billing_month = today.replace(day=1)
    charge = RentCharge(
        lease_id=test_active_lease.id,
        property_id=test_managed_property.id,
        owner_id=test_user.id,
        tenant_user_id=test_tenant_user.id,
        billing_month=billing_month,
        period_start=billing_month,
        period_end=(billing_month + timedelta(days=32)).replace(day=1) - timedelta(days=1),
        due_date=billing_month.replace(day=5),
        amount_due=50000.0,
        status=RentChargeStatus.pending,
    )
    db_session.add(charge)
    await db_session.flush()
    await db_session.refresh(charge)
    return charge


@pytest_asyncio.fixture
async def test_rent_charges(
    db_session,
    test_user,
    test_tenant_user,
    test_managed_property,
    test_active_lease,
) -> list[RentCharge]:
    """
    Create multiple rent charges for testing history.

    Returns:
        List of RentCharge objects spanning 3 months
    """
    charges = []
    today = date.today()

    for i in range(3):
        billing_month = (today - timedelta(days=30 * i)).replace(day=1)
        charge = RentCharge(
            lease_id=test_active_lease.id,
            property_id=test_managed_property.id,
            owner_id=test_user.id,
            tenant_user_id=test_tenant_user.id,
            billing_month=billing_month,
            period_start=billing_month,
            period_end=(billing_month + timedelta(days=32)).replace(day=1) - timedelta(days=1),
            due_date=billing_month.replace(day=5),
            amount_due=50000.0,
            status=RentChargeStatus.paid if i > 0 else RentChargeStatus.pending,
        )
        db_session.add(charge)
        await db_session.flush()
        await db_session.refresh(charge)
        charges.append(charge)

    return charges


@pytest_asyncio.fixture
async def test_overdue_rent_charge(
    db_session,
    test_user,
    test_tenant_user,
    test_managed_property,
    test_active_lease,
) -> RentCharge:
    """
    Create an overdue rent charge for testing late fees.

    Returns:
        RentCharge that is past due
    """
    today = date.today()
    billing_month = (today - timedelta(days=45)).replace(day=1)
    charge = RentCharge(
        lease_id=test_active_lease.id,
        property_id=test_managed_property.id,
        owner_id=test_user.id,
        tenant_user_id=test_tenant_user.id,
        billing_month=billing_month,
        period_start=billing_month,
        period_end=(billing_month + timedelta(days=32)).replace(day=1) - timedelta(days=1),
        due_date=billing_month.replace(day=5),
        amount_due=50000.0,
        status=RentChargeStatus.overdue,
    )
    db_session.add(charge)
    await db_session.flush()
    await db_session.refresh(charge)
    return charge


@pytest_asyncio.fixture
async def test_maintenance_request(
    db_session,
    test_user,
    test_tenant_user,
    test_managed_property,
    test_active_lease,
) -> MaintenanceRequest:
    """
    Create a maintenance request for testing.

    Returns:
        MaintenanceRequest in open status
    """
    request = MaintenanceRequest(
        property_id=test_managed_property.id,
        lease_id=test_active_lease.id,
        owner_id=test_user.id,
        tenant_user_id=test_tenant_user.id,
        category=MaintenanceCategory.plumbing,
        urgency=MaintenanceUrgency.medium,
        title="Leaky faucet in kitchen",
        description="The kitchen faucet has been dripping for a few days",
        request_status=MaintenanceRequestStatus.open,
    )
    db_session.add(request)
    await db_session.flush()
    await db_session.refresh(request)
    return request


@pytest_asyncio.fixture
async def test_maintenance_requests(
    db_session,
    test_user,
    test_tenant_user,
    test_managed_property,
    test_active_lease,
) -> list[MaintenanceRequest]:
    """
    Create multiple maintenance requests with different statuses.

    Returns:
        List of MaintenanceRequest objects
    """
    requests = []
    categories = [
        (MaintenanceCategory.plumbing, MaintenanceUrgency.medium, "Leaky faucet", MaintenanceRequestStatus.open),
        (MaintenanceCategory.electrical, MaintenanceUrgency.high, "Broken socket", MaintenanceRequestStatus.in_progress),
        (MaintenanceCategory.hvac, MaintenanceUrgency.low, "AC servicing", MaintenanceRequestStatus.resolved),
    ]

    for cat, urg, title, status in categories:
        request = MaintenanceRequest(
            property_id=test_managed_property.id,
            lease_id=test_active_lease.id,
            owner_id=test_user.id,
            tenant_user_id=test_tenant_user.id,
            category=cat,
            urgency=urg,
            title=title,
            description=f"Description for {title}",
            request_status=status,
        )
        db_session.add(request)
        await db_session.flush()
        await db_session.refresh(request)
        requests.append(request)

    return requests


# =============================================================================
# Agent Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_agent(db_session, test_agent_user) -> Agent:
    """
    Create a test agent.

    Returns:
        Agent instance
    """
    from tests.fixtures.factories import AgentFactory

    return await AgentFactory.create(
        db_session,
        name="Test Agent",
        description="Test Real Estate Agent",
        agent_type="general",
        experience_level="intermediate",
        is_active=True,
        is_available=True,
    )


@pytest_asyncio.fixture
async def test_agents(db_session, test_agent_user) -> list[Agent]:
    """
    Create multiple test agents.

    Returns:
        List of 3 agents
    """
    from tests.fixtures.factories import AgentFactory

    agents = []

    # Create first agent
    agents.append(await AgentFactory.create(
        db_session,
        name="First Agent",
        description="First Agency Agent",
        agent_type="general",
        experience_level="intermediate",
        is_active=True,
        is_available=True,
    ))

    # Create additional agents
    for i in range(2):
        agents.append(await AgentFactory.create(
            db_session,
            name=f"Agent {i+2}",
            description=f"Agency {i+2} Agent",
            agent_type="specialist" if i % 2 == 0 else "senior",
            experience_level="expert" if i % 2 == 0 else "beginner",
            is_active=True,
            is_available=i % 2 == 0,  # Alternate availability
        ))

    return agents


@pytest_asyncio.fixture
async def test_user_with_agent(db_session, test_user, test_agent) -> User:
    """
    Create a test user with an assigned agent.

    Returns:
        User with agent_id set
    """
    test_user.agent_id = test_agent.id
    await db_session.flush()
    await db_session.refresh(test_user)
    return test_user


# =============================================================================
# Visit Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_visit(db_session, test_user, test_property, test_agent) -> Visit:
    """
    Create a test visit.

    Returns:
        Visit scheduled for test_user
    """
    from app.models.enums import VisitStatus
    from tests.fixtures.factories import VisitFactory

    return await VisitFactory.create(
        db_session,
        user=test_user,
        property_obj=test_property,
        agent_id=test_agent.id,
        scheduled_date=datetime.now(timezone.utc) + timedelta(days=3),
        status=VisitStatus.scheduled,
    )


@pytest_asyncio.fixture
async def test_visits(db_session, test_user, test_property, test_agent) -> list[Visit]:
    """
    Create multiple test visits.

    Returns:
        List of visits with different statuses
    """
    from app.models.enums import VisitStatus
    from tests.fixtures.factories import VisitFactory

    visits = []
    statuses = [
        (VisitStatus.scheduled, 3),
        (VisitStatus.confirmed, 5),
        (VisitStatus.completed, -10),  # Past visit
    ]

    for status, days_offset in statuses:
        visits.append(await VisitFactory.create(
            db_session,
            user=test_user,
            property_obj=test_property,
            agent_id=test_agent.id,
            scheduled_date=datetime.now(timezone.utc) + timedelta(days=days_offset),
            status=status,
        ))

    return visits


@pytest_asyncio.fixture
async def cancelled_visit(db_session, test_user, test_property, test_agent) -> Visit:
    """
    Create a cancelled visit.

    Returns:
        Visit with cancelled status
    """
    from app.models.enums import VisitStatus
    from tests.fixtures.factories import VisitFactory

    return await VisitFactory.create(
        db_session,
        user=test_user,
        property_obj=test_property,
        agent_id=test_agent.id,
        scheduled_date=datetime.now(timezone.utc) + timedelta(days=7),
        status=VisitStatus.cancelled,
    )


# =============================================================================
# Swipe Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_swipe(db_session, test_user, test_property) -> UserSwipe:
    """
    Create a test swipe.

    Returns:
        UserSwipe for test_user on test_property
    """
    from tests.fixtures.factories import SwipeFactory

    return await SwipeFactory.create(
        db_session,
        user=test_user,
        property_obj=test_property,
        is_liked=True,
    )


@pytest_asyncio.fixture
async def test_swipes(db_session, test_user, test_properties) -> list[UserSwipe]:
    """
    Create multiple test swipes.

    Returns:
        List of swipes on test_properties
    """
    from tests.fixtures.factories import SwipeFactory

    swipes = []
    for i, prop in enumerate(test_properties):
        swipes.append(await SwipeFactory.create(
            db_session,
            user=test_user,
            property_obj=prop,
            is_liked=i % 2 == 0,  # Alternate likes/dislikes
        ))

    return swipes


# =============================================================================
# Property with Location Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_property_with_location(db_session, test_user) -> Property:
    """
    Create a property with specific location data.

    Returns:
        Property with lat/lng for Mumbai
    """
    return await PropertyFactory.create(
        db_session,
        owner=test_user,
        title="Property with Location",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        monthly_rent=Decimal("45000"),
        city="Mumbai",
        locality="Andheri",
        latitude=19.1136,
        longitude=72.8697,
    )


@pytest_asyncio.fixture
async def test_properties_with_locations(db_session, test_user) -> list[Property]:
    """
    Create multiple properties with varied locations.

    Returns:
        List of properties in different Mumbai localities
    """
    locations = [
        ("Andheri", 19.1136, 72.8697),
        ("Bandra", 19.0544, 72.8406),
        ("Powai", 19.1176, 72.9060),
        ("Colaba", 18.9067, 72.8147),
    ]

    properties = []
    for locality, lat, lng in locations:
        properties.append(await PropertyFactory.create(
            db_session,
            owner=test_user,
            title=f"Property in {locality}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            monthly_rent=Decimal("45000"),
            city="Mumbai",
            locality=locality,
            latitude=lat,
            longitude=lng,
        ))

    return properties


# =============================================================================
# Lease Fixtures (Aliases)
# =============================================================================

@pytest_asyncio.fixture
async def test_lease(test_active_lease) -> Lease:
    """Alias for test_active_lease for convenience."""
    return test_active_lease


@pytest_asyncio.fixture
async def test_leases(
    db_session,
    test_user,
    test_tenant_user,
    test_managed_property,
) -> list[Lease]:
    """
    Create multiple leases with different statuses.

    Returns:
        List of leases
    """
    from tests.fixtures.factories import PropertyFactory

    leases = []
    today = date.today()
    statuses = [
        (LeaseStatus.active, -30, 335),
        (LeaseStatus.draft, 0, 365),
        (LeaseStatus.expired, -400, -35),
    ]

    for status, start_offset, end_offset in statuses:
        # Create a new managed property for each lease
        prop = await PropertyFactory.create(
            db_session,
            owner=test_user,
            title=f"Lease Property {status.value}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            monthly_rent=Decimal("50000"),
            is_managed=True,
        )

        lease = Lease(
            property_id=prop.id,
            owner_id=test_user.id,
            tenant_user_id=test_tenant_user.id,
            tenant_name=test_tenant_user.full_name,
            status=status,
            start_date=today + timedelta(days=start_offset),
            end_date=today + timedelta(days=end_offset),
            monthly_rent=50000.0,
            security_deposit=100000.0,
        )
        db_session.add(lease)
        await db_session.flush()
        await db_session.refresh(lease)
        leases.append(lease)

    return leases
