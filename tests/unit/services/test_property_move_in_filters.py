from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.enums import MoveInTimeline
from app.repositories.property_query_builder import (
    IST_TZ,
    available_from_minimum,
    move_in_window,
)
from app.schemas.property import UnifiedPropertyFilter


def _ist(day: int, month: int = 5, year: int = 2026) -> datetime:
    """Midnight (start of day) in IST, expressed in UTC."""
    return datetime(year, month, day, tzinfo=IST_TZ).astimezone(timezone.utc)


def test_move_in_immediate_window_includes_today_and_next_seven_days():
    # 13:30 UTC == 19:00 IST on the 7th; the day boundary is IST midnight.
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("immediate", now=now) == (
        None,
        _ist(15),
    )


def test_move_in_this_month_window_ends_at_next_month_start():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("this_month", now=now) == (
        None,
        datetime(2026, 6, 1, tzinfo=IST_TZ).astimezone(timezone.utc),
    )


def test_move_in_within_one_week_window():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("within_1_week", now=now) == (
        None,
        _ist(15),
    )


def test_move_in_within_two_weeks_window():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("within_2_weeks", now=now) == (
        None,
        _ist(22),
    )


def test_move_in_within_one_month_window_is_rolling():
    # Late in the month, "within 1 month" must still mean ~30 days, not
    # "until the end of this calendar month".
    now = datetime(2026, 5, 28, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("within_1_month", now=now) == (
        None,
        _ist(27, month=6),
    )


def test_move_in_within_two_months_window_is_rolling():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("within_2_months", now=now) == (
        None,
        _ist(6, month=7),
    )


def test_move_in_within_three_months_window_is_rolling():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("within_3_months", now=now) == (
        None,
        _ist(5, month=8),
    )


def test_move_in_rolling_windows_wrap_calendar_year():
    now = datetime(2026, 12, 5, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("within_2_months", now=now) == (
        None,
        _ist(3, month=2, year=2027),
    )
    assert move_in_window("within_3_months", now=now) == (
        None,
        _ist(5, month=3, year=2027),
    )


def test_move_in_next_month_window_uses_calendar_month_boundaries():
    now = datetime(2026, 12, 20, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("next_month", now=now) == (
        datetime(2027, 1, 1, tzinfo=IST_TZ).astimezone(timezone.utc),
        datetime(2027, 2, 1, tzinfo=IST_TZ).astimezone(timezone.utc),
    )


def test_move_in_flexible_does_not_filter():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert move_in_window("flexible", now=now) is None
    assert move_in_window(MoveInTimeline.flexible, now=now) is None


def test_move_in_before_ist_midnight_uses_previous_ist_day():
    # 20:00 UTC == 01:30 IST the next day; the IST day boundary is what
    # counts, so "today" is the 8th, not the 7th.
    now = datetime(2026, 5, 7, 20, 0, tzinfo=timezone.utc)

    assert move_in_window("within_1_week", now=now) == (
        None,
        _ist(16),
    )


def test_available_from_minimum_parses_date_at_ist_day_start():

    assert available_from_minimum(date(2026, 5, 7)) == datetime(
        2026,
        5,
        6,
        18,
        30,
        tzinfo=timezone.utc,
    )


def test_retired_move_in_aliases_are_rejected():
    # The client sends only canonical values. Anything else is a 422, not a silent no-op.
    with pytest.raises(ValueError):
        MoveInTimeline("within_a_week")
    with pytest.raises(ValidationError):
        UnifiedPropertyFilter(move_in="unknown_catalog_value")
    assert UnifiedPropertyFilter(move_in="within_1_week").move_in == MoveInTimeline.within_1_week
