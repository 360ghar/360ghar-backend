"""Booking chat for the stays app: only the guest and the host may read or write (decisions.md).

Uses the generic conversation tables (app='stays', context_type='booking').
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.api_v1.dependencies.auth import get_current_cached_active_user
from app.models.bookings import Booking
from app.models.enums import (
    BookingStatus,
    PaymentStatus,
    PropertyPurpose,
    PropertyType,
    UserRole,
)
from app.models.properties import Property
from app.models.users import User
from app.schemas.user import SelfUser

pytestmark = pytest.mark.asyncio


def _user(name: str, phone: str) -> User:
    return User(
        supabase_user_id=str(uuid.uuid4()),
        phone=phone,
        full_name=name,
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )


@pytest.fixture
async def stay(db_session):
    guest = _user("Guest", "+919300000001")
    host = _user("Host", "+919300000002")
    stranger = _user("Stranger", "+919300000003")
    db_session.add_all([guest, host, stranger])
    await db_session.flush()

    prop = Property(
        title="Stay Villa",
        property_type=PropertyType.villa,
        purpose=PropertyPurpose.short_stay,
        base_price=9000,
        daily_rate=9000,
        owner_id=host.id,
        latitude=12.97,
        longitude=77.59,
    )
    db_session.add(prop)
    await db_session.flush()

    booking = Booking(
        user_id=guest.id,
        property_id=prop.id,
        booking_reference=f"BK-CHAT-{uuid.uuid4().hex[:8]}",
        check_in_date=date(2026, 12, 1),
        check_out_date=date(2026, 12, 3),
        nights=2,
        guests=2,
        base_amount=18000,
        taxes_amount=0,
        service_charges=0,
        discount_amount=0,
        total_amount=18000,
        booking_status=BookingStatus.confirmed,
        payment_status=PaymentStatus.pending,
        primary_guest_name="Guest",
        primary_guest_phone="+919300000001",
        primary_guest_email="guest@example.com",
    )
    db_session.add(booking)
    await db_session.flush()
    return {"guest": guest, "host": host, "stranger": stranger, "booking": booking}


@pytest.fixture
async def chat(test_app):
    """One HTTP client; ``as_user`` switches which user the auth override returns."""
    client = AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test")

    def as_user(user: User) -> AsyncClient:
        schema = SelfUser.model_validate(user, from_attributes=True)

        async def _override():
            return schema

        test_app.dependency_overrides[get_current_cached_active_user] = _override
        return client

    yield as_user
    await client.aclose()
    test_app.dependency_overrides.pop(get_current_cached_active_user, None)


async def test_guest_and_host_exchange_messages(chat, stay):
    booking_id = stay["booking"].id
    path = f"/api/v1/bookings/{booking_id}/messages"

    sent = await chat(stay["guest"]).post(path, json={"body": "Early check-in?"})
    assert sent.status_code == 201
    assert sent.json()["sender_id"] == stay["guest"].id
    assert sent.json()["body"] == "Early check-in?"

    reply = await chat(stay["host"]).post(path, json={"body": "Yes, from 11"})
    assert reply.status_code == 201
    assert reply.json()["sender_id"] == stay["host"].id

    page = await chat(stay["host"]).get(path)
    assert page.status_code == 200
    body = page.json()
    assert [m["body"] for m in body["items"]] == ["Yes, from 11", "Early check-in?"]
    assert body["total"] is None and body["has_more"] is False


async def test_messages_page_walks_back_in_time_with_keyset_cursor(chat, stay):
    """Keyset paging: newest page first, then older messages; no message repeats or drops."""
    path = f"/api/v1/bookings/{stay['booking'].id}/messages"
    for text in ["one", "two", "three"]:
        sent = await chat(stay["guest"]).post(path, json={"body": text})
        assert sent.status_code == 201

    first = (await chat(stay["host"]).get(path, params={"limit": 2})).json()
    assert [m["body"] for m in first["items"]] == ["three", "two"]
    assert first["has_more"] is True and first["next_cursor"]

    second = (
        await chat(stay["host"]).get(path, params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()
    assert [m["body"] for m in second["items"]] == ["one"]
    assert second["has_more"] is False and second["next_cursor"] is None


async def test_stranger_gets_404_and_writes_nothing(chat, stay):
    path = f"/api/v1/bookings/{stay['booking'].id}/messages"
    read = await chat(stay["stranger"]).get(path)
    write = await chat(stay["stranger"]).post(path, json={"body": "hi"})

    assert read.status_code == 404
    assert write.status_code == 404


async def test_blank_body_and_unknown_keys_are_rejected(chat, stay):
    path = f"/api/v1/bookings/{stay['booking'].id}/messages"
    resp = await chat(stay["guest"]).post(path, json={"body": "   "})
    extra = await chat(stay["guest"]).post(path, json={"body": "hi", "sender_id": 1})

    assert resp.status_code == 422
    assert extra.status_code == 422
