"""Cursor-based pagination primitives shared by all list endpoints."""

from __future__ import annotations

import base64
import datetime as _dt
import json
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import cast, tuple_
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import BadRequestException

T = TypeVar("T")

CURSOR_VERSION = 1
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode a cursor payload to an opaque, URL-safe, unpadded base64 token."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode an opaque cursor. Raises BadRequestException(INVALID_CURSOR)."""
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR") from e
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR")
    return payload


def keyset_payload(sort_value: Any, item_id: int | str) -> dict[str, Any]:
    return {"v": CURSOR_VERSION, "k": [sort_value, item_id]}


def read_keyset(payload: dict[str, Any]) -> tuple[Any, int | str] | None:
    key = payload.get("k")
    if isinstance(key, list) and len(key) == 2:
        return key[0], key[1]
    return None


def keyset_sort_value(value: Any) -> Any:
    """JSON-safe representation of a sort value for cursor encoding."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return value


def keyset_filter(
    sort_col: Any,
    id_col: Any,
    cursor_payload: dict[str, Any],
    *,
    descending: bool = True,
) -> ColumnElement | None:
    """Return a SQLAlchemy keyset predicate for the given cursor, or None if no cursor.

    Casts the cursor's bound sort value to sort_col's own type so timestamp/date
    columns compare correctly (a raw ISO string would raise an operator error).
    """
    keyset = read_keyset(cursor_payload)
    if keyset is None:
        return None
    last_sort, last_id = keyset
    row = tuple_(sort_col, id_col)
    rhs = tuple_(cast(last_sort, sort_col.type), cast(last_id, id_col.type))
    return row < rhs if descending else row > rhs


def offset_payload(offset: int) -> dict[str, Any]:
    """Encode an offset-based cursor payload.

    Note: offset cursors are NOT bound to query filters — reusing a cursor across
    a request with different filter params will paginate the new filter's result set
    by raw offset (a known offset-pagination limitation).
    """
    return {"v": CURSOR_VERSION, "o": offset}


def read_offset(payload: dict[str, Any]) -> int:
    value = payload.get("o", 0)
    return value if isinstance(value, int) and value >= 0 else 0


class CursorParams:
    """FastAPI dependency carrying the standard cursor query params."""

    def __init__(
        self,
        cursor: str | None = Query(None, description="Opaque pagination cursor from a prior response's next_cursor."),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max items to return (1-100)."),
        include_total: bool = Query(False, description="If true, include a total count (extra COUNT query)."),
    ) -> None:
        self.cursor = cursor
        self.limit = limit
        self.include_total = include_total

    def decoded(self) -> dict[str, Any]:
        return decode_cursor(self.cursor) if self.cursor else {}


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int
    total: int | None = None


def build_cursor_page(
    items: list[Any],
    *,
    limit: int,
    next_payload: dict[str, Any] | None,
    total: int | None = None,
) -> dict[str, Any]:
    """Build the response dict. `next_payload` None => end of list."""
    has_more = next_payload is not None
    page: dict[str, Any] = {
        "items": items,
        "next_cursor": encode_cursor(next_payload) if next_payload else None,
        "has_more": has_more,
        "limit": limit,
    }
    if total is not None:
        page["total"] = total
    return page
