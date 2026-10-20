"""Drift gate rules for missing tables and extra columns. No database needed."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from scripts.verify_schema_drift import (
    MISSING_TABLE_EXEMPTIONS,
    _check_table,
    _db_family,
    _extra_column_lines,
    _model_family,
    _table_presence,
)

EXEMPT = sorted(MISSING_TABLE_EXEMPTIONS)


def _db_col(family: str, **kw: Any) -> dict[str, Any]:
    return {
        "family": family,
        "nullable": kw.get("nullable", True),
        "length": kw.get("length"),
        "precision": kw.get("precision"),
        "scale": kw.get("scale"),
        "has_default": True,
    }


def _check(
    type_: sa.types.TypeEngine[Any], db_column: dict[str, Any], name: str = "n"
) -> list[str]:
    """Run the per-table check for one model column type against one DB column."""
    table = sa.Table(
        "t",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(name, type_),
    )
    db = {
        "columns": {("t", "id"): _db_col("int4", nullable=False), ("t", name): db_column},
        "enum_labels": {},
        "unique": {},
        "fks": {},
        "checks": {},
    }
    return _check_table(table, db)


def test_integer_widths_are_distinct_families() -> None:
    assert _model_family(sa.Column("n", sa.SmallInteger()))[0] == "int2"
    assert _model_family(sa.Column("n", sa.Integer()))[0] == "int4"
    assert _model_family(sa.Column("n", sa.BigInteger()))[0] == "int8"
    assert _db_family("smallint", "int2") == "int2"
    assert _db_family("integer", "int4") == "int4"
    assert _db_family("bigint", "int8") == "int8"


def test_integer_width_mismatch_is_a_difference() -> None:
    assert _check(sa.Integer(), _db_col("int8")) == ["t.n: type: model=int4 db=int8"]
    assert _check(sa.BigInteger(), _db_col("int8")) == []


def test_unbounded_model_string_is_compared_with_db_length() -> None:
    assert _check(sa.String(), _db_col("varchar", length=200), "title") == [
        "t.title: type: varchar length model=unbounded db=200"
    ]
    assert _check(sa.String(), _db_col("text"), "title") == []  # unbounded in both
    assert _check(sa.String(), _db_col("varchar"), "title") == []
    assert _check(sa.String(32), _db_col("varchar"), "title") == [
        "t.title: type: varchar length model=32 db=unbounded"
    ]


def test_numeric_precision_and_scale_are_compared_even_when_unbounded() -> None:
    assert _check(sa.Numeric(), _db_col("numeric", precision=10, scale=2), "amount") == [
        "t.amount: type: numeric model=unbounded db=10,2"
    ]
    assert _check(sa.Numeric(10, 2), _db_col("numeric"), "amount") == [
        "t.amount: type: numeric model=10,2 db=unbounded"
    ]
    assert _check(sa.Numeric(10, 2), _db_col("numeric", precision=10, scale=2), "amount") == []


def _column(nullable: bool, has_default: bool) -> dict[str, Any]:
    return {"nullable": nullable, "has_default": has_default}


def test_unlisted_missing_table_is_a_difference() -> None:
    diffs, errors, notes = _table_presence(["orders", *EXEMPT], set())
    assert diffs == ["orders: table_missing: not in database"]
    assert errors == []
    assert len(notes) == len(EXEMPT)


def test_exempt_missing_table_is_only_a_note() -> None:
    diffs, errors, notes = _table_presence(EXEMPT, set())
    assert diffs == []
    assert errors == []
    assert len(notes) == len(EXEMPT)


def test_exempt_table_that_now_exists_is_an_error() -> None:
    diffs, errors, _ = _table_presence(EXEMPT, set(EXEMPT))
    assert diffs == []
    assert len(errors) == len(EXEMPT)
    assert all("exemption_stale" in line for line in errors)


def test_exemption_for_a_removed_model_is_an_error() -> None:
    _, errors, _ = _table_presence([], set())
    assert len(errors) == len(EXEMPT)
    assert all("exemption_unknown" in line for line in errors)


def test_every_exemption_has_a_reason() -> None:
    assert all(reason.strip() for reason in MISSING_TABLE_EXEMPTIONS.values())


def test_extra_not_null_without_default_is_a_difference() -> None:
    db = {
        "columns": {
            ("orders", "id"): _column(False, True),
            ("orders", "legacy"): _column(False, False),
        }
    }
    diffs, notes = _extra_column_lines("orders", {"id"}, db)
    assert diffs == ["orders.legacy: extra_column: not_null_without_default"]
    assert notes == []


def test_extra_nullable_or_defaulted_column_is_a_note() -> None:
    db = {
        "columns": {
            ("orders", "a"): _column(True, False),
            ("orders", "b"): _column(False, True),
        }
    }
    diffs, notes = _extra_column_lines("orders", set(), db)
    assert diffs == []
    assert len(notes) == 2


def test_other_tables_and_model_columns_are_ignored() -> None:
    db = {
        "columns": {
            ("orders", "id"): _column(False, False),
            ("users", "extra"): _column(False, False),
        }
    }
    assert _extra_column_lines("orders", {"id"}, db) == ([], [])
