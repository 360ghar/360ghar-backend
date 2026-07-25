"""
Core utility functions.

Shared helper functions used across the application.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# Namespace for deterministic seed supabase_user_id values (UUID5).
_SEED_SUPABASE_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


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


def is_valid_uuid(value: str | None) -> bool:
    """True when ``value`` is a parseable UUID string (any version)."""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def seed_supabase_user_id(email: str) -> str:
    """Deterministic UUID for seed users before real Auth IDs exist.

    Must be a valid UUID so queries against ``auth.users.id`` and PostgREST
    UUID columns do not raise ``invalid input syntax for type uuid``. Prefer
    replacing with a real Auth UUID via ``seed_data/03_create_auth_users.py``.
    """
    normalized = (email or "").strip().lower()
    return str(uuid.uuid5(_SEED_SUPABASE_NS, f"360ghar-seed:{normalized}"))
