"""Property schema, visibility allowlist, keyset helpers and column types (no database)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import Float, Numeric
from sqlalchemy.dialects import postgresql

from app.core.exceptions import BadRequestException
from app.models.enums import PropertyPurpose, PropertyStatus, PropertyType
from app.models.properties import Property
from app.schemas.pagination import validate_keyset_payload
from app.schemas.property import (
    BASE_PRICE_MAX,
    PropertyCreate,
    PropertyFields,
    PropertyInDB,
    PropertyUpdate,
)
from app.services.property.keyset import keyset_after, read_cursor_key
from app.services.visibility import (
    PUBLIC_LISTING_PREFERENCE_KEYS,
    Viewer,
    mask_listing_preferences,
    public_listing_preferences,
)

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


def _create(**overrides):
    data = {
        "title": "Flat",
        "property_type": PropertyType.apartment,
        "purpose": PropertyPurpose.buy,
        "base_price": 1000,
    }
    data.update(overrides)
    return PropertyCreate(**data)


class TestWriteShape:
    def test_create_and_update_share_one_field_base(self):
        assert issubclass(PropertyCreate, PropertyFields)
        assert issubclass(PropertyUpdate, PropertyFields)
        assert set(PropertyUpdate.model_fields) == set(PropertyFields.model_fields)

    def test_patch_sends_only_the_keys_the_client_set(self):
        assert PropertyUpdate().model_dump(exclude_unset=True) == {}
        body = PropertyUpdate(title="New title")
        assert body.model_fields_set == {"title"}

    @pytest.mark.parametrize(
        "field",
        ["title", "property_type", "purpose", "base_price", "status", "is_available", "country"],
    )
    def test_explicit_null_on_a_required_field_is_rejected_on_patch(self, field):
        with pytest.raises(ValidationError):
            PropertyUpdate(**{field: None})

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(ValidationError):
            PropertyUpdate(unknown_key=1)

    def test_base_price_cap_is_the_numeric_12_2_ceiling(self):
        assert BASE_PRICE_MAX == 9_999_999_999.99
        assert _create(base_price=BASE_PRICE_MAX).base_price == BASE_PRICE_MAX

    def test_base_price_above_the_cap_is_rejected_on_create(self):
        with pytest.raises(ValidationError):
            _create(base_price=10_000_000_000)

    def test_base_price_above_the_cap_is_rejected_on_patch(self):
        with pytest.raises(ValidationError):
            PropertyUpdate(base_price=10_000_000_000)

    def test_money_is_rounded_to_two_places(self):
        assert _create(base_price="12.345").base_price == 12.35

    @pytest.mark.parametrize("latitude", [90.5, -91])
    def test_latitude_bounds(self, latitude):
        with pytest.raises(ValidationError):
            PropertyUpdate(latitude=latitude)

    @pytest.mark.parametrize("longitude", [180.5, -181])
    def test_longitude_bounds(self, longitude):
        with pytest.raises(ValidationError):
            PropertyUpdate(longitude=longitude)

    def test_available_from_is_a_date_not_a_string(self):
        body = PropertyUpdate(available_from="2026-11-01")
        assert body.available_from.isoformat() == "2026-11-01"
        with pytest.raises(ValidationError):
            PropertyUpdate(available_from="next week")

    def test_price_per_sqft_is_not_a_write_field(self):
        assert "price_per_sqft" not in PropertyFields.model_fields
        with pytest.raises(ValidationError):
            _create(price_per_sqft=10)


def _out(**overrides):
    data = {
        "id": 1,
        "owner_id": 2,
        "title": "Flat",
        "property_type": PropertyType.apartment,
        "purpose": PropertyPurpose.buy,
        "status": PropertyStatus.available,
        "base_price": 5_000_000,
        "area_sqft": 1000,
        "is_available": True,
        "view_count": 0,
        "like_count": 0,
        "interest_count": 0,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    data.update(overrides)
    return data


class TestOutputShape:
    def test_price_per_sqft_is_computed_from_the_purpose_price(self):
        assert PropertyInDB(**_out()).price_per_sqft == 5000.0
        rent = PropertyInDB(**_out(purpose="rent", monthly_rent=25000))
        assert rent.price_per_sqft == 25.0
        assert rent.nightly_rate is None

    def test_nightly_rate_is_the_daily_rate_for_short_stays(self):
        short = PropertyInDB(**_out(purpose="short_stay", base_price=4000, daily_rate=4000))
        assert short.nightly_rate == 4000
        assert short.price_per_sqft == 4.0

    def test_no_area_means_no_price_per_sqft(self):
        assert PropertyInDB(**_out(area_sqft=None)).price_per_sqft is None

    def test_object_features_are_not_read(self):
        # Object-form rows are converted by migration 20261014001001. The read path has no branch for them.
        listing = PropertyInDB(**_out(features={"lift": False, "facing": "north", "gym": True}))
        assert listing.features is None

    def test_list_features_are_read_as_strings(self):
        listing = PropertyInDB(**_out(features=["facing", "gym"]))
        assert listing.features == ["facing", "gym"]

    def test_features_migration_drops_false_values(self):
        files = sorted(MIGRATIONS.glob("20261014001001_*.sql"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "jsonb_typeof(p.features) = 'object'" in text
        assert "'false'::jsonb" in text

    def test_legacy_furnishing_value_is_normalized_on_output(self):
        listing = PropertyInDB(**_out(furnishing_level="fully-furnished"))
        assert listing.furnishing_level.value == "furnished"

    def test_available_from_datetime_becomes_the_utc_date(self):
        listing = PropertyInDB(**_out(available_from=datetime(2026, 11, 1, tzinfo=UTC)))
        assert listing.available_from.isoformat() == "2026-11-01"

    def test_timestamps_end_with_z(self):
        dumped = PropertyInDB(**_out()).model_dump(mode="json")
        assert dumped["created_at"].endswith("Z")

    def test_property_schema_has_floor_plans_and_no_wire_price_input(self):
        from app.schemas.property import Property as PropertySchema

        assert "floor_plans" in PropertySchema.model_fields


class TestListingPreferenceAllowlist:
    def test_allowlist_has_no_moderator_key(self):
        moderator_keys = {
            "moderated_by",
            "moderated_at",
            "moderation_reason",
            "ai_prescreen_flags",
            "ai_prescreen_reason",
            "ai_prescreened_by",
            "auto_paused_reason",
            "room_poster_review_required",
            "owner_status_updated_at",
        }
        assert not moderator_keys & PUBLIC_LISTING_PREFERENCE_KEYS

    def test_public_keys_are_kept_and_moderator_keys_removed(self):
        raw = {"pets": "no", "moderated_by": 9, "society_type": "gated", "moderation_reason": "x"}
        assert public_listing_preferences(raw) == {"pets": "no", "society_type": "gated"}

    def test_non_admin_viewer_gets_the_allowlist(self):
        prop = {"id": 1, "listing_preferences": {"pets": "yes", "moderated_by": 9}}
        masked = mask_listing_preferences(prop, Viewer(user=SimpleNamespace(id=5)))
        assert masked["listing_preferences"] == {"pets": "yes"}

    def test_admin_viewer_keeps_everything(self):
        prop = {"id": 1, "listing_preferences": {"pets": "yes", "moderated_by": 9}}
        admin = Viewer(user=SimpleNamespace(id=5), is_admin=True)
        assert mask_listing_preferences(prop, admin) is prop

    def test_pydantic_listing_keeps_its_model_type(self):
        from app.schemas.property import ListingPreferences
        from app.schemas.property import Property as PropertySchema

        prefs = ListingPreferences.model_validate({"pets": "yes", "moderated_by": 9})
        listing = SimpleNamespace(listing_preferences=prefs)
        masked = mask_listing_preferences(listing, Viewer(user=SimpleNamespace(id=5)))
        assert isinstance(masked.listing_preferences, ListingPreferences)
        assert "moderated_by" not in masked.listing_preferences.model_dump()
        assert PropertySchema is not None


class TestKeysetHelpers:
    def test_two_key_predicate_is_a_lexicographic_or(self):
        specs = [(Property.like_count, Float(), True), (Property.created_at, Float(), True)]
        predicate = keyset_after(specs, True, [3, 1.5], 7)
        text = str(predicate.compile(dialect=postgresql.dialect()))
        assert " OR " in text
        assert "properties.id <" in text

    def test_cursor_shape_must_match_the_sort(self):
        assert read_cursor_key({"v": 1, "k": [[5], 9]}, ["number"]) == ([5], 9)
        assert read_cursor_key({}, ["number"]) is None
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": [[5, 6], 9]}, ["number"])
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": ["x", 9]}, ["number"])

    def test_cursor_value_types_must_match_the_sort_keys(self):
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": [["abc"], 9]}, ["number"])
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": [["not-a-date"], 9]}, ["datetime"])
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": [[5], "x"]}, ["number"])
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": [[5], True]}, ["number"])
        assert read_cursor_key({"v": 1, "k": [[None], 9]}, ["number"]) == ([None], 9)

    @pytest.mark.parametrize(
        ("key", "kinds"),
        [
            ([[3_000_000_000], 9], ["int4"]),  # above the int4 range
            ([[-3_000_000_000], 9], ["int4"]),  # below the int4 range
            ([[True], 9], ["int4"]),  # a bool is not an integer
            ([[1], 2**63], ["int4"]),  # the id is checked against int8
            ([[float("nan")], 9], ["number"]),
            ([[float("inf")], 9], ["number"]),
            ([[-float("inf")], 9], ["number"]),
            ([[10**400], 9], ["number"]),  # too large for a float
            ([["2024-W01-1"], 9], ["datetime"]),  # week date: Python accepts, Postgres does not
            ([["2024-02-30T00:00:00Z"], 9], ["datetime"]),  # not a calendar date
            ([["9999-12-31T23:59:59-05:00"], 9], ["datetime"]),  # year 10000 in UTC
            ([["2024-01-01T10:00:00.1234567"], 9], ["datetime"]),  # more than 6 fraction digits
        ],
    )
    def test_cursor_values_outside_their_sql_range_are_rejected(self, key, kinds):
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": key}, kinds)

    @pytest.mark.parametrize(
        "value", ["2024-01-01", "2024-01-01T10:00:00Z", "2026-10-14T10:00:00.123456+00:00"]
    )
    def test_postgres_datetime_forms_are_accepted(self, value):
        assert read_cursor_key({"v": 1, "k": [[value], 9]}, ["datetime"]) == ([value], 9)

    def test_null_sort_value_is_a_position_but_null_id_is_not(self):
        # A NULL sort value stays a valid position for every kind, as before the fix round.
        assert read_cursor_key({"v": 1, "k": [[None], 9]}, ["int4"]) == ([None], 9)
        with pytest.raises(BadRequestException):
            read_cursor_key({"v": 1, "k": [[1], None]}, ["int4"])

    def test_integer_bounds_are_inclusive(self):
        high = {"v": 1, "k": [[2**31 - 1], 2**63 - 1]}
        low = {"v": 1, "k": [[-(2**31)], 0]}
        assert read_cursor_key(high, ["int4"]) == ([2**31 - 1], 2**63 - 1)
        assert read_cursor_key(low, ["int4"]) == ([-(2**31)], 0)

    def test_single_key_payload_needs_a_key_and_an_id_in_range(self):
        validate_keyset_payload({}, "text")  # no cursor sent: the first page
        with pytest.raises(BadRequestException):
            validate_keyset_payload({"v": 1}, "text")
        with pytest.raises(BadRequestException):
            validate_keyset_payload({"v": 1, "k": ["a", 2**31]}, "text", id_kind="int4")
        validate_keyset_payload({"v": 1, "k": ["a", 2**31]}, "text")  # int8 id is in range

    def test_numeric_key_casts_to_numeric(self):
        specs = [(Property.base_price, Numeric(), False)]
        text = str(keyset_after(specs, False, [100.0], 3).compile(dialect=postgresql.dialect()))
        assert "CAST" in text.upper()


# These classes read the ORM metadata, which create_all builds in the test schema. They do not
# prove a migration. The database guard is the CI drift gate, scripts/verify_schema_drift.py.
class TestColumnTypes:
    def test_columns_the_response_requires_are_not_null(self):
        # Migration 20261014001004 sets NOT NULL in the database for these columns.
        for name in ("status", "country", "minimum_stay_days", "is_available", "is_managed"):
            assert Property.__table__.c[name].nullable is False, name

    def test_money_columns_are_numeric_12_2(self):
        for name in (
            "base_price",
            "price_per_sqft",
            "monthly_rent",
            "daily_rate",
            "security_deposit",
            "maintenance_charges",
            "setup_cost",
            "other_charges",
        ):
            column_type = Property.__table__.c[name].type
            assert column_type.precision == 12, name
            assert column_type.scale == 2, name

    def test_coordinates_are_double_precision(self):
        for name in ("latitude", "longitude"):
            column_type = Property.__table__.c[name].type
            assert isinstance(column_type, Float)
            assert column_type.precision is None or column_type.precision > 24

    def test_money_migration_exists_and_casts_to_numeric_12_2(self):
        files = sorted(MIGRATIONS.glob("20261014001000_*.sql"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "NUMERIC(12,2)" in text
        assert "DOUBLE PRECISION" in text
        assert "base_price" in text
