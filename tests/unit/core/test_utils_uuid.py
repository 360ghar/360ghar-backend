"""UUID helpers for seed ids and runtime guards."""

from __future__ import annotations

from app.core.utils import is_valid_uuid, seed_supabase_user_id


def test_is_valid_uuid_accepts_canonical() -> None:
    assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True


def test_is_valid_uuid_rejects_seed_email_placeholder() -> None:
    assert is_valid_uuid("seed-karan.chauhan50@gmail.com") is False
    assert is_valid_uuid(None) is False
    assert is_valid_uuid("") is False


def test_seed_supabase_user_id_is_stable_uuid() -> None:
    a = seed_supabase_user_id("Karan.Chauhan50@gmail.com")
    b = seed_supabase_user_id("karan.chauhan50@gmail.com")
    assert a == b
    assert is_valid_uuid(a) is True
