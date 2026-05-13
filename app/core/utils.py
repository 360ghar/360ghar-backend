"""
Core utility functions.

Shared helper functions used across the application.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return the current UTC datetime serialized as ISO-8601."""
    return utc_now().isoformat()


def make_tz_aware(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware (UTC).

    Handles both naive and aware datetimes. If the datetime is naive
    (has no timezone info), it is assumed to be UTC and marked as such.

    Args:
        dt: A datetime object, which may be timezone-naive or aware.

    Returns:
        A timezone-aware datetime in UTC, or None if input is None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
