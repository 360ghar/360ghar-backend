"""Schema rules for visits, bookings, agents and swipes (no database)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.bookings import Booking
from app.schemas.agent import AgentAvailabilityUpdate, AgentUpdate
from app.schemas.booking import BookingCreate, BookingPricing, BookingUpdate
from app.schemas.swipe import BatchRemoveRequest, SwipeCreate
from app.schemas.visit import Visit, VisitCancel, VisitCreate, VisitUpdate

NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def test_visit_create_rejects_unknown_keys():
    with pytest.raises(ValidationError) as exc:
        VisitCreate(property_id=1, scheduled_date=NOW, visit_notes="not writable here")
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_visit_create_rejects_a_naive_date():
    with pytest.raises(ValidationError) as exc:
        VisitCreate(property_id=1, scheduled_date=datetime(2030, 1, 1, 10, 0))
    assert exc.value.errors()[0]["loc"] == ("scheduled_date",)


def test_visit_create_converts_an_offset_date_to_utc():
    visit = VisitCreate(property_id=1, scheduled_date="2030-01-01T10:00:00+05:30")
    assert visit.scheduled_date.utcoffset().total_seconds() == 0
    assert visit.scheduled_date.hour == 4 and visit.scheduled_date.minute == 30


@pytest.mark.parametrize("status", ["cancelled", "completed", "rescheduled", "requested"])
def test_visit_update_status_only_confirms(status):
    with pytest.raises(ValidationError):
        VisitUpdate(status=status)


def test_visit_update_confirms_and_rejects_null_for_required_fields():
    assert VisitUpdate(status="confirmed").status.value == "confirmed"
    with pytest.raises(ValidationError):
        VisitUpdate.model_validate({"status": None})
    with pytest.raises(ValidationError):
        VisitUpdate.model_validate({"follow_up_required": None})


def test_visit_update_has_no_reschedule_or_cancel_fields():
    with pytest.raises(ValidationError):
        VisitUpdate.model_validate({"scheduled_date": NOW.isoformat()})
    with pytest.raises(ValidationError):
        VisitUpdate.model_validate({"cancellation_reason": "nope"})


def test_visit_cancel_needs_a_reason():
    with pytest.raises(ValidationError):
        VisitCancel.model_validate({})
    assert VisitCancel(reason="Changed plans").reason == "Changed plans"


def test_visit_counterparty_is_public_user_ref_only():
    counterparty = {
        "id": 7,
        "full_name": "Asha Rao",
        "email": "asha@example.com",
        "phone": "+919000000001",
        "supabase_user_id": "uuid-7",
        "date_of_birth": "1990-01-01",
        "current_latitude": 19.1,
        "profile_image_url": "https://img.example.com/7.png",
    }
    payload = {
        "id": 1,
        "property_id": 2,
        "user_id": 3,
        "scheduled_date": NOW,
        "status": "requested",
        "created_at": NOW,
        "counterparty_user": counterparty,
    }

    dumped = Visit.model_validate(payload).model_dump(mode="json")

    assert dumped["counterparty_user"] == {
        "id": 7,
        "display_name": "Asha Rao",
        "avatar_url": "https://img.example.com/7.png",
    }
    assert "asha@example.com" not in str(dumped)


def test_visit_dates_are_utc_strings_ending_in_z():
    payload = {
        "id": 1,
        "property_id": 2,
        "user_id": 3,
        "scheduled_date": NOW,
        "status": "requested",
        "created_at": NOW,
    }
    dumped = Visit.model_validate(payload).model_dump(mode="json")
    assert dumped["scheduled_date"] == "2030-01-01T10:00:00Z"


def test_booking_create_rejects_money_and_status_fields():
    body = {
        "property_id": 1,
        "check_in_date": NOW,
        "check_out_date": datetime(2030, 1, 3, 10, 0, tzinfo=UTC),
        "guests": 1,
        "primary_guest_name": "A",
        "primary_guest_phone": "+919000000002",
        "primary_guest_email": "a@example.com",
    }
    BookingCreate.model_validate(body)
    for extra in ("total_amount", "booking_status", "payment_status", "nights"):
        with pytest.raises(ValidationError):
            BookingCreate.model_validate({**body, extra: 1})


def test_booking_update_has_no_notes_field_and_rejects_null_name():
    with pytest.raises(ValidationError):
        BookingUpdate.model_validate({"notes": "dropped before"})
    with pytest.raises(ValidationError):
        BookingUpdate.model_validate({"primary_guest_name": None})


def test_booking_pricing_money_is_two_decimal_numbers():
    pricing = BookingPricing(
        property_id=1,
        check_in_date=NOW,
        check_out_date=NOW,
        guests=1,
        nights=1,
        base_amount=100.456,
        taxes_amount=18.08208,
        service_charges=5.0,
        discount_amount=0.0,
        total_amount=123.5382,
    )
    dumped = pricing.model_dump(mode="json")
    assert dumped["base_amount"] == 100.46
    assert dumped["total_amount"] == 123.54


def test_booking_money_columns_are_numeric_12_2():
    for column in (
        "base_amount",
        "taxes_amount",
        "service_charges",
        "discount_amount",
        "total_amount",
        "refund_amount",
    ):
        col_type = getattr(Booking.__table__.c, column).type
        assert (col_type.precision, col_type.scale) == (12, 2), column


def test_agent_update_rejects_null_for_required_fields():
    with pytest.raises(ValidationError):
        AgentUpdate.model_validate({"name": None})
    with pytest.raises(ValidationError):
        AgentUpdate.model_validate({"is_available": None})
    assert AgentUpdate.model_validate({"contact_number": None}).model_fields_set == {
        "contact_number"
    }


def test_agent_availability_is_a_strict_body():
    assert AgentAvailabilityUpdate(is_available=False).is_available is False
    with pytest.raises(ValidationError):
        AgentAvailabilityUpdate.model_validate({"is_available": False, "extra": 1})


def test_swipe_write_bodies_are_strict():
    assert SwipeCreate(property_id=1, is_liked=True).is_liked is True
    with pytest.raises(ValidationError):
        SwipeCreate.model_validate({"property_id": 1, "is_liked": True, "match": True})
    with pytest.raises(ValidationError):
        BatchRemoveRequest.model_validate({"property_ids": [1], "extra": 1})
