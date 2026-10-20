"""Engagement migrations: the statements that the contract depends on.

These read the migration text. The migrated-database drift check (CI) confirms the
effect on a real database.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.bookings import Booking

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _sql(name: str) -> str:
    return (MIGRATIONS_DIR / name).read_text(encoding="utf-8")


def test_message_thread_type_is_dropped_and_no_migration_types_a_column_with_it() -> None:
    dropping = [
        path.name
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if re.search(
            r"drop\s+type\s+(if\s+exists\s+)?message_thread_type\b",
            path.read_text(encoding="utf-8"),
            re.I,
        )
    ]
    assert dropping == ["20261014004005_drop_message_thread_type.sql"]

    # Strip comments, then the CREATE and DROP statements. Any other mention is a column or a cast.
    typed: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        text = re.sub(r"create\s+type\s+message_thread_type\b[^;]*;", "", text, flags=re.I)
        text = re.sub(
            r"drop\s+type\s+(if\s+exists\s+)?message_thread_type\b[^;]*;", "", text, flags=re.I
        )
        if re.search(r"\bmessage_thread_type\b", text, re.I):
            typed.append(path.name)
    assert typed == []


def test_booking_money_columns_are_numeric_12_2_in_orm_and_migration() -> None:
    money = [
        "base_amount",
        "taxes_amount",
        "service_charges",
        "discount_amount",
        "total_amount",
        "refund_amount",
    ]
    migration = _sql("20261014004001_booking_money_precision.sql")
    for column in money:
        assert re.search(rf"{column}\s+TYPE\s+NUMERIC\(12,\s*2\)", migration), column
        col_type = Booking.__table__.c[column].type
        assert (col_type.precision, col_type.scale) == (12, 2), column
