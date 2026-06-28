"""
Factory fixtures for generating test data.

Uses Factory Boy pattern for creating consistent test entities.
These factories can be used directly or through pytest fixtures.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent
from app.models.bookings import Booking
from app.models.enums import (
    BookingStatus,
    PaymentStatus,
    PropertyPurpose,
    PropertyStatus,
    PropertyType,
    UserRole,
    VisitStatus,
)
from app.models.properties import Amenity, Property, Visit
from app.models.users import User, UserSwipe

# =============================================================================
# Helper Functions
# =============================================================================

def random_phone() -> str:
    """Generate a random Indian phone number."""
    return f"+91{random.randint(9000000000, 9999999999)}"


def random_email(prefix: str = "user") -> str:
    """Generate a random email address."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"


def random_price(min_val: int = 10000, max_val: int = 10000000) -> Decimal:
    """Generate a random price."""
    return Decimal(str(random.randint(min_val, max_val)))


def random_coordinates_mumbai() -> tuple[float, float]:
    """Generate random coordinates within Mumbai area."""
    lat = 18.9 + random.random() * 0.3  # ~18.9 to 19.2
    lng = 72.8 + random.random() * 0.2  # ~72.8 to 73.0
    return round(lat, 6), round(lng, 6)


# =============================================================================
# Factory Classes
# =============================================================================

class UserFactory:
    """Factory for creating User instances."""

    @staticmethod
    def build(
        supabase_user_id: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        full_name: str = "Test User",
        role: str = UserRole.user.value,
        is_active: bool = True,
        is_verified: bool = True,
        **kwargs,
    ) -> User:
        """Build a User instance without persisting."""
        return User(
            supabase_user_id=supabase_user_id or str(uuid.uuid4()),
            email=email or random_email(),
            phone=phone or random_phone(),
            full_name=full_name,
            role=role,
            is_active=is_active,
            is_verified=is_verified,
            preferences=kwargs.get("preferences", {}),
            notification_settings=kwargs.get("notification_settings", {}),
            privacy_settings=kwargs.get("privacy_settings", {}),
            **{k: v for k, v in kwargs.items() if k not in [
                "preferences", "notification_settings", "privacy_settings"
            ]},
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        **kwargs,
    ) -> User:
        """Create and persist a User instance."""
        user = UserFactory.build(**kwargs)
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user


class PropertyFactory:
    """Factory for creating Property instances."""

    @staticmethod
    def build(
        owner_id: int | None = None,
        title: str = "Test Property",
        description: str = "A beautiful test property",
        property_type: PropertyType = PropertyType.apartment,
        purpose: PropertyPurpose = PropertyPurpose.rent,
        status: PropertyStatus = PropertyStatus.available,
        base_price: Decimal | None = None,
        monthly_rent: Decimal | None = None,
        daily_rate: Decimal | None = None,
        city: str = "Mumbai",
        locality: str = "Andheri",
        **kwargs,
    ) -> Property:
        """Build a Property instance without persisting."""
        lat, lng = random_coordinates_mumbai()

        return Property(
            owner_id=owner_id,
            title=title,
            description=description,
            property_type=property_type,
            purpose=purpose,
            status=status,
            base_price=base_price or random_price(500000, 50000000),
            monthly_rent=monthly_rent or random_price(10000, 100000),
            daily_rate=daily_rate or random_price(1000, 10000),
            city=city,
            locality=locality,
            full_address=kwargs.get(
                "full_address", f"{locality}, {city}, Maharashtra, India"
            ),
            pincode=kwargs.get("pincode", str(random.randint(400001, 400099))),
            state=kwargs.get("state", "Maharashtra"),
            country=kwargs.get("country", "India"),
            latitude=kwargs.get("latitude", lat),
            longitude=kwargs.get("longitude", lng),
            bedrooms=kwargs.get("bedrooms", random.randint(1, 4)),
            bathrooms=kwargs.get("bathrooms", random.randint(1, 3)),
            area_sqft=kwargs.get("area_sqft", Decimal(str(random.randint(500, 3000)))),
            is_available=kwargs.get("is_available", True),
            is_managed=kwargs.get("is_managed", False),
            **{k: v for k, v in kwargs.items() if k not in [
                "full_address", "pincode", "state", "country", "latitude",
                "longitude", "bedrooms", "bathrooms", "area_sqft",
                "is_available", "is_managed"
            ]},
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        owner: User | None = None,
        owner_id: int | None = None,
        **kwargs,
    ) -> Property:
        """Create and persist a Property instance."""
        if owner is not None:
            owner_id = owner.id
        prop = PropertyFactory.build(owner_id=owner_id, **kwargs)
        db.add(prop)
        await db.flush()
        await db.refresh(prop)
        return prop


class BookingFactory:
    """Factory for creating Booking instances."""

    @staticmethod
    def build(
        user_id: int | None = None,
        property_id: int | None = None,
        check_in_date: datetime | None = None,
        check_out_date: datetime | None = None,
        guests: int = 2,
        booking_status: BookingStatus = BookingStatus.pending,
        payment_status: PaymentStatus = PaymentStatus.pending,
        **kwargs,
    ) -> Booking:
        """Build a Booking instance without persisting."""
        if check_in_date is None:
            check_in_date = datetime.now(timezone.utc) + timedelta(days=7)
        if check_out_date is None:
            check_out_date = check_in_date + timedelta(days=3)

        nights = (check_out_date - check_in_date).days
        base_amount = Decimal("1500") * nights
        taxes_amount = base_amount * Decimal("0.18")
        service_charges = base_amount * Decimal("0.05")
        total_amount = base_amount + taxes_amount + service_charges

        return Booking(
            user_id=user_id,
            property_id=property_id,
            booking_reference=kwargs.get(
                "booking_reference", f"BK{uuid.uuid4().hex[:8].upper()}"
            ),
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            guests=guests,
            nights=nights,
            base_amount=kwargs.get("base_amount", base_amount),
            taxes_amount=kwargs.get("taxes_amount", taxes_amount),
            service_charges=kwargs.get("service_charges", service_charges),
            discount_amount=kwargs.get("discount_amount", Decimal("0")),
            total_amount=kwargs.get("total_amount", total_amount),
            booking_status=booking_status.value if isinstance(
                booking_status, BookingStatus
            ) else booking_status,
            payment_status=payment_status.value if isinstance(
                payment_status, PaymentStatus
            ) else payment_status,
            # Required guest information fields
            primary_guest_name=kwargs.get("primary_guest_name", "Test Guest"),
            primary_guest_phone=kwargs.get("primary_guest_phone", "+919876543210"),
            primary_guest_email=kwargs.get("primary_guest_email", "guest@test.com"),
            **{k: v for k, v in kwargs.items() if k not in [
                "booking_reference", "base_amount", "taxes_amount",
                "service_charges", "discount_amount", "total_amount",
                "primary_guest_name", "primary_guest_phone", "primary_guest_email"
            ]},
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        user: User | None = None,
        property_obj: Property | None = None,
        **kwargs,
    ) -> Booking:
        """Create and persist a Booking instance."""
        user_id = kwargs.pop("user_id", None) or (user.id if user else None)
        property_id = kwargs.pop("property_id", None) or (
            property_obj.id if property_obj else None
        )

        booking = BookingFactory.build(
            user_id=user_id,
            property_id=property_id,
            **kwargs,
        )
        db.add(booking)
        await db.flush()
        await db.refresh(booking)
        return booking


class VisitFactory:
    """Factory for creating Visit instances."""

    @staticmethod
    def build(
        user_id: int | None = None,
        property_id: int | None = None,
        agent_id: int | None = None,
        scheduled_date: datetime | None = None,
        status: VisitStatus = VisitStatus.scheduled,
        **kwargs,
    ) -> Visit:
        """Build a Visit instance without persisting."""
        if scheduled_date is None:
            scheduled_date = datetime.now() + timedelta(days=3)

        return Visit(
            user_id=user_id,
            property_id=property_id,
            agent_id=agent_id,
            scheduled_date=scheduled_date,
            status=status.value if isinstance(status, VisitStatus) else status,
            visit_notes=kwargs.get("visit_notes", "Test visit notes"),
            special_requirements=kwargs.get("special_requirements"),
            **{k: v for k, v in kwargs.items() if k not in [
                "visit_notes", "special_requirements"
            ]},
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        user: User | None = None,
        property_obj: Property | None = None,
        **kwargs,
    ) -> Visit:
        """Create and persist a Visit instance."""
        user_id = kwargs.pop("user_id", None) or (user.id if user else None)
        property_id = kwargs.pop("property_id", None) or (
            property_obj.id if property_obj else None
        )

        visit = VisitFactory.build(
            user_id=user_id,
            property_id=property_id,
            **kwargs,
        )
        db.add(visit)
        await db.flush()
        await db.refresh(visit)
        return visit


class AgentFactory:
    """Factory for creating Agent instances."""

    @staticmethod
    def build(
        name: str = "Test Agent",
        contact_number: str | None = None,
        description: str = "Experienced real estate agent",
        agent_type: str = "general",
        experience_level: str = "intermediate",
        is_active: bool = True,
        is_available: bool = True,
        **kwargs,
    ) -> Agent:
        """Build an Agent instance without persisting."""
        from app.models.enums import AgentType, ExperienceLevel

        return Agent(
            name=name,
            contact_number=contact_number or random_phone(),
            description=description,
            agent_type=AgentType(agent_type) if isinstance(agent_type, str) else agent_type,
            experience_level=ExperienceLevel(experience_level) if isinstance(experience_level, str) else experience_level,
            is_active=is_active,
            is_available=is_available,
            languages=kwargs.get("languages", ["English", "Hindi"]),
            total_users_assigned=kwargs.get("total_users_assigned", 0),
            user_satisfaction_rating=kwargs.get("user_satisfaction_rating", 4.5),
            **{k: v for k, v in kwargs.items() if k not in [
                "languages", "total_users_assigned", "user_satisfaction_rating"
            ]},
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        **kwargs,
    ) -> Agent:
        """Create and persist an Agent instance."""
        agent = AgentFactory.build(**kwargs)
        db.add(agent)
        await db.flush()
        await db.refresh(agent)
        return agent


class SwipeFactory:
    """Factory for creating UserSwipe instances."""

    @staticmethod
    def build(
        user_id: int | None = None,
        property_id: int | None = None,
        is_liked: bool = True,
    ) -> UserSwipe:
        """Build a UserSwipe instance without persisting."""
        return UserSwipe(
            user_id=user_id,
            property_id=property_id,
            is_liked=is_liked,
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        user: User | None = None,
        property_obj: Property | None = None,
        is_liked: bool = True,
    ) -> UserSwipe:
        """Create and persist a UserSwipe instance."""
        user_id = user.id if user else None
        property_id = property_obj.id if property_obj else None

        swipe = SwipeFactory.build(
            user_id=user_id,
            property_id=property_id,
            is_liked=is_liked,
        )
        db.add(swipe)
        await db.flush()
        await db.refresh(swipe)
        return swipe


class AmenityFactory:
    """Factory for creating Amenity instances."""

    AMENITY_NAMES = [
        "Swimming Pool", "Gym", "Parking", "Security", "Garden",
        "Club House", "Power Backup", "Lift", "Wi-Fi", "AC",
    ]

    @staticmethod
    def build(
        title: str | None = None,
        icon: str = "star",
        category: str = "recreation",
    ) -> Amenity:
        """Build an Amenity instance without persisting."""
        return Amenity(
            title=title or random.choice(AmenityFactory.AMENITY_NAMES),
            icon=icon,
            category=category,
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        **kwargs,
    ) -> Amenity:
        """Create and persist an Amenity instance."""
        amenity = AmenityFactory.build(**kwargs)
        db.add(amenity)
        await db.flush()
        await db.refresh(amenity)
        return amenity


# =============================================================================
# Pytest Fixtures
# =============================================================================

@pytest.fixture
def user_factory():
    """Provide UserFactory for custom user creation."""
    return UserFactory


@pytest.fixture
def property_factory():
    """Provide PropertyFactory for custom property creation."""
    return PropertyFactory


@pytest.fixture
def booking_factory():
    """Provide BookingFactory for custom booking creation."""
    return BookingFactory


@pytest.fixture
def visit_factory():
    """Provide VisitFactory for custom visit creation."""
    return VisitFactory


@pytest.fixture
def agent_factory():
    """Provide AgentFactory for custom agent creation."""
    return AgentFactory


@pytest.fixture
def swipe_factory():
    """Provide SwipeFactory for custom swipe creation."""
    return SwipeFactory


@pytest.fixture
def amenity_factory():
    """Provide AmenityFactory for custom amenity creation."""
    return AmenityFactory
