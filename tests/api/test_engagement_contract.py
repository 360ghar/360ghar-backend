"""Engagement contract: visits, bookings, agents and swipes (BE-engagement pass A)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_admin,
    get_current_cached_active_user,
)
from app.models.enums import (
    BookingStatus,
    PaymentStatus,
    PropertyPurpose,
    UserRole,
    VisitStatus,
)
from app.models.users import User, UserSwipe
from tests.fixtures.factories import (
    AgentFactory,
    BookingFactory,
    PropertyFactory,
    UserFactory,
    VisitFactory,
)

pytestmark = pytest.mark.asyncio

PUBLIC_REF_KEYS = {"id", "display_name", "avatar_url"}


async def _property(db, **kwargs):
    """A property with an owner. Properties need owner_id."""
    if "owner" not in kwargs and "owner_id" not in kwargs:
        kwargs["owner"] = await UserFactory.create(db)
    return await PropertyFactory.create(db, **kwargs)


def _in_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _act_as(test_app, user: User, *dependencies) -> None:
    """Authenticate every request as ``user`` through the given dependencies."""
    for dependency in dependencies:
        test_app.dependency_overrides[dependency] = lambda user=user: user


def _snapshot(user: User) -> SimpleNamespace:
    """Cached-user shape used by the GET routes."""
    return SimpleNamespace(
        id=user.id, role=user.role, agent_id=user.agent_id, is_active=True, email=user.email
    )


def _cached_as(test_app, user: User) -> None:
    snapshot = _snapshot(user)
    test_app.dependency_overrides[get_current_cached_active_user] = lambda: snapshot


# ---------------------------------------------------------------- visits


async def test_visit_counterparty_is_name_and_avatar_only_on_detail_and_list_routes(
    test_app, client: AsyncClient, db_session
):
    prop_owner = await UserFactory.create(db_session)
    prop = await _property(db_session, owner=prop_owner)
    visitor = await UserFactory.create(db_session)
    other = await UserFactory.create(db_session, full_name="Other Person")
    visit = await VisitFactory.create(
        db_session, user=visitor, property_obj=prop, counterparty_user_id=other.id
    )

    _cached_as(test_app, visitor)
    detail = await client.get(f"/api/v1/visits/{visit.id}")
    listed = await client.get("/api/v1/visits")

    assert detail.status_code == 200, detail.text
    assert listed.status_code == 200, listed.text
    assert set(detail.json()["user"]) == PUBLIC_REF_KEYS
    assert detail.json()["user"]["id"] == visitor.id
    for body in (detail.json(), next(i for i in listed.json()["items"] if i["id"] == visit.id)):
        counterparty = body["counterparty_user"]
        assert set(counterparty) == PUBLIC_REF_KEYS
        assert counterparty["id"] == other.id
        assert counterparty["display_name"] == "Other Person"
        assert other.email not in str(body)
        assert other.supabase_user_id not in str(body)


def test_every_visit_route_returns_the_visit_schema(test_app):
    """Upcoming, past, all, PUT, reschedule, cancel and complete all return Visit (or a page of it)."""
    from fastapi.routing import APIRoute

    from app.schemas.base import PublicUserRef
    from app.schemas.pagination import CursorPage
    from app.schemas.visit import Visit as VisitSchema

    routes = [
        route
        for route in test_app.routes
        if isinstance(route, APIRoute)
        and route.response_model
        and (
            route.path.startswith("/api/v1/visits")
            or (route.path.startswith("/api/v1/agents/") and route.path.endswith("/visits"))
        )
    ]
    assert len(routes) >= 11, [route.path for route in routes]
    for route in routes:
        assert route.response_model in {VisitSchema, CursorPage[VisitSchema]}, route.path

    assert VisitSchema.model_fields["counterparty_user"].annotation == PublicUserRef | None
    contact_fields = {"email", "phone", "date_of_birth", "current_latitude", "supabase_user_id"}
    assert not contact_fields & set(VisitSchema.model_fields)


async def test_agent_visit_route_hides_counterparty_contact(
    test_app, client: AsyncClient, db_session
):
    agent = await AgentFactory.create(db_session)
    customer = await UserFactory.create(db_session, agent_id=agent.id)
    other = await UserFactory.create(db_session)
    prop = await _property(db_session, owner=customer)
    await VisitFactory.create(
        db_session,
        user=customer,
        property_obj=prop,
        agent_id=agent.id,
        counterparty_user_id=other.id,
    )

    _cached_as(test_app, customer)
    _act_as(test_app, customer, get_current_active_user)
    response = await client.get(f"/api/v1/agents/{agent.id}/visits")

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert set(item["counterparty_user"]) == PUBLIC_REF_KEYS
    assert other.email not in response.text


async def test_agent_visit_route_limits_a_customer_to_own_visits(
    test_app, client: AsyncClient, db_session
):
    agent = await AgentFactory.create(db_session)
    customer = await UserFactory.create(db_session, agent_id=agent.id)
    stranger = await UserFactory.create(db_session, agent_id=agent.id)
    prop = await _property(db_session, owner=stranger)
    own = await VisitFactory.create(db_session, user=customer, property_obj=prop, agent_id=agent.id)
    await VisitFactory.create(db_session, user=stranger, property_obj=prop, agent_id=agent.id)

    _act_as(test_app, customer, get_current_active_user)
    response = await client.get(f"/api/v1/agents/{agent.id}/visits")

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [own.id]


async def test_create_visit_stores_and_returns_time_slot_label(
    test_app, client: AsyncClient, db_session
):
    user = await UserFactory.create(db_session)
    prop = await _property(db_session)
    _act_as(test_app, user, get_current_active_user)

    response = await client.post(
        "/api/v1/visits",
        json={"property_id": prop.id, "scheduled_date": _in_days(3), "time_slot_label": "morning"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["time_slot_label"] == "morning"
    _cached_as(test_app, user)
    fetched = await client.get(f"/api/v1/visits/{response.json()['id']}")
    assert fetched.json()["time_slot_label"] == "morning"


async def test_create_visit_sets_the_owners_agent(test_app, client: AsyncClient, db_session):
    agent = await AgentFactory.create(db_session, contact_number="+919111111111")
    user = await UserFactory.create(db_session, agent_id=agent.id)
    prop = await _property(db_session)
    _act_as(test_app, user, get_current_active_user)

    response = await client.post(
        "/api/v1/visits", json={"property_id": prop.id, "scheduled_date": _in_days(3)}
    )

    assert response.status_code == 201, response.text
    assert response.json()["agent_id"] == agent.id
    assert response.json()["agents"]["id"] == agent.id


async def test_customer_cannot_set_another_visit_owner(test_app, client: AsyncClient, db_session):
    user = await UserFactory.create(db_session)
    someone = await UserFactory.create(db_session)
    prop = await _property(db_session)
    _act_as(test_app, user, get_current_active_user)

    response = await client.post(
        "/api/v1/visits",
        json={"property_id": prop.id, "scheduled_date": _in_days(3), "user_id": someone.id},
    )

    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == user.id


async def test_admin_can_set_the_visit_owner(test_app, client: AsyncClient, db_session):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session)
    _act_as(test_app, admin, get_current_active_user)

    response = await client.post(
        "/api/v1/visits",
        json={"property_id": prop.id, "scheduled_date": _in_days(3), "user_id": guest.id},
    )

    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == guest.id


async def test_visit_cancel_needs_a_reason_and_put_cannot_cancel(
    test_app, client: AsyncClient, db_session
):
    user = await UserFactory.create(db_session)
    prop = await _property(db_session)
    visit = await VisitFactory.create(db_session, user=user, property_obj=prop)
    _act_as(test_app, user, get_current_active_user)

    no_reason = await client.post(f"/api/v1/visits/{visit.id}/cancel", json={})
    via_put = await client.put(f"/api/v1/visits/{visit.id}", json={"status": "cancelled"})
    with_reason = await client.post(
        f"/api/v1/visits/{visit.id}/cancel", json={"reason": "Changed plans"}
    )

    assert no_reason.status_code == 422, no_reason.text
    assert no_reason.json()["error"]["code"] == "VALIDATION_ERROR"
    assert via_put.status_code == 422, via_put.text
    assert with_reason.status_code == 200, with_reason.text
    assert with_reason.json()["status"] == "cancelled"
    assert with_reason.json()["cancellation_reason"] == "Changed plans"


async def test_put_visit_rejects_a_reschedule_and_reschedule_route_works(
    test_app, client: AsyncClient, db_session
):
    user = await UserFactory.create(db_session)
    prop = await _property(db_session)
    visit = await VisitFactory.create(db_session, user=user, property_obj=prop)
    _act_as(test_app, user, get_current_active_user)

    via_put = await client.put(f"/api/v1/visits/{visit.id}", json={"scheduled_date": _in_days(5)})
    via_route = await client.post(
        f"/api/v1/visits/{visit.id}/reschedule", json={"new_date": _in_days(5)}
    )

    assert via_put.status_code == 422, via_put.text
    assert via_route.status_code == 200, via_route.text
    assert via_route.json()["status"] == "reschedule_suggested"


async def test_admin_visit_search_matches_the_property_title(
    test_app, client: AsyncClient, db_session
):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    prop = await _property(db_session, title="Sea View Flat")
    other_prop = await _property(db_session, title="Garden Villa")
    visit = await VisitFactory.create(db_session, user=admin, property_obj=prop)
    await VisitFactory.create(db_session, user=admin, property_obj=other_prop)
    _cached_as(test_app, admin)

    response = await client.get("/api/v1/visits/all", params={"q": "sea view"})

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [visit.id]


async def test_admin_visit_search_matches_the_agent_name(test_app, client: AsyncClient, db_session):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    orion = await AgentFactory.create(db_session, name="Agent Orion")
    lyra = await AgentFactory.create(db_session, name="Agent Lyra")
    prop = await _property(db_session)
    visit = await VisitFactory.create(db_session, user=admin, property_obj=prop, agent_id=orion.id)
    await VisitFactory.create(db_session, user=admin, property_obj=prop, agent_id=lyra.id)
    _cached_as(test_app, admin)

    response = await client.get("/api/v1/visits/all", params={"q": "orion"})

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [visit.id]


async def test_admin_visit_search_matches_the_visitor_name(
    test_app, client: AsyncClient, db_session
):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    zed = await UserFactory.create(db_session, full_name="Zed Visitor")
    kim = await UserFactory.create(db_session, full_name="Kim Visitor")
    prop = await _property(db_session)
    visit = await VisitFactory.create(db_session, user=zed, property_obj=prop)
    await VisitFactory.create(db_session, user=kim, property_obj=prop)
    _cached_as(test_app, admin)

    response = await client.get("/api/v1/visits/all", params={"q": "zed"})

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [visit.id]


# -------------------------------------------------------------- bookings


async def test_guest_booking_response_has_no_internal_notes(
    test_app, client: AsyncClient, db_session
):
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session)
    booking = await BookingFactory.create(
        db_session, user=guest, property_obj=prop, internal_notes="staff only"
    )

    _cached_as(test_app, guest)
    guest_view = await client.get(f"/api/v1/bookings/{booking.id}")
    assert guest_view.status_code == 200, guest_view.text
    assert "internal_notes" not in guest_view.json()
    assert guest_view.json()["property"]["id"] == prop.id
    assert set(guest_view.json()["guest"]) == PUBLIC_REF_KEYS

    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    _cached_as(test_app, admin)
    staff_view = await client.get(f"/api/v1/bookings/{booking.id}")
    assert staff_view.status_code == 200, staff_view.text
    assert staff_view.json()["internal_notes"] == "staff only"


async def test_booking_create_replays_the_first_result_for_the_same_key(
    test_app, client: AsyncClient, db_session
):
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session, purpose=PropertyPurpose.short_stay)
    _act_as(test_app, guest, get_current_active_user)
    body = {
        "property_id": prop.id,
        "check_in_date": _in_days(7),
        "check_out_date": _in_days(9),
        "guests": 2,
        "primary_guest_name": "Guest",
        "primary_guest_phone": "+919876543210",
        "primary_guest_email": "guest@example.com",
    }
    headers = {"Idempotency-Key": "key-123"}

    first = await client.post("/api/v1/bookings", json=body, headers=headers)
    second = await client.post("/api/v1/bookings", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["booking_reference"] == first.json()["booking_reference"]


async def test_booking_blank_idempotency_key_is_rejected(test_app, client: AsyncClient, db_session):
    """A blank key used to be stored as "" and fail on the second POST with a unique violation."""
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session, purpose=PropertyPurpose.short_stay)
    _act_as(test_app, guest, get_current_active_user)
    body = {
        "property_id": prop.id,
        "check_in_date": _in_days(7),
        "check_out_date": _in_days(9),
        "guests": 2,
        "primary_guest_name": "Guest",
        "primary_guest_phone": "+919876543210",
        "primary_guest_email": "guest@example.com",
    }
    headers = {"Idempotency-Key": ""}

    first = await client.post("/api/v1/bookings", json=body, headers=headers)
    second = await client.post("/api/v1/bookings", json=body, headers=headers)

    assert first.status_code == 422, first.text
    assert second.status_code == 422, second.text
    assert first.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
    stored = await db_session.execute(
        text("SELECT count(*) FROM bookings WHERE created_by_user_id = :uid"), {"uid": guest.id}
    )
    assert stored.scalar_one() == 0


async def test_visit_times_need_a_utc_offset(test_app, client: AsyncClient, db_session):
    """A naive time was read as UTC: 14:00 IST was stored as 14:00 UTC."""
    user = await UserFactory.create(db_session)
    prop = await _property(db_session)
    visit = await VisitFactory.create(db_session, user=user, property_obj=prop)
    _act_as(test_app, user, get_current_active_user)
    naive = (datetime.now(UTC) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")

    created = await client.post(
        "/api/v1/visits", json={"property_id": prop.id, "scheduled_date": naive}
    )
    rescheduled = await client.post(
        f"/api/v1/visits/{visit.id}/reschedule", json={"new_date": naive}
    )

    assert created.status_code == 422, created.text
    assert rescheduled.status_code == 422, rescheduled.text
    created_fields = [f["field"] for f in created.json()["error"]["details"]["fields"]]
    rescheduled_fields = [f["field"] for f in rescheduled.json()["error"]["details"]["fields"]]
    assert created_fields == ["body.scheduled_date"]
    assert rescheduled_fields == ["body.new_date"]


async def test_visit_offset_time_is_stored_as_utc(test_app, client: AsyncClient, db_session):
    user = await UserFactory.create(db_session)
    prop = await _property(db_session)
    _act_as(test_app, user, get_current_active_user)

    response = await client.post(
        "/api/v1/visits",
        json={"property_id": prop.id, "scheduled_date": "2099-07-01T14:00:00+05:30"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["scheduled_date"] == "2099-07-01T08:30:00Z"


async def test_admin_booking_create_sets_the_guest_as_owner(
    test_app, client: AsyncClient, db_session
):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session, purpose=PropertyPurpose.short_stay)
    _act_as(test_app, admin, get_current_active_user)

    response = await client.post(
        "/api/v1/bookings",
        json={
            "property_id": prop.id,
            "check_in_date": _in_days(7),
            "check_out_date": _in_days(9),
            "guests": 2,
            "primary_guest_name": "Guest",
            "primary_guest_phone": "+919876543210",
            "primary_guest_email": "guest@example.com",
            "user_id": guest.id,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == guest.id


async def test_calculate_pricing_failures_are_4xx_envelopes(client: AsyncClient, db_session):
    prop = await _property(db_session, purpose=PropertyPurpose.short_stay)
    prop.daily_rate = None
    await db_session.flush()
    payload = {
        "property_id": prop.id,
        "check_in_date": _in_days(7),
        "check_out_date": _in_days(9),
        "guests": 2,
    }

    no_rate = await client.post("/api/v1/bookings/calculate-pricing", json=payload)
    unknown = await client.post(
        "/api/v1/bookings/calculate-pricing", json={**payload, "property_id": 999999}
    )

    assert no_rate.status_code == 400, no_rate.text
    assert no_rate.json()["error"]["code"] == "PRICING_UNAVAILABLE"
    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["error"]["code"] == "PROPERTY_NOT_FOUND"


async def test_calculate_pricing_returns_rounded_money_numbers(client: AsyncClient, db_session):
    prop = await _property(db_session, purpose=PropertyPurpose.short_stay)
    prop.daily_rate = 1000.005
    await db_session.flush()

    response = await client.post(
        "/api/v1/bookings/calculate-pricing",
        json={
            "property_id": prop.id,
            "check_in_date": _in_days(7),
            "check_out_date": _in_days(9),
            "guests": 2,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["nights"] == 2
    for key in (
        "base_amount",
        "taxes_amount",
        "service_charges",
        "discount_amount",
        "total_amount",
    ):
        assert isinstance(body[key], float)
        assert round(body[key], 2) == body[key]


async def test_admin_booking_list_filters_by_payment_status_and_search(
    test_app, client: AsyncClient, db_session
):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session)
    paid = await BookingFactory.create(
        db_session,
        user=guest,
        property_obj=prop,
        primary_guest_name="Asha Rao",
        primary_guest_email="asha.rao@example.com",
        payment_status=PaymentStatus.paid,
    )
    await BookingFactory.create(db_session, user=guest, property_obj=prop, primary_guest_name="Ben")
    _cached_as(test_app, admin)

    by_status = await client.get("/api/v1/bookings/all", params={"payment_status": "paid"})
    by_name = await client.get("/api/v1/bookings/all", params={"q": "asha"})
    by_email = await client.get("/api/v1/bookings/all", params={"q": "asha.rao@"})

    assert by_status.status_code == 200, by_status.text
    assert [item["id"] for item in by_status.json()["items"]] == [paid.id]
    assert by_name.status_code == 200, by_name.text
    assert [item["id"] for item in by_name.json()["items"]] == [paid.id]
    assert by_email.status_code == 200, by_email.text
    assert [item["id"] for item in by_email.json()["items"]] == [paid.id]


# ---------------------------------------------------------------- agents


async def test_agent_availability_takes_a_json_body(test_app, client: AsyncClient, db_session):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    agent = await AgentFactory.create(db_session)
    _act_as(test_app, admin, get_current_admin)

    as_body = await client.patch(
        f"/api/v1/agents/{agent.id}/availability", json={"is_available": False}
    )
    as_query = await client.patch(
        f"/api/v1/agents/{agent.id}/availability", params={"is_available": False}
    )

    assert as_body.status_code == 200, as_body.text
    assert as_body.json()["id"] == agent.id
    assert as_body.json()["is_available"] is False
    assert as_query.status_code == 422, as_query.text


async def test_agent_stats_are_for_admins_and_the_agent_only(
    test_app, client: AsyncClient, db_session
):
    agent = await AgentFactory.create(db_session)
    customer = await UserFactory.create(db_session, agent_id=agent.id)
    _act_as(test_app, customer, get_current_active_user)
    customer_view = await client.get(f"/api/v1/agents/{agent.id}/stats")

    own_user = await UserFactory.create(db_session, role=UserRole.agent.value, agent_id=agent.id)
    _act_as(test_app, own_user, get_current_active_user)
    agent_view = await client.get(f"/api/v1/agents/{agent.id}/stats")

    assert customer_view.status_code == 403, customer_view.text
    assert agent_view.status_code == 200, agent_view.text
    assert "efficiency_score" in agent_view.json()["stats"]


async def test_assigned_agent_read_does_not_assign(test_app, client: AsyncClient, db_session):
    user = await UserFactory.create(db_session)
    await AgentFactory.create(db_session)
    _act_as(test_app, user, get_current_active_user)

    response = await client.get("/api/v1/agents/assigned")

    assert response.status_code == 404, response.text
    await db_session.refresh(user)
    assert user.agent_id is None


async def test_delete_agent_returns_no_content(test_app, client: AsyncClient, db_session):
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    agent = await AgentFactory.create(db_session)
    _act_as(test_app, admin, get_current_admin)

    response = await client.delete(f"/api/v1/agents/{agent.id}")

    assert response.status_code == 204, response.text
    assert response.content == b""


# ---------------------------------------------------------------- swipes


async def test_swipe_returns_a_typed_swipe_and_rejects_own_and_missing_property(
    test_app, client: AsyncClient, db_session
):
    owner = await UserFactory.create(db_session)
    user = await UserFactory.create(db_session)
    prop = await _property(db_session, owner=owner)
    own = await _property(db_session, owner=user)
    _act_as(test_app, user, get_current_active_user)

    created = await client.post("/api/v1/swipes", json={"property_id": prop.id, "is_liked": True})
    updated = await client.post("/api/v1/swipes", json={"property_id": prop.id, "is_liked": False})
    own_property = await client.post(
        "/api/v1/swipes", json={"property_id": own.id, "is_liked": True}
    )
    missing = await client.post("/api/v1/swipes", json={"property_id": 999999, "is_liked": True})

    assert created.status_code == 201, created.text
    assert set(created.json()) == {"id", "property_id", "is_liked"}
    assert created.json()["is_liked"] is True
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == created.json()["id"]
    assert own_property.status_code == 403, own_property.text
    assert own_property.json()["error"]["code"] == "OWN_PROPERTY_SWIPE"
    assert missing.status_code == 404, missing.text
    assert missing.json()["error"]["code"] == "PROPERTY_NOT_FOUND"


async def test_swipe_toggle_returns_the_typed_swipe(test_app, client: AsyncClient, db_session):
    owner = await UserFactory.create(db_session)
    user = await UserFactory.create(db_session)
    prop = await _property(db_session, owner=owner)
    _act_as(test_app, user, get_current_active_user)
    created = await client.post("/api/v1/swipes", json={"property_id": prop.id, "is_liked": True})

    toggled = await client.put(f"/api/v1/swipes/{created.json()['id']}/toggle")

    assert toggled.status_code == 200, toggled.text
    assert toggled.json() == {
        "id": created.json()["id"],
        "property_id": prop.id,
        "is_liked": False,
    }


async def test_likes_feed_accepts_the_filters_it_sends(test_app, client: AsyncClient, db_session):
    user = await UserFactory.create(db_session)
    _cached_as(test_app, user)

    response = await client.get(
        "/api/v1/swipes",
        params={
            "is_liked": "true",
            "gender_preference": "any",
            "sharing_type": "shared_room",
            "available_from": "2026-07-01",
            "ids": [1, 2],
        },
    )

    assert response.status_code == 200, response.text
    assert set(response.json()) >= {"items", "next_cursor", "has_more", "limit"}


async def test_likes_feed_applies_available_from(test_app, client: AsyncClient, db_session):
    """GET /swipes filters by available_from, like GET /properties does."""
    user = await UserFactory.create(db_session)
    owner = await UserFactory.create(db_session)
    early = await _property(
        db_session, owner=owner, available_from=datetime(2026, 8, 1, tzinfo=UTC)
    )
    late = await _property(
        db_session, owner=owner, available_from=datetime(2026, 12, 1, tzinfo=UTC)
    )
    _act_as(test_app, user, get_current_active_user)
    for prop in (early, late):
        await client.post("/api/v1/swipes", json={"property_id": prop.id, "is_liked": True})
    _cached_as(test_app, user)

    response = await client.get("/api/v1/swipes", params={"available_from": "2026-11-01"})

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [late.id]


async def test_likes_feed_rejects_list_only_flags(test_app, client: AsyncClient, db_session):
    """semantic_search and exclude_swiped do not apply to the feed, so true gives 422."""
    user = await UserFactory.create(db_session)
    _cached_as(test_app, user)

    response = await client.get("/api/v1/swipes", params={"exclude_swiped": "true"})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_batch_remove_lists_the_ids_it_did_not_remove(
    test_app, client: AsyncClient, db_session
):
    owner = await UserFactory.create(db_session)
    user = await UserFactory.create(db_session)
    swiped = await _property(db_session, owner=owner)
    not_swiped = await _property(db_session, owner=owner)
    _act_as(test_app, user, get_current_active_user)
    await client.post("/api/v1/swipes", json={"property_id": swiped.id, "is_liked": True})

    response = await client.post(
        "/api/v1/swipes/batch-remove",
        json={"property_ids": [swiped.id, not_swiped.id]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"removed_count": 1, "failed_property_ids": [not_swiped.id]}


async def test_undo_without_a_swipe_is_404(test_app, client: AsyncClient, db_session):
    user = await UserFactory.create(db_session)
    _act_as(test_app, user, get_current_active_user)

    response = await client.delete("/api/v1/swipes/undo")

    assert response.status_code == 404, response.text


# -------------------------------------------------------------- removed


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/payments/methods"),
        ("POST", "/api/v1/payments/methods"),
        ("POST", "/api/v1/payments/razorpay/order"),
        ("POST", "/api/v1/payments/razorpay/verify"),
    ],
)
async def test_payment_routes_are_gone(client: AsyncClient, method: str, path: str):
    response = await client.request(method, path, json={})
    assert response.status_code == 404, response.text


# ------------------------------------------- pass B: occupancy, staff notes, enums


async def test_check_availability_checks_guest_count_only(
    test_app, client: AsyncClient, db_session
):
    """Overlapping bookings are allowed, so the check takes no dates."""
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session, max_occupancy=4)
    await BookingFactory.create(
        db_session,
        user=guest,
        property_obj=prop,
        check_in_date=datetime.now(UTC) + timedelta(days=7),
        check_out_date=datetime.now(UTC) + timedelta(days=10),
    )
    _act_as(test_app, guest, get_current_active_user)

    fits = await client.post(
        "/api/v1/bookings/check-availability", json={"property_id": prop.id, "guests": 2}
    )
    too_many = await client.post(
        "/api/v1/bookings/check-availability", json={"property_id": prop.id, "guests": 5}
    )
    with_dates = await client.post(
        "/api/v1/bookings/check-availability",
        json={
            "property_id": prop.id,
            "guests": 2,
            "check_in_date": _in_days(8),
            "check_out_date": _in_days(9),
        },
    )

    assert fits.status_code == 200, fits.text
    assert fits.json() == {"occupancy_ok": True, "reason": None, "max_occupancy": 4}
    assert too_many.status_code == 200, too_many.text
    assert too_many.json()["occupancy_ok"] is False
    assert "maximum 4 guests" in too_many.json()["reason"]
    assert "available" not in fits.json()
    assert with_dates.status_code == 422, with_dates.text
    assert with_dates.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_booking_update_rejects_null_on_not_null_dates(
    test_app, client: AsyncClient, db_session
):
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session)
    booking = await BookingFactory.create(db_session, user=guest, property_obj=prop)
    _act_as(test_app, guest, get_current_active_user)

    response = await client.put(f"/api/v1/bookings/{booking.id}", json={"check_in_date": None})

    assert response.status_code == 422, response.text
    fields = response.json()["error"]["details"]["fields"]
    assert any(field["field"] == "body.check_in_date" for field in fields), fields


async def test_booking_internal_notes_are_written_by_staff_only(
    test_app, client: AsyncClient, db_session
):
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session)
    booking = await BookingFactory.create(db_session, user=guest, property_obj=prop)

    _act_as(test_app, guest, get_current_active_user)
    as_guest = await client.put(
        f"/api/v1/bookings/{booking.id}", json={"internal_notes": "guest note"}
    )
    assert as_guest.status_code == 403, as_guest.text
    assert as_guest.json()["error"]["code"] == "FORBIDDEN"

    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    _act_as(test_app, admin, get_current_active_user)
    as_admin = await client.put(
        f"/api/v1/bookings/{booking.id}", json={"internal_notes": "staff note"}
    )
    assert as_admin.status_code == 200, as_admin.text
    assert as_admin.json()["internal_notes"] == "staff note"

    _cached_as(test_app, guest)
    guest_view = await client.get(f"/api/v1/bookings/{booking.id}")
    assert guest_view.status_code == 200, guest_view.text
    assert "internal_notes" not in guest_view.json()


async def test_booking_response_has_no_host_review_fields(
    test_app, client: AsyncClient, db_session
):
    """host_rating and host_review have no writer, so the API does not return them."""
    guest = await UserFactory.create(db_session)
    prop = await _property(db_session)
    booking = await BookingFactory.create(db_session, user=guest, property_obj=prop)

    _cached_as(test_app, guest)
    response = await client.get(f"/api/v1/bookings/{booking.id}")

    assert response.status_code == 200, response.text
    assert "host_rating" not in response.json()
    assert "host_review" not in response.json()


async def test_visit_status_db_labels_match_wire_values(db_session):
    """The Postgres enum stores the same strings the API sends."""
    result = await db_session.execute(text("SELECT unnest(enum_range(NULL::visit_status))::text"))
    labels = sorted(result.scalars().all())

    assert labels == sorted(member.value for member in VisitStatus)
    assert "requested" in labels
    assert "reschedule_suggested" in labels


# ------------------------------------- fix round 2: swipe scope, payment, review, reasons


async def test_flatmates_peer_swipe_is_ignored_by_property_swipe_routes(
    test_app, client: AsyncClient, db_session
):
    """A flatmates peer swipe (target_type='user') is not a property swipe.

    The feed, stats, toggle, batch-remove and undo never read or change it.
    """
    user = await UserFactory.create(db_session)
    peer = await UserFactory.create(db_session)
    owner = await UserFactory.create(db_session)
    prop = await _property(db_session, owner=owner)
    _act_as(test_app, user, get_current_active_user)
    liked = await client.post("/api/v1/swipes", json={"property_id": prop.id, "is_liked": True})
    assert liked.status_code == 201, liked.text
    # The newest row in the table is the peer swipe. Undo must still skip it.
    peer_swipe = UserSwipe(
        user_id=user.id,
        property_id=None,
        target_user_id=peer.id,
        target_type="user",
        swipe_action="like",
        is_liked=True,
        created_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(peer_swipe)
    await db_session.flush()
    peer_id = peer_swipe.id

    _cached_as(test_app, user)
    feed = await client.get("/api/v1/swipes")
    stats = await client.get("/api/v1/swipes/stats")
    assert [item["id"] for item in feed.json()["items"]] == [prop.id], feed.text
    assert stats.status_code == 200, stats.text
    assert stats.json()["total_swipes"] == 1, stats.text
    assert stats.json()["liked_count"] == 1, stats.text

    _act_as(test_app, user, get_current_active_user)
    toggled = await client.put(f"/api/v1/swipes/{peer_id}/toggle")
    assert toggled.status_code == 404, toggled.text

    removed = await client.post("/api/v1/swipes/batch-remove", json={"property_ids": [prop.id]})
    assert removed.json() == {"removed_count": 1, "failed_property_ids": []}, removed.text

    undo = await client.delete("/api/v1/swipes/undo")
    assert undo.status_code == 404, undo.text

    await db_session.refresh(peer_swipe)
    assert peer_swipe.is_liked is True
    assert peer_swipe.target_type == "user"


@pytest.mark.parametrize(
    "booking_status",
    [BookingStatus.cancelled, BookingStatus.completed, BookingStatus.checked_out],
)
async def test_payment_is_refused_for_a_closed_booking(
    test_app, client: AsyncClient, db_session, booking_status
):
    """A cancelled, completed or checked-out booking is not payable. Its state stays as it was."""
    guest = await UserFactory.create(db_session)
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    prop = await _property(db_session)
    booking = await BookingFactory.create(
        db_session,
        user=guest,
        property_obj=prop,
        booking_status=booking_status,
        payment_status=PaymentStatus.refunded
        if booking_status == BookingStatus.cancelled
        else PaymentStatus.pending,
    )
    _act_as(test_app, admin, get_current_active_user)

    response = await client.post(
        "/api/v1/bookings/payment",
        json={
            "booking_id": booking.id,
            "payment_method": "cash",
            "transaction_id": "TXN-REVIVE",
            "amount": float(booking.total_amount),
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BOOKING_NOT_PAYABLE"
    await db_session.refresh(booking)
    assert booking.booking_status == booking_status
    assert booking.transaction_id is None


async def test_payment_still_confirms_a_pending_booking(test_app, client: AsyncClient, db_session):
    """Control: the guard blocks closed bookings only."""
    guest = await UserFactory.create(db_session)
    admin = await UserFactory.create(db_session, role=UserRole.admin.value)
    prop = await _property(db_session)
    booking = await BookingFactory.create(db_session, user=guest, property_obj=prop)
    _act_as(test_app, admin, get_current_active_user)

    # The success path sends a notification. Stub it: the real dispatcher calls Supabase.
    with patch("app.api.api_v1.endpoints.bookings.dispatch_notification_to_user", new=AsyncMock()):
        response = await client.post(
            "/api/v1/bookings/payment",
            json={
                "booking_id": booking.id,
                "payment_method": "cash",
                "transaction_id": "TXN-OK",
                "amount": float(booking.total_amount),
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["booking_status"] == "confirmed"
    assert response.json()["payment_status"] == "paid"


async def test_non_guest_review_is_rejected_with_review_not_allowed(
    test_app, client: AsyncClient, db_session
):
    guest = await UserFactory.create(db_session)
    other = await UserFactory.create(db_session)
    prop = await _property(db_session)
    booking = await BookingFactory.create(
        db_session, user=guest, property_obj=prop, booking_status=BookingStatus.completed
    )
    body = {"booking_id": booking.id, "guest_rating": 5}

    _act_as(test_app, other, get_current_active_user)
    rejected = await client.post("/api/v1/bookings/review", json=body)
    _act_as(test_app, guest, get_current_active_user)
    accepted = await client.post("/api/v1/bookings/review", json=body)

    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["error"]["code"] == "REVIEW_NOT_ALLOWED"
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["guest_rating"] == 5


async def test_check_availability_unknown_property_is_404(
    test_app, client: AsyncClient, db_session
):
    """Same error as calculate-pricing for an unknown property: 404 PROPERTY_NOT_FOUND."""
    user = await UserFactory.create(db_session)
    _act_as(test_app, user, get_current_active_user)

    response = await client.post(
        "/api/v1/bookings/check-availability", json={"property_id": 999999, "guests": 2}
    )
    pricing = await client.post(
        "/api/v1/bookings/calculate-pricing",
        json={
            "property_id": 999999,
            "check_in_date": _in_days(8),
            "check_out_date": _in_days(9),
            "guests": 2,
        },
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "PROPERTY_NOT_FOUND"
    assert pricing.status_code == 404, pricing.text


async def test_whitespace_only_cancel_reason_is_rejected_on_visit_and_booking(
    test_app, client: AsyncClient, db_session
):
    user = await UserFactory.create(db_session)
    prop = await _property(db_session)
    visit = await VisitFactory.create(db_session, user=user, property_obj=prop)
    booking = await BookingFactory.create(db_session, user=user, property_obj=prop)
    _act_as(test_app, user, get_current_active_user)

    visit_blank = await client.post(f"/api/v1/visits/{visit.id}/cancel", json={"reason": "   "})
    booking_blank = await client.post(
        "/api/v1/bookings/cancel", json={"booking_id": booking.id, "reason": "   "}
    )
    padded = await client.post(
        f"/api/v1/visits/{visit.id}/cancel", json={"reason": "  Changed plans  "}
    )

    assert visit_blank.status_code == 422, visit_blank.text
    assert visit_blank.json()["error"]["code"] == "VALIDATION_ERROR"
    assert booking_blank.status_code == 422, booking_blank.text
    assert booking_blank.json()["error"]["code"] == "VALIDATION_ERROR"
    assert padded.status_code == 200, padded.text
    assert padded.json()["cancellation_reason"] == "Changed plans"
