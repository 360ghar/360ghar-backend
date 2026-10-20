"""Cursor-based pagination primitives shared by all list endpoints.

A cursor embeds a short hash of the request filters. A cursor sent with other
filters fails with 422 INVALID_CURSOR, so a client cannot page one filter set
with the cursor of another.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import Any, Generic, TypeVar

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import cast, tuple_
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import BadRequestException, ValidationException

T = TypeVar("T")

CURSOR_VERSION = 1
CURSOR_FILTER_HASH_LEN = 12
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _canonical_filter_value(value: Any) -> Any:
    """Stable JSON form: sets sorted, datetimes as UTC ISO, enums by value, unset (None) dropped."""
    if isinstance(value, Mapping):
        return {str(k): _canonical_filter_value(v) for k, v in value.items() if v is not None}
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical_filter_value(v) for v in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [_canonical_filter_value(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, _dt.datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=_dt.UTC)
        return aware.astimezone(_dt.UTC).isoformat()
    return value


def filters_hash(filters: Mapping[str, Any] | None = None) -> str:
    """Short hash of the canonical JSON of the filters. ``None`` hashes as ``{}``."""
    canonical = json.dumps(
        _canonical_filter_value(dict(filters or {})),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:CURSOR_FILTER_HASH_LEN]


# migrate in wave 3: pass filters= so the cursor is bound to the request filters.
def encode_cursor(payload: dict[str, Any], filters: Mapping[str, Any] | None = None) -> str:
    """Encode a cursor payload to an opaque, URL-safe, unpadded base64 token bound to ``filters``."""
    bound = {**payload, "f": filters_hash(filters)}
    raw = json.dumps(bound, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# migrate in wave 3: pass filters= so a cursor from other filters is rejected.
def decode_cursor(cursor: str, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Decode an opaque cursor.

    Malformed cursors raise 400 INVALID_CURSOR. A cursor bound to other filters raises
    422 INVALID_CURSOR.
    """
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR") from e
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR")
    if payload.get("f") != filters_hash(filters):
        raise ValidationException(
            "Pagination cursor does not match the requested filters",
            error_code="INVALID_CURSOR",
        )
    payload.pop("f")
    return payload


def keyset_payload(sort_value: Any, item_id: int | str) -> dict[str, Any]:
    return {"v": CURSOR_VERSION, "k": [sort_value, item_id]}


def read_keyset(
    payload: dict[str, Any], value_kind: str = "scalar", id_kind: str = "id"
) -> tuple[Any, int | str] | None:
    """The ``(sort value, id)`` of a single-key cursor, or None when there is no cursor.

    An empty payload is no cursor. Any other payload must carry ``k`` as a two-item list whose
    value fits ``value_kind`` and whose id fits ``id_kind`` (see ``require_cursor_value``).
    Otherwise it raises 400 INVALID_CURSOR, so a crafted cursor never reaches SQL.
    """
    if not payload:
        return None
    key = payload.get("k")
    if not isinstance(key, list) or len(key) != 2:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR")
    return require_cursor_value(key[0], value_kind), require_cursor_id(key[1], id_kind)


_INT_RANGES = {
    "int2": (-(2**15), 2**15 - 1),
    "int4": (-(2**31), 2**31 - 1),
    "int8": (-(2**63), 2**63 - 1),
}

# An ISO 8601 calendar date or date-time in a form Postgres parses. Python also accepts
# week dates (2024-W01-1) and ordinal dates, which Postgres rejects, so they fail here.
_ISO_DATETIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?"
    r"(?:Z|[+-][0-9]{2}(?::?[0-9]{2})?)?)?"
)


_MAX_UTC_OFFSET = _dt.timedelta(hours=16)


def require_cursor_value(value: Any, kind: str) -> Any:
    """Return a keyset sort value that fits its kind, or raise 400 INVALID_CURSOR.

    ``int2``, ``int4`` and ``int8`` are integer sort keys, checked against the SQL range.
    ``number`` is a finite numeric sort value. ``datetime`` is an ISO 8601 string that
    Postgres accepts, with a UTC offset under 16 hours. ``text`` is a string. ``bool`` is a
    boolean. ``scalar`` is any string, boolean or finite number (a column type with no
    stricter kind). ``id`` is an int8 integer or a string. A NULL sort value is a valid
    position for every kind. Ids go through ``require_cursor_id``, which rejects NULL.
    """
    if value is None:
        return value
    if kind in _INT_RANGES:
        low, high = _INT_RANGES[kind]
        ok = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    elif kind == "number":
        ok = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and _is_finite_number(value)
        )
    elif kind == "text":
        ok = isinstance(value, str)
    elif kind == "bool":
        ok = isinstance(value, bool)
    elif kind == "scalar":
        ok = isinstance(value, (str, bool)) or (
            isinstance(value, (int, float)) and _is_finite_number(value)
        )
    elif kind == "id":
        ok = isinstance(value, str) or (
            isinstance(value, int) and not isinstance(value, bool) and _fits_int8(value)
        )
    elif kind == "datetime":
        ok = isinstance(value, str) and _is_iso_datetime(value)
    else:
        raise ValueError(f"unknown cursor value kind: {kind}")
    if not ok:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR")
    return value


def require_cursor_id(value: Any, kind: str) -> Any:
    """Return a cursor id that fits its SQL range, or raise 400 INVALID_CURSOR.

    An id is never NULL. ``kind`` is the id column's kind: ``int4`` or ``int8`` for an integer
    id, ``text`` for a string id, or ``id`` when the caller does not know.
    """
    if value is None:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR")
    return require_cursor_value(value, kind)


def _fits_int8(value: int) -> bool:
    low, high = _INT_RANGES["int8"]
    return low <= value <= high


def _is_finite_number(value: int | float) -> bool:
    """False for NaN, Infinity (json.loads accepts both) and ints too large for a float."""
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _is_iso_datetime(value: str) -> bool:
    """True for a date or date-time that Postgres parses and that stays in range in UTC."""
    if _ISO_DATETIME.fullmatch(value) is None:
        return False
    try:
        parsed = _dt.datetime.fromisoformat(value)
        aware = parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.UTC)
        aware.astimezone(_dt.UTC)
    except (ValueError, OverflowError):
        return False
    # Python takes any offset under 24 hours. Postgres rejects 16 hours and more.
    offset = parsed.utcoffset()
    return offset is None or abs(offset) < _MAX_UTC_OFFSET


def validate_keyset_payload(
    payload: dict[str, Any], value_kind: str, id_kind: str = "int8"
) -> None:
    """Validate a single-key cursor with ``read_keyset``. An empty payload is the first page."""
    read_keyset(payload, value_kind, id_kind)


def keyset_sort_value(value: Any) -> Any:
    """JSON-safe representation of a sort value for cursor encoding."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return value


def _column_kind(sql_type: Any) -> str:
    """The cursor value kind for a column type. Every integer width is checked as int8."""
    if isinstance(sql_type, sa.Integer):
        return "int8"
    if isinstance(sql_type, (sa.DateTime, sa.Date)):
        return "datetime"
    if isinstance(sql_type, sa.Boolean):
        return "bool"
    if isinstance(sql_type, sa.Numeric):  # Float is a Numeric too
        return "number"
    if isinstance(sql_type, sa.String):  # Text and Enum are Strings too
        return "text"
    return "scalar"


def _bind_cursor_value(value: Any, sql_type: Any) -> ColumnElement:
    """Cast a cursor value to the column type. An integer is bound as BIGINT.

    A BIGINT bind never overflows against an int4 column, and it also fits a column the
    model maps as Integer but the database made bigint.
    """
    return cast(value, sa.BigInteger() if isinstance(sql_type, sa.Integer) else sql_type)


def keyset_filter(
    sort_col: Any,
    id_col: Any,
    cursor_payload: dict[str, Any],
    *,
    descending: bool = True,
) -> ColumnElement | None:
    """Return a SQLAlchemy keyset predicate for the given cursor, or None if no cursor.

    The cursor's sort value and id are checked against the column types first, so a value of
    the wrong type gives 400 INVALID_CURSOR here, for every domain, and never a 500 from SQL.
    Each value is then cast to its column's own type, so timestamp and date columns compare
    correctly (a raw ISO string would raise an operator error).
    """
    keyset = read_keyset(
        cursor_payload, _column_kind(sort_col.type), _column_kind(id_col.type)
    )
    if keyset is None:
        return None
    last_sort, last_id = keyset
    row = tuple_(sort_col, id_col)
    rhs = tuple_(
        _bind_cursor_value(last_sort, sort_col.type), _bind_cursor_value(last_id, id_col.type)
    )
    return row < rhs if descending else row > rhs


def offset_payload(offset: int) -> dict[str, Any]:
    """Encode an offset-based cursor payload. The payload is filter-bound by ``encode_cursor``."""
    return {"v": CURSOR_VERSION, "o": offset}


def trim_lookahead(items: Sequence[T], *, limit: int) -> tuple[list[T], bool]:
    """Trim a limit+1 result set and report whether another page exists."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return list(items[:limit]), len(items) > limit


def trim_keyset_lookahead(
    items: Sequence[T],
    *,
    limit: int,
    sort_value: Callable[[T], Any],
    item_id: Callable[[T], int | str],
) -> tuple[list[T], dict[str, Any] | None]:
    """Trim keyset lookahead rows and build the next cursor payload."""
    page_items, has_more = trim_lookahead(items, limit=limit)
    if not has_more or not page_items:
        return page_items, None
    last = page_items[-1]
    return page_items, keyset_payload(keyset_sort_value(sort_value(last)), item_id(last))


def trim_offset_lookahead(
    items: Sequence[T],
    *,
    limit: int,
    offset: int,
) -> tuple[list[T], dict[str, Any] | None]:
    """Trim offset lookahead rows and build the next offset cursor payload."""
    page_items, has_more = trim_lookahead(items, limit=limit)
    if not has_more or not page_items:
        return page_items, None
    return page_items, offset_payload(offset + len(page_items))


def read_offset(payload: dict[str, Any]) -> int:
    value = payload.get("o", 0)
    return value if isinstance(value, int) and value >= 0 else 0


class CursorParams:
    """FastAPI dependency carrying the standard cursor query params."""

    def __init__(
        self,
        cursor: str | None = Query(
            None, description="Opaque pagination cursor from a prior response's next_cursor."
        ),
        limit: int = Query(
            DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max items to return (1-100)."
        ),
        include_total: bool = Query(
            False, description="If true, include a total count (extra COUNT query)."
        ),
    ) -> None:
        self.cursor = cursor
        self.limit = limit
        self.include_total = include_total

    # migrate in wave 3: pass the request filters so a cursor from other filters is rejected.
    def decoded(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return decode_cursor(self.cursor, filters) if self.cursor else {}


class CursorPage(BaseModel, Generic[T]):
    # Every field is always sent (null when unset), so the response schema marks them all
    # required and generated clients get next_cursor, has_more and total without "?".
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int
    total: int | None = Field(
        default=None,
        description="Set only when the request sets include_total=true; otherwise null.",
    )


# migrate in wave 3: pass filters= and include total only when the request sets include_total.
def build_cursor_page(
    items: list[Any],
    *,
    limit: int,
    next_payload: dict[str, Any] | None,
    total: int | None = None,
    filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the response dict. `next_payload` None => end of list."""
    has_more = next_payload is not None
    page: dict[str, Any] = {
        "items": items,
        "next_cursor": encode_cursor(next_payload, filters) if next_payload else None,
        "has_more": has_more,
        "limit": limit,
    }
    if total is not None:
        page["total"] = total
    return page
