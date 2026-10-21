"""MCP outputs use the REST encodings: UTC datetimes with Z, money as JSON numbers."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.mcp.utils import serialize_property_basic, utc_iso


def test_utc_iso_writes_z_for_aware_and_naive_datetimes():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert utc_iso(datetime(2026, 10, 20, 10, 0, tzinfo=ist)) == "2026-10-20T04:30:00Z"
    assert utc_iso(datetime(2026, 10, 20, 4, 30, tzinfo=UTC)) == "2026-10-20T04:30:00Z"
    assert utc_iso(datetime(2026, 10, 20, 4, 30)) == "2026-10-20T04:30:00Z"


def test_utc_iso_keeps_date_only_values_and_none():
    assert utc_iso(date(2026, 10, 20)) == "2026-10-20"
    assert utc_iso(None) is None


def test_orm_decimal_money_serializes_as_json_number():
    prop = SimpleNamespace(
        id=1,
        title="Flat",
        city="Pune",
        locality="Baner",
        latitude=18.5,
        longitude=73.8,
        main_image_url=None,
        base_price=Decimal("5000.00"),
        monthly_rent=Decimal("12000.50"),
        daily_rate=Decimal("1500"),
        created_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )

    out = serialize_property_basic(prop)

    assert out["base_price"] == 5000.0 and isinstance(out["base_price"], float)
    assert out["monthly_rent"] == 12000.5
    assert out["daily_rate"] == 1500.0 and isinstance(out["daily_rate"], float)
    assert out["created_at"] == "2026-10-01T12:00:00Z"


def test_full_property_emits_the_detail_widget_fields_from_their_sources():
    from app.mcp.utils import serialize_property_full

    prop = SimpleNamespace(
        id=1,
        title="Flat",
        city="Pune",
        locality="Baner",
        latitude=18.5,
        longitude=73.8,
        main_image_url=None,
        base_price=Decimal("5000"),
        description="d",
        furnishing_level="furnished",
        age_of_property=7,
        owner_contact="+91-9000000000",
        owner_id=1,
        created_at=None,
        updated_at=None,
        available_from=None,
    )

    out = serialize_property_full(prop, viewer=SimpleNamespace(id=1, role="user"))

    assert out["furnished_status"] == "furnished"
    assert out["age_years"] == 7
    assert out["owner_phone"] == "+91-9000000000"
    assert "facing" not in out


def test_owner_phone_is_masked_for_anonymous_and_other_viewers():
    from app.mcp.utils import serialize_property_full

    prop = SimpleNamespace(
        id=1,
        title="Flat",
        city="Pune",
        locality="Baner",
        latitude=18.5,
        longitude=73.8,
        main_image_url=None,
        base_price=Decimal("5000"),
        description="d",
        owner_contact="+91-9000000000",
        owner_id=1,
        created_at=None,
        updated_at=None,
        available_from=None,
    )

    # No viewer is anonymous; a non-owner user is not the owner. Neither sees the owner number.
    assert serialize_property_full(prop)["owner_phone"] != "+91-9000000000"
    stranger = SimpleNamespace(id=2, role="user")
    assert serialize_property_full(prop, viewer=stranger)["owner_phone"] != "+91-9000000000"
