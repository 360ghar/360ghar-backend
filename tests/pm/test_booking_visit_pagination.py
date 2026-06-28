"""Cursor-based pagination tests for bookings and visits list endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.bookings import Booking
from app.models.enums import (
    BookingStatus,
    PaymentStatus,
    PropertyPurpose,
    PropertyType,
    UserRole,
    VisitStatus,
)
from app.models.properties import Property, Visit
from app.models.users import User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def booking_user(db_session) -> User:
    """A regular user for booking pagination tests."""
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="booking_pag_user@example.com",
        phone="+919100000001",
        full_name="Booking Pag User",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def booking_client(test_app, booking_user) -> AsyncClient:
    """Authenticated client for booking_user."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(booking_user, from_attributes=True)

    async def _active() -> UserSchema:
        return user_schema

    test_app.dependency_overrides[get_current_user] = _active
    test_app.dependency_overrides[get_current_active_user] = _active
    test_app.dependency_overrides[get_current_user_optional] = _active

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_property(db_session, booking_user) -> Property:
    """A property owned by booking_user."""
    prop = Property(
        title="Pagination Test Property",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.short_stay,
        base_price=2000,
        daily_rate=2000,
        owner_id=booking_user.id,
    )
    db_session.add(prop)
    await db_session.flush()
    await db_session.refresh(prop)
    return prop


@pytest_asyncio.fixture
async def seeded_bookings(db_session, booking_user, seeded_property) -> list[Booking]:
    """Create 3 bookings for booking_user."""
    bookings = []
    base = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(3):
        b = Booking(
            user_id=booking_user.id,
            property_id=seeded_property.id,
            booking_reference=f"BKTEST{i:04d}",
            check_in_date=base + timedelta(days=i * 30 + 40),
            check_out_date=base + timedelta(days=i * 30 + 43),
            nights=3,
            guests=1,
            base_amount=6000.0,
            taxes_amount=1080.0,
            service_charges=300.0,
            discount_amount=0.0,
            total_amount=7380.0,
            booking_status=BookingStatus.pending,
            payment_status=PaymentStatus.pending,
            primary_guest_name="Test Guest",
            primary_guest_phone="+919999999999",
            primary_guest_email="guest@test.com",
        )
        db_session.add(b)
        await db_session.flush()
        await db_session.refresh(b)
        bookings.append(b)
    return bookings


@pytest_asyncio.fixture
async def seeded_upcoming_bookings(db_session, booking_user, seeded_property) -> list[Booking]:
    """Create 3 confirmed upcoming bookings for booking_user."""
    bookings = []
    base = datetime.now(timezone.utc)
    for i in range(3):
        b = Booking(
            user_id=booking_user.id,
            property_id=seeded_property.id,
            booking_reference=f"BKUP{i:04d}",
            check_in_date=base + timedelta(days=i * 10 + 5),
            check_out_date=base + timedelta(days=i * 10 + 8),
            nights=3,
            guests=1,
            base_amount=6000.0,
            taxes_amount=1080.0,
            service_charges=300.0,
            discount_amount=0.0,
            total_amount=7380.0,
            booking_status=BookingStatus.confirmed,
            payment_status=PaymentStatus.paid,
            primary_guest_name="Test Guest",
            primary_guest_phone="+919999999999",
            primary_guest_email="guest@test.com",
        )
        db_session.add(b)
        await db_session.flush()
        await db_session.refresh(b)
        bookings.append(b)
    return bookings


@pytest_asyncio.fixture
async def seeded_past_bookings(db_session, booking_user, seeded_property) -> list[Booking]:
    """Create 3 past bookings for booking_user."""
    bookings = []
    base = datetime.now(timezone.utc) - timedelta(days=100)
    for i in range(3):
        b = Booking(
            user_id=booking_user.id,
            property_id=seeded_property.id,
            booking_reference=f"BKPAST{i:04d}",
            check_in_date=base - timedelta(days=i * 10 + 10),
            check_out_date=base - timedelta(days=i * 10 + 7),
            nights=3,
            guests=1,
            base_amount=6000.0,
            taxes_amount=1080.0,
            service_charges=300.0,
            discount_amount=0.0,
            total_amount=7380.0,
            booking_status=BookingStatus.completed,
            payment_status=PaymentStatus.paid,
            primary_guest_name="Test Guest",
            primary_guest_phone="+919999999999",
            primary_guest_email="guest@test.com",
        )
        db_session.add(b)
        await db_session.flush()
        await db_session.refresh(b)
        bookings.append(b)
    return bookings


@pytest_asyncio.fixture
async def seeded_visits(db_session, booking_user, seeded_property) -> list[Visit]:
    """Create 3 upcoming visits for booking_user."""
    visits = []
    base = datetime.now(timezone.utc) + timedelta(days=5)
    for i in range(3):
        v = Visit(
            user_id=booking_user.id,
            property_id=seeded_property.id,
            scheduled_date=base + timedelta(days=i * 7),
            status=VisitStatus.scheduled,
        )
        db_session.add(v)
        await db_session.flush()
        await db_session.refresh(v)
        visits.append(v)
    return visits


@pytest_asyncio.fixture
async def seeded_past_visits(db_session, booking_user, seeded_property) -> list[Visit]:
    """Create 3 past visits for booking_user."""
    visits = []
    base = datetime.now(timezone.utc) - timedelta(days=50)
    for i in range(3):
        v = Visit(
            user_id=booking_user.id,
            property_id=seeded_property.id,
            scheduled_date=base - timedelta(days=i * 7),
            status=VisitStatus.completed,
        )
        db_session.add(v)
        await db_session.flush()
        await db_session.refresh(v)
        visits.append(v)
    return visits


# ---------------------------------------------------------------------------
# Bookings GET /api/v1/bookings
# ---------------------------------------------------------------------------


async def test_bookings_cursor_paginates(
    booking_client: AsyncClient, seeded_bookings: list[Booking]
) -> None:
    r1 = await booking_client.get("/api/v1/bookings/?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await booking_client.get(f"/api/v1/bookings/?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_bookings_include_total(
    booking_client: AsyncClient, seeded_bookings: list[Booking]
) -> None:
    r = await booking_client.get("/api/v1/bookings/?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_bookings_invalid_cursor_400(booking_client: AsyncClient) -> None:
    r = await booking_client.get("/api/v1/bookings/?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Bookings GET /api/v1/bookings/upcoming
# ---------------------------------------------------------------------------


async def test_upcoming_bookings_cursor_paginates(
    booking_client: AsyncClient, seeded_upcoming_bookings: list[Booking]
) -> None:
    r1 = await booking_client.get("/api/v1/bookings/upcoming?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True

    r2 = await booking_client.get(f"/api/v1/bookings/upcoming?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_upcoming_bookings_window_filter(
    booking_client: AsyncClient,
    seeded_past_bookings: list[Booking],
    seeded_upcoming_bookings: list[Booking],
) -> None:
    """Upcoming endpoint must only return future bookings."""
    r = await booking_client.get("/api/v1/bookings/upcoming?limit=100")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in items:
        assert item["check_in_date"] > now_iso


async def test_upcoming_bookings_invalid_cursor_400(booking_client: AsyncClient) -> None:
    r = await booking_client.get("/api/v1/bookings/upcoming?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Bookings GET /api/v1/bookings/past
# ---------------------------------------------------------------------------


async def test_past_bookings_cursor_paginates(
    booking_client: AsyncClient, seeded_past_bookings: list[Booking]
) -> None:
    r1 = await booking_client.get("/api/v1/bookings/past?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True

    r2 = await booking_client.get(f"/api/v1/bookings/past?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_past_bookings_window_filter(
    booking_client: AsyncClient,
    seeded_bookings: list[Booking],
    seeded_past_bookings: list[Booking],
) -> None:
    """Past endpoint must only return bookings where check_out_date < now."""
    r = await booking_client.get("/api/v1/bookings/past?limit=100")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in items:
        assert item["check_out_date"] < now_iso


async def test_past_bookings_invalid_cursor_400(booking_client: AsyncClient) -> None:
    r = await booking_client.get("/api/v1/bookings/past?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Visits GET /api/v1/visits
# ---------------------------------------------------------------------------


async def test_visits_cursor_paginates(
    booking_client: AsyncClient, seeded_visits: list[Visit]
) -> None:
    r1 = await booking_client.get("/api/v1/visits/?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await booking_client.get(f"/api/v1/visits/?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_visits_include_total(
    booking_client: AsyncClient, seeded_visits: list[Visit]
) -> None:
    r = await booking_client.get("/api/v1/visits/?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_visits_invalid_cursor_400(booking_client: AsyncClient) -> None:
    r = await booking_client.get("/api/v1/visits/?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Visits GET /api/v1/visits/upcoming
# ---------------------------------------------------------------------------


async def test_upcoming_visits_cursor_paginates(
    booking_client: AsyncClient, seeded_visits: list[Visit]
) -> None:
    r1 = await booking_client.get("/api/v1/visits/upcoming?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True

    r2 = await booking_client.get(f"/api/v1/visits/upcoming?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_upcoming_visits_window_filter(
    booking_client: AsyncClient,
    seeded_past_visits: list[Visit],
    seeded_visits: list[Visit],
) -> None:
    """Upcoming visits endpoint must only return future visits."""
    r = await booking_client.get("/api/v1/visits/upcoming?limit=100")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in items:
        assert item["scheduled_date"] > now_iso


async def test_upcoming_visits_invalid_cursor_400(booking_client: AsyncClient) -> None:
    r = await booking_client.get("/api/v1/visits/upcoming?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Visits GET /api/v1/visits/past
# ---------------------------------------------------------------------------


async def test_past_visits_cursor_paginates(
    booking_client: AsyncClient, seeded_past_visits: list[Visit]
) -> None:
    r1 = await booking_client.get("/api/v1/visits/past?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True

    r2 = await booking_client.get(f"/api/v1/visits/past?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_past_visits_window_filter(
    booking_client: AsyncClient,
    seeded_visits: list[Visit],
    seeded_past_visits: list[Visit],
) -> None:
    """Past visits endpoint must only return past visits."""
    r = await booking_client.get("/api/v1/visits/past?limit=100")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in items:
        assert item["scheduled_date"] < now_iso


async def test_past_visits_invalid_cursor_400(booking_client: AsyncClient) -> None:
    r = await booking_client.get("/api/v1/visits/past?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
