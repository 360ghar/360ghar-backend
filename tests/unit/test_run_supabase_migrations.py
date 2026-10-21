from __future__ import annotations

from scripts.run_supabase_migrations import _normalise_database_url


def test_raw_special_characters_are_encoded() -> None:
    url = "postgresql://user.ref:p@ss@db.example.com:6543/postgres"
    assert _normalise_database_url(url) == "postgresql://user.ref:p%40ss@db.example.com:6543/postgres"


def test_already_encoded_password_is_not_encoded_twice() -> None:
    url = "postgresql://user.ref:p%40ss@db.example.com:6543/postgres"
    assert _normalise_database_url(url) == url
