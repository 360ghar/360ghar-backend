"""
Tests for app.core.utils module.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.utils import make_tz_aware, utc_now, utc_now_iso


class TestUtcNow:
    """Tests for utc_now function."""

    def test_returns_timezone_aware_datetime(self):
        result = utc_now()
        assert result.tzinfo is not None

    def test_returns_utc_timezone(self):
        result = utc_now()
        assert result.tzinfo == timezone.utc

    def test_returns_recent_time(self):
        before = datetime.now(timezone.utc)
        result = utc_now()
        after = datetime.now(timezone.utc)
        assert before <= result <= after


class TestUtcNowIso:
    """Tests for utc_now_iso function."""

    def test_returns_string(self):
        result = utc_now_iso()
        assert isinstance(result, str)

    def test_is_parseable_as_iso8601(self):
        result = utc_now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None


class TestMakeTzAware:
    """Tests for make_tz_aware function."""

    def test_none_returns_none(self):
        assert make_tz_aware(None) is None

    def test_naive_datetime_gets_utc(self):
        naive = datetime(2025, 1, 15, 10, 30, 0)
        result = make_tz_aware(naive)
        assert result.tzinfo == timezone.utc
        assert result.year == 2025
        assert result.hour == 10

    def test_aware_datetime_stays_in_utc(self):
        aware = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = make_tz_aware(aware)
        assert result.tzinfo == timezone.utc
        assert result == aware

    def test_non_utc_timezone_converted_to_utc(self):
        # IST is UTC+5:30
        ist = timezone(timedelta(hours=5, minutes=30))
        ist_dt = datetime(2025, 1, 15, 16, 0, 0, tzinfo=ist)
        result = make_tz_aware(ist_dt)
        assert result.tzinfo == timezone.utc
        # 16:00 IST = 10:30 UTC
        assert result.hour == 10
        assert result.minute == 30

    @pytest.mark.parametrize(
        "year,month,day,hour",
        [
            (2024, 1, 1, 0),
            (2025, 6, 15, 12),
            (2025, 12, 31, 23),
        ],
    )
    def test_various_naive_dates(self, year, month, day, hour):
        naive = datetime(year, month, day, hour, 0, 0)
        result = make_tz_aware(naive)
        assert result.tzinfo == timezone.utc
        assert result.year == year
        assert result.hour == hour
