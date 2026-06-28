from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.utils import (
    can_manage_property,
    get_user_from_mcp_context,
    get_user_role,
    is_admin,
    is_agent,
    is_owner_or_above,
    serialize_booking,
    serialize_lease,
    serialize_maintenance_request,
    serialize_property_full,
    serialize_user_basic,
)


class _EnumLike:
    def __init__(self, value: str):
        self.value = value


def test_serialize_property_full_prefers_model_dump_when_available():
    class PydanticLike:
        def model_dump(self):
            return {"id": 10, "kind": "pydantic"}

    serialized = serialize_property_full(PydanticLike())
    assert serialized == {"id": 10, "kind": "pydantic"}


def test_serialize_property_full_handles_property_amenities_with_and_without_wrapper():
    prop = SimpleNamespace(
        id=1,
        title="Sea View",
        property_type=_EnumLike("apartment"),
        purpose=_EnumLike("rent"),
        status=_EnumLike("available"),
        city="Mumbai",
        locality="Bandra",
        full_address="Bandra West",
        base_price=100000.0,
        monthly_rent=25000.0,
        daily_rate=None,
        bedrooms=2,
        bathrooms=2,
        area_sqft=900.0,
        is_available=True,
        is_managed=True,
        management_status=_EnumLike("active"),
        latitude=19.0,
        longitude=72.0,
        main_image_url="https://example.com/main.jpg",
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        description="Nice property",
        sub_locality=None,
        landmark=None,
        pincode="400001",
        state="MH",
        country="India",
        price_per_sqft=None,
        security_deposit=50000.0,
        maintenance_charges=2500.0,
        balconies=1,
        parking_spaces=1,
        floor_number=5,
        total_floors=20,
        max_occupancy=4,
        age_of_property=2,
        virtual_tour_url=None,
        video_tour_url=None,
        features={"furnished": True},
        tags=["family"],
        available_from=date(2026, 3, 1),
        minimum_stay_days=1,
        owner_name="Owner",
        builder_name="Builder",
        view_count=3,
        like_count=1,
        payment_due_day=5,
        grace_period_days=7,
        images=[SimpleNamespace(image_url="https://example.com/1.jpg", caption="Front")],
        property_amenities=[
            SimpleNamespace(
                amenity=SimpleNamespace(id=11, title="Gym", icon="dumbbell", category="fitness")
            ),
            SimpleNamespace(id=12, title="Pool", icon="pool", category="recreation"),
        ],
        updated_at=datetime(2026, 2, 2, tzinfo=timezone.utc),
    )

    serialized = serialize_property_full(prop)

    assert serialized["amenities"][0]["id"] == 11
    assert serialized["amenities"][0]["title"] == "Gym"
    assert serialized["amenities"][1]["id"] == 12
    assert serialized["images"][0]["url"] == "https://example.com/1.jpg"


def test_serialize_booking_uses_enum_values():
    booking = SimpleNamespace(
        id=1,
        property_id=2,
        user_id=3,
        check_in_date=date(2026, 2, 10),
        check_out_date=date(2026, 2, 12),
        guests=2,
        nights=2,
        base_amount=1000,
        taxes_amount=100,
        service_charges=50,
        discount_amount=0,
        total_amount=1150,
        booking_status=_EnumLike("confirmed"),
        payment_status=_EnumLike("paid"),
        payment_method="upi",
        special_requests=None,
        cancellation_reason=None,
        cancellation_date=None,
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    serialized = serialize_booking(booking)
    assert serialized["booking_status"] == "confirmed"
    assert serialized["payment_status"] == "paid"


def test_serialize_lease_maps_new_fields():
    lease = SimpleNamespace(
        id=1,
        property_id=9,
        owner_id=5,
        tenant_user_id=7,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        monthly_rent=25000,
        security_deposit=50000,
        status=_EnumLike("active"),
        payment_due_day=1,
        grace_period_days=5,
        late_fee_amount=500,
        late_fee_percentage=2.5,
        lease_terms="No smoking",
        special_clauses="Pets allowed",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    serialized = serialize_lease(lease)
    assert serialized["late_fee_amount"] == 500
    assert serialized["late_fee_percentage"] == 2.5
    assert serialized["terms"] == "No smoking"
    assert serialized["notes"] == "Pets allowed"


def test_serialize_maintenance_request_maps_emergency_to_urgent_and_completed_status():
    req = SimpleNamespace(
        id=1,
        property_id=5,
        lease_id=9,
        tenant_user_id=7,
        title="Leak",
        description="Pipe leak",
        category=_EnumLike("plumbing"),
        urgency=_EnumLike("emergency"),
        request_status=_EnumLike("open"),
        work_order_status=_EnumLike("in_progress"),
        estimated_cost=1200,
        actual_cost=None,
        scheduled_for=datetime(2026, 2, 21, tzinfo=timezone.utc),
        completed_at=None,
        vendor_name="ACME",
        completion_notes=None,
        created_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 2, 21, tzinfo=timezone.utc),
    )

    serialized = serialize_maintenance_request(req)
    assert serialized["priority"] == "urgent"
    assert serialized["status"] == "scheduled"


def test_role_and_property_permission_helpers():
    admin = SimpleNamespace(id=1, role="admin")
    agent = SimpleNamespace(id=2, role="agent")
    user = SimpleNamespace(id=3, role="user")
    unknown = SimpleNamespace(id=4, role="mystery")

    assert get_user_role(admin).value == "admin"
    assert get_user_role(unknown).value == "user"
    assert is_admin(admin) is True
    assert is_agent(agent) is True
    assert is_owner_or_above(user) is True
    assert can_manage_property(admin, property_owner_id=999) is True
    assert can_manage_property(user, property_owner_id=3) is True
    assert can_manage_property(user, property_owner_id=4) is False


@pytest.mark.asyncio
async def test_get_user_from_mcp_context_returns_none_for_invalid_auth_context():
    db = AsyncMock()

    with patch("app.mcp.utils.get_auth_access_token", return_value=None):
        assert await get_user_from_mcp_context(db) is None

    with patch(
        "app.mcp.utils.get_auth_access_token",
        return_value=SimpleNamespace(),
    ):
        assert await get_user_from_mcp_context(db) is None

    with patch(
        "app.mcp.utils.get_auth_access_token",
        return_value=SimpleNamespace(claims={"auth_method": "supabase", "sub": "1"}),
    ):
        assert await get_user_from_mcp_context(db) is None

    with patch(
        "app.mcp.utils.get_auth_access_token",
        return_value=SimpleNamespace(claims={"auth_method": "oauth"}),
    ):
        assert await get_user_from_mcp_context(db) is None

    with patch(
        "app.mcp.utils.get_auth_access_token",
        return_value=SimpleNamespace(claims={"auth_method": "oauth", "sub": "abc"}),
    ):
        assert await get_user_from_mcp_context(db) is None


@pytest.mark.asyncio
async def test_get_user_from_mcp_context_calls_user_lookup_for_valid_oauth_claims():
    db = AsyncMock()
    user = SimpleNamespace(id=42, role="user")

    with (
        patch(
            "app.mcp.utils.get_auth_access_token",
            return_value=SimpleNamespace(claims={"auth_method": "oauth", "sub": "42"}),
        ),
        patch("app.mcp.utils.get_user_by_id", new=AsyncMock(return_value=user)) as mock_get_user,
    ):
        result = await get_user_from_mcp_context(db)

    assert result is user
    mock_get_user.assert_awaited_once_with(db, 42)


@pytest.mark.asyncio
async def test_get_user_from_mcp_context_handles_unknown_user_and_user_id_claim():
    db = AsyncMock()

    with (
        patch(
            "app.mcp.utils.get_auth_access_token",
            return_value=SimpleNamespace(claims={"auth_method": "oauth", "user_id": "88"}),
        ),
        patch("app.mcp.utils.get_user_by_id", new=AsyncMock(return_value=None)) as mock_get_user,
    ):
        result = await get_user_from_mcp_context(db)

    assert result is None
    mock_get_user.assert_awaited_once_with(db, 88)


def test_serialize_property_full_handles_missing_optional_fields_gracefully():
    prop = SimpleNamespace(
        id=1,
        title="Bare",
        property_type=None,
        purpose=None,
        status=None,
        city=None,
        locality=None,
        full_address=None,
        base_price=0,
        monthly_rent=None,
        daily_rate=None,
        bedrooms=None,
        bathrooms=None,
        area_sqft=None,
        is_available=True,
        is_managed=False,
        management_status=None,
        latitude=None,
        longitude=None,
        main_image_url=None,
        created_at=None,
        description=None,
    )

    serialized = serialize_property_full(prop)
    assert serialized["management_status"] is None
    assert serialized["images"] == []
    assert serialized["amenities"] == []
    assert serialized["available_from"] is None


def test_serialize_booking_and_lease_handle_none_enum_and_numeric_fields():
    booking = SimpleNamespace(
        id=1,
        property_id=2,
        user_id=3,
        check_in_date=None,
        check_out_date=None,
        guests=None,
        nights=None,
        base_amount=None,
        taxes_amount=None,
        service_charges=None,
        discount_amount=None,
        total_amount=None,
        booking_status=None,
        payment_status=None,
        payment_method=None,
        special_requests=None,
        cancellation_reason=None,
        cancellation_date=None,
        created_at=None,
    )
    lease = SimpleNamespace(
        id=1,
        property_id=2,
        owner_id=None,
        tenant_user_id=None,
        start_date=None,
        end_date=None,
        monthly_rent=None,
        security_deposit=None,
        status=None,
        payment_due_day=None,
        grace_period_days=None,
        late_fee_amount=None,
        late_fee_percentage=None,
        lease_terms=None,
        special_clauses=None,
        created_at=None,
        updated_at=None,
    )

    serialized_booking = serialize_booking(booking)
    serialized_lease = serialize_lease(lease)
    assert serialized_booking["booking_status"] is None
    assert serialized_booking["total_amount"] == 0.0
    assert serialized_lease["status"] is None
    assert serialized_lease["monthly_rent"] == 0.0


@pytest.mark.parametrize(
    ("request_status", "work_order_status", "scheduled_for", "completed_at", "expected_status"),
    [
        ("open", "cancelled", None, None, "cancelled"),
        ("resolved", None, None, None, "completed"),
        ("open", None, None, datetime(2026, 2, 21, tzinfo=timezone.utc), "completed"),
        ("open", "in_progress", None, None, "in_progress"),
        ("open", None, None, None, "open"),
    ],
)
def test_serialize_maintenance_request_status_mapping_branches(
    request_status,
    work_order_status,
    scheduled_for,
    completed_at,
    expected_status,
):
    req = SimpleNamespace(
        id=2,
        property_id=5,
        lease_id=9,
        tenant_user_id=7,
        title="Issue",
        description="Desc",
        category=_EnumLike("plumbing"),
        urgency=_EnumLike("high"),
        request_status=_EnumLike(request_status) if request_status else None,
        work_order_status=_EnumLike(work_order_status) if work_order_status else None,
        estimated_cost=None,
        actual_cost=None,
        scheduled_for=scheduled_for,
        completed_at=completed_at,
        vendor_name=None,
        completion_notes=None,
        created_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 2, 21, tzinfo=timezone.utc),
    )

    serialized = serialize_maintenance_request(req)
    assert serialized["priority"] == "high"
    assert serialized["status"] == expected_status


def test_serialize_user_basic_defaults():
    user = SimpleNamespace(id=1)
    serialized = serialize_user_basic(user)
    assert serialized["role"] == "user"
    assert serialized["full_name"] is None
