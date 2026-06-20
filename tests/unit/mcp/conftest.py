"""Shared fixtures for MCP unit tests.

Provides reusable factories and mock helpers for testing MCP tools
without a real database. All factories return ``SimpleNamespace`` objects
or ``AsyncMock`` instances that match the shapes expected by tool functions.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.mcp.apps_sdk import AuthRequiredError

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def raise_auth_required(**kwargs: Any) -> None:
    """Side effect that raises ``AuthRequiredError``.

    Matches the signature of ``_require_auth(action=, message=, scope=)``.
    """
    raise AuthRequiredError(
        message=kwargs.get("message", "Authentication required"),
        www_authenticate='Bearer error="insufficient_scope"',
    )


# ---------------------------------------------------------------------------
# User factory
# ---------------------------------------------------------------------------


def make_user(
    user_id: int = 10,
    role: str = "user",
    full_name: str = "Owner User",
    agent_id: int | None = None,
) -> SimpleNamespace:
    """Create a mock user object matching the User ORM shape."""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=user_id,
        role=role,
        supabase_user_id=f"user-{user_id}",
        phone="+919876543210",
        full_name=full_name,
        email=f"user{user_id}@example.com",
        is_active=True,
        is_verified=True,
        agent_id=agent_id,
        created_at=now,
        updated_at=now,
    )


def make_agent(user_id: int = 20, agent_id: int = 5) -> SimpleNamespace:
    """Create a mock agent user."""
    return make_user(user_id=user_id, role="agent", full_name="Agent User", agent_id=agent_id)


def make_admin(user_id: int = 1) -> SimpleNamespace:
    """Create a mock admin user."""
    return make_user(user_id=user_id, role="admin", full_name="Admin User")


# ---------------------------------------------------------------------------
# Property factory
# ---------------------------------------------------------------------------


def make_property(
    property_id: int = 1,
    title: str = "Test Property",
    city: str = "Delhi",
    locality: str = "Karol Bagh",
    purpose: str = "buy",
    property_type: str = "apartment",
    base_price: float = 5000000,
    monthly_rent: float | None = None,
    bedrooms: int = 3,
    bathrooms: int = 2,
    area_sqft: float = 1200,
    is_available: bool = True,
    owner_id: int = 10,
) -> SimpleNamespace:
    """Create a mock property object matching the Property ORM shape."""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=property_id,
        title=title,
        description="A beautiful property",
        city=city,
        locality=locality,
        full_address=f"{locality}, {city}",
        purpose=purpose,
        property_type=property_type,
        base_price=base_price,
        monthly_rent=monthly_rent,
        daily_rate=None,
        security_deposit=None,
        maintenance_charges=None,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        balconies=1,
        area_sqft=area_sqft,
        parking_spaces=1,
        floor_number=2,
        total_floors=10,
        max_occupancy=5,
        is_available=is_available,
        owner_id=owner_id,
        owner_name="Owner User",
        owner_contact="+919876543210",
        images=[],
        property_amenities=[],
        amenities=[],
        latitude=None,
        longitude=None,
        pincode="110005",
        state="Delhi",
        main_image_url=None,
        like_count=5,
        view_count=100,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Booking factory
# ---------------------------------------------------------------------------


def make_booking(
    booking_id: int = 1,
    property_id: int = 1,
    user_id: int = 10,
    status: str = "confirmed",
    check_in: str = "2026-07-01",
    check_out: str = "2026-07-05",
    guests: int = 2,
) -> SimpleNamespace:
    """Create a mock booking object."""
    return SimpleNamespace(
        id=booking_id,
        property_id=property_id,
        user_id=user_id,
        booking_status=status,
        check_in_date=check_in,
        check_out_date=check_out,
        guests=guests,
        special_requests=None,
        base_amount=8000,
        tax_amount=1440,
        total_amount=9440,
        created_at=datetime.now(timezone.utc),
        property=make_property(property_id=property_id),
    )


# ---------------------------------------------------------------------------
# Lease factory
# ---------------------------------------------------------------------------


def make_lease(
    lease_id: int = 1,
    property_id: int = 1,
    tenant_user_id: int = 10,
    monthly_rent: float = 25000,
    status: str = "active",
    start_date: str = "2026-01-01",
    end_date: str = "2026-12-31",
) -> SimpleNamespace:
    """Create a mock lease object."""
    return SimpleNamespace(
        id=lease_id,
        property_id=property_id,
        tenant_user_id=tenant_user_id,
        monthly_rent=monthly_rent,
        security_deposit=50000,
        payment_due_day=1,
        grace_period_days=5,
        status=status,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
        rent_paid_through=None,
        termination_date=None,
        termination_reason=None,
        created_at=datetime.now(timezone.utc),
        property=make_property(property_id=property_id),
        tenant_user=make_user(user_id=tenant_user_id, full_name="Tenant User"),
    )


# ---------------------------------------------------------------------------
# Maintenance request factory
# ---------------------------------------------------------------------------


def make_maintenance_request(
    request_id: int = 1,
    property_id: int = 1,
    lease_id: int = 1,
    title: str = "Broken pipe",
    category: str = "plumbing",
    status: str = "open",
    urgency: str = "medium",
) -> SimpleNamespace:
    """Create a mock maintenance request."""
    return SimpleNamespace(
        id=request_id,
        property_id=property_id,
        lease_id=lease_id,
        title=title,
        description="Description of the issue",
        category=category,
        urgency=urgency,
        status=status,
        scheduled_date=None,
        estimated_cost=None,
        actual_cost=None,
        resolution_notes=None,
        vendor_name=None,
        vendor_contact=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Rent charge factory
# ---------------------------------------------------------------------------


def make_rent_charge(
    charge_id: int = 1,
    lease_id: int = 1,
    amount_due: float = 25000,
    amount_paid: float = 0,
    status: str = "pending",
) -> SimpleNamespace:
    """Create a mock rent charge."""
    return SimpleNamespace(
        id=charge_id,
        lease_id=lease_id,
        billing_month=date(2026, 6, 1),
        due_date=date(2026, 6, 5),
        amount_due=amount_due,
        amount_paid=amount_paid,
        status=status,
        late_fee=0,
    )


# ---------------------------------------------------------------------------
# DB / session helpers
# ---------------------------------------------------------------------------


async def async_gen_db(db: Any) -> Any:
    """Async generator that yields db once, mimicking ``get_db()``."""
    yield db


class SessionContext:
    """Context manager matching ``AsyncSessionLocal()`` pattern."""

    def __init__(self, db: Any):
        self.db = db

    async def __aenter__(self) -> Any:
        return self.db

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> AsyncMock:
    """Provide a fresh ``AsyncMock`` database session."""
    return AsyncMock()


@pytest.fixture
def user() -> SimpleNamespace:
    """Provide a default mock user."""
    return make_user()


@pytest.fixture
def agent() -> SimpleNamespace:
    """Provide a mock agent user."""
    return make_agent()


@pytest.fixture
def admin() -> SimpleNamespace:
    """Provide a mock admin user."""
    return make_admin()


@pytest.fixture
def property_obj() -> SimpleNamespace:
    """Provide a mock property."""
    return make_property()


@pytest.fixture
def booking_obj() -> SimpleNamespace:
    """Provide a mock booking."""
    return make_booking()
