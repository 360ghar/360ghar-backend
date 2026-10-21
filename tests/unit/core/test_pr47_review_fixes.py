"""Small checks for the PR #47 review fixes."""

import pytest
from pydantic import ValidationError
from sqlalchemy import Integer, column
from sqlalchemy.dialects import postgresql

from app.core.cache.counters import FixedWindowCounters
from app.core.exceptions import ValidationException
from app.schemas.common import PrivacySettings
from app.schemas.custom_domain import normalize_domain
from app.schemas.pm_expense import ExpenseCreate
from app.services.property.helpers import derive_furnishing_level
from app.services.property.keyset import keyset_after
from app.services.tour_ai.floor_plan_ai import _unit_float


def test_unit_float_keeps_zero_and_clamps():
    assert _unit_float(0, 0.5) == 0.0
    assert _unit_float(0.0, 0.5) == 0.0
    assert _unit_float(None, 0.5) == 0.5
    assert _unit_float("x", 0.5) == 0.5
    assert _unit_float(1.7, 0.5) == 1.0
    assert _unit_float(-3, 0.5) == 0.0


def test_domain_with_trailing_newline_is_rejected():
    assert normalize_domain("Tours.Example.com") == "tours.example.com"
    with pytest.raises(ValueError):
        normalize_domain("tours.example.com\n")


def test_expense_amount_is_capped_at_numeric_12_2():
    base = {"property_id": 1, "category": "repairs", "expense_date": "2026-01-01"}
    ExpenseCreate(**base, amount=9_999_999_999.99)
    with pytest.raises(ValidationError):
        ExpenseCreate(**base, amount=10_000_000_000)


def test_non_string_room_furnishing_is_a_422_not_a_500():
    with pytest.raises(ValidationException):
        derive_furnishing_level({"rooms": [{"furnishing_level": ["furnished"]}]})


def test_legacy_profile_visibility_reads_as_private():
    assert PrivacySettings.model_validate({"profile_visibility": "friends"}).profile_visibility == "private"
    assert PrivacySettings.model_validate({}).profile_visibility == "public"


def test_keyset_after_handles_null_cursor_values():
    expr = column("k", Integer)
    specs = [(expr, Integer(), False)]
    sql = str(
        keyset_after(specs, False, [None], 5).compile(dialect=postgresql.dialect())
    )
    assert "IS NULL" in sql
    sql = str(keyset_after(specs, False, [3], 5).compile(dialect=postgresql.dialect()))
    assert "IS NULL" in sql  # ASC puts NULL last, so a NULL row comes after a value


def test_counters_never_evict_a_live_window():
    counters = FixedWindowCounters(max_counters=2)
    assert [counters.incr("a", 60) for _ in range(3)] == [1, 2, 3]
    counters.incr("b", 60)
    assert counters.incr("c", 60) == 1  # full of live windows: "c" is not stored
    assert counters.incr("c", 60) == 1
    assert counters.incr("a", 60) == 4  # an active window is untouched


def test_counters_delete_pattern():
    counters = FixedWindowCounters()
    counters.incr("endpoint_limit:x:1", 60)
    counters.incr("other", 60)
    assert counters.delete_pattern("endpoint_limit:*") == 1
    assert counters.incr("endpoint_limit:x:1", 60) == 1


def test_unit_float_survives_huge_ints():
    assert _unit_float(10**400, 0.5) == 0.5
