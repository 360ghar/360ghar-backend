from datetime import datetime, timezone

from app.services.property.search import (
    IST_TZ,
    _available_from_minimum,
    _move_in_window,
)


def _ist(day: int, month: int = 5, year: int = 2026) -> datetime:
    """Midnight (start of day) in IST, expressed in UTC."""
    return datetime(year, month, day, tzinfo=IST_TZ).astimezone(timezone.utc)


def test_move_in_immediate_window_includes_today_and_next_seven_days():
    # 13:30 UTC == 19:00 IST on the 7th; the day boundary is IST midnight.
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("immediate", now=now) == (
        None,
        _ist(15),
    )


def test_move_in_this_month_window_ends_at_next_month_start():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("this_month", now=now) == (
        None,
        datetime(2026, 6, 1, tzinfo=IST_TZ).astimezone(timezone.utc),
    )


def test_move_in_within_one_week_window():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("within_1_week", now=now) == (
        None,
        _ist(15),
    )
    assert _move_in_window("within_a_week", now=now) == (
        None,
        _ist(15),
    )


def test_move_in_within_two_weeks_window():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("within_2_weeks", now=now) == (
        None,
        _ist(22),
    )


def test_move_in_within_one_month_window_is_rolling():
    # Late in the month, "within 1 month" must still mean ~30 days, not
    # "until the end of this calendar month".
    now = datetime(2026, 5, 28, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("within_1_month", now=now) == (
        None,
        _ist(27, month=6),
    )
    assert _move_in_window("within_a_month", now=now) == (
        None,
        _ist(27, month=6),
    )


def test_move_in_within_two_months_window_is_rolling():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("within_2_months", now=now) == (
        None,
        _ist(6, month=7),
    )
    assert _move_in_window("two_months", now=now) == (
        None,
        _ist(6, month=7),
    )


def test_move_in_within_three_months_window_is_rolling():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("within_3_months", now=now) == (
        None,
        _ist(5, month=8),
    )
    assert _move_in_window("three_months", now=now) == (
        None,
        _ist(5, month=8),
    )


def test_move_in_rolling_windows_wrap_calendar_year():
    now = datetime(2026, 12, 5, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("within_2_months", now=now) == (
        None,
        _ist(3, month=2, year=2027),
    )
    assert _move_in_window("within_3_months", now=now) == (
        None,
        _ist(5, month=3, year=2027),
    )


def test_move_in_next_month_window_uses_calendar_month_boundaries():
    now = datetime(2026, 12, 20, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("next_month", now=now) == (
        datetime(2027, 1, 1, tzinfo=IST_TZ).astimezone(timezone.utc),
        datetime(2027, 2, 1, tzinfo=IST_TZ).astimezone(timezone.utc),
    )


def test_move_in_flexible_and_unknown_values_do_not_filter():
    now = datetime(2026, 5, 7, 13, 30, tzinfo=timezone.utc)

    assert _move_in_window("flexible", now=now) is None
    assert _move_in_window("unknown_catalog_value", now=now) is None


def test_move_in_before_ist_midnight_uses_previous_ist_day():
    # 20:00 UTC == 01:30 IST the next day; the IST day boundary is what
    # counts, so "today" is the 8th, not the 7th.
    now = datetime(2026, 5, 7, 20, 0, tzinfo=timezone.utc)

    assert _move_in_window("within_1_week", now=now) == (
        None,
        _ist(16),
    )


def test_available_from_minimum_parses_date_at_ist_day_start():
    assert _available_from_minimum("2026-05-07") == datetime(
        2026,
        5,
        6,
        18,
        30,
        tzinfo=timezone.utc,
    )
