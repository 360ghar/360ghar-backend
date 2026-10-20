"""Keyset cursor values are checked inside read_keyset and keyset_filter, for every domain.

A cursor is client input. A value of the wrong type, an id outside its range or a UTC offset of
16 hours or more must give 400 INVALID_CURSOR here, before SQL. Postgres would reject each of them
with an error that the API turns into a 500.
"""

from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql

from app.core.exceptions import BadRequestException
from app.schemas.pagination import (
    _is_iso_datetime,
    keyset_filter,
    keyset_payload,
    read_keyset,
    require_cursor_value,
    validate_keyset_payload,
)

_TABLE = Table(
    "cursor_probe",
    MetaData(),
    Column("id", Integer, primary_key=True),
    Column("big_id", BigInteger),
    Column("text_id", String),
    Column("created_at", DateTime(timezone=True)),
    Column("due_on", Date),
    Column("name", String),
    Column("rank", Integer),
    Column("flag", Boolean),
)
C = _TABLE.c


def _payload(value, item_id=1) -> dict:
    return keyset_payload(value, item_id)


def _sql(predicate) -> str:
    return str(predicate.compile(dialect=postgresql.dialect()))


# --- UTC offsets: Python takes under 24 hours, Postgres rejects 16 hours and more -----------


@pytest.mark.parametrize(
    "value",
    [
        "2026-01-01T00:00:00+16:00",
        "2026-01-01T00:00:00-16:00",
        "2026-01-01T00:00:00+1600",
        "2026-01-01T00:00:00+16",
        "2026-01-01 00:00:00-17:30",
        "2026-01-01T00:00:00+23:59",
        "2026-01-01T00:00:00-23:59",
        "2026-01-01T00:00:00+24:00",
    ],
)
def test_offset_of_16_hours_or_more_is_rejected(value):
    assert _is_iso_datetime(value) is False
    with pytest.raises(BadRequestException) as exc:
        require_cursor_value(value, "datetime")
    assert exc.value.error_code == "INVALID_CURSOR"


@pytest.mark.parametrize(
    "value",
    [
        "2026-01-01T00:00:00+15:59",
        "2026-01-01T00:00:00-15:30",
        "2026-01-01T00:00:00+05:30",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00",
        "2026-01-01",
    ],
)
def test_offset_under_16_hours_is_accepted(value):
    assert _is_iso_datetime(value) is True
    assert require_cursor_value(value, "datetime") == value


# --- keyset_filter checks the value against the column type ---------------------------------


@pytest.mark.parametrize(
    ("sort_col", "value"),
    [
        (C.created_at, "not-a-date"),
        (C.created_at, 123),
        (C.created_at, ["2026-01-01"]),
        (C.created_at, {"a": 1}),
        (C.created_at, True),
        (C.created_at, "2026-01-01T00:00:00+16:00"),
        (C.due_on, "2026-13-01"),
        (C.due_on, "2026-01-01T00:00:00-16:00"),
        (C.name, 123),
        (C.name, ["x"]),
        (C.name, {"a": 1}),
        (C.rank, "abc"),
        (C.rank, 1.5e300),
        (C.rank, 2**63),
        (C.rank, True),
        (C.rank, ["1"]),
        (C.flag, "yes"),
    ],
)
def test_keyset_filter_rejects_a_sort_value_of_the_wrong_type(sort_col, value):
    with pytest.raises(BadRequestException) as exc:
        keyset_filter(sort_col, C.id, _payload(value))
    assert exc.value.error_code == "INVALID_CURSOR"
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    ("id_col", "item_id"),
    [
        (C.id, "x"),
        (C.id, None),
        (C.id, True),
        (C.id, 1.5),
        (C.id, ["1"]),
        (C.id, {"a": 1}),
        (C.id, 2**63),
        (C.id, -(2**63) - 1),
        (C.big_id, "x"),
        (C.text_id, 5),
        (C.text_id, ["a"]),
    ],
)
def test_keyset_filter_rejects_an_id_of_the_wrong_type_or_range(id_col, item_id):
    with pytest.raises(BadRequestException) as exc:
        keyset_filter(C.created_at, id_col, _payload("2026-01-01T00:00:00Z", item_id))
    assert exc.value.error_code == "INVALID_CURSOR"


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 1},
        {"v": 1, "k": None},
        {"v": 1, "k": "x"},
        {"v": 1, "k": [1]},
        {"v": 1, "k": [1, 2, 3]},
        {"v": 1, "k": {"a": 1}},
        {"v": 1, "o": 5},
    ],
)
def test_a_cursor_without_a_valid_key_is_400_not_the_first_page(payload):
    with pytest.raises(BadRequestException):
        keyset_filter(C.created_at, C.id, payload)
    with pytest.raises(BadRequestException):
        read_keyset(payload)


def test_no_cursor_is_the_first_page():
    assert keyset_filter(C.created_at, C.id, {}) is None
    assert read_keyset({}) is None
    validate_keyset_payload({}, "datetime")


def test_valid_values_of_every_column_kind_build_a_predicate():
    assert keyset_filter(C.created_at, C.id, _payload("2026-01-01T00:00:00Z", 7)) is not None
    assert keyset_filter(C.due_on, C.id, _payload("2026-01-01", 7)) is not None
    assert keyset_filter(C.name, C.text_id, _payload("a", "b"), descending=False) is not None
    assert keyset_filter(C.rank, C.big_id, _payload(5, 2**40)) is not None
    assert keyset_filter(C.flag, C.id, _payload(True, 3)) is not None
    # A NULL sort value is a valid position. A NULL id is not.
    assert keyset_filter(C.created_at, C.id, _payload(None, 3)) is not None


def test_integer_cursor_values_are_bound_as_bigint():
    """A BIGINT bind never overflows an int4 column and fits a bigint column mapped as Integer."""
    sql = _sql(keyset_filter(C.rank, C.id, _payload(5, 2**40)))
    assert sql.count("AS BIGINT") == 2
    assert "AS INTEGER" not in sql


def test_timestamp_and_date_values_are_cast_to_the_column_type():
    assert "AS TIMESTAMP WITH TIME ZONE" in _sql(
        keyset_filter(C.created_at, C.id, _payload("2026-01-01T00:00:00Z"))
    )
    assert "AS DATE" in _sql(keyset_filter(C.due_on, C.id, _payload("2026-01-01")))


def test_read_keyset_without_kinds_still_rejects_containers_and_non_finite_numbers():
    for value in (["a"], {"a": 1}, float("nan"), float("inf")):
        with pytest.raises(BadRequestException):
            read_keyset(_payload(value))
    for item_id in (["a"], {"a": 1}, True, 2**63, None):
        with pytest.raises(BadRequestException):
            read_keyset(_payload("a", item_id))
    assert read_keyset(_payload("a", "b")) == ("a", "b")
    assert read_keyset(_payload(5, 7)) == (5, 7)
