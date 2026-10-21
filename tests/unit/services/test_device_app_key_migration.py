"""The device_tokens.app_key migration does not backfill, and it allows NULL for legacy rows."""

from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20261014003000_device_tokens_app_key.sql"
)


def test_app_key_migration_has_no_blanket_backfill():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "UPDATE device_tokens" not in sql
    assert "SET NOT NULL" not in sql


def test_app_key_check_allows_legacy_null_rows():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "app_key IS NULL OR app_key IN ('ghar', 'estate', 'flatmates', 'stays')" in sql
