"""Keyset pagination for property lists.

A list is ordered by one or more sort keys and then by id. The cursor carries the
key values of the last row on the page. The next page is every row after that
position, so rows removed or added between requests do not shift later pages.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, and_, cast, false, literal, or_
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import BadRequestException
from app.models.properties import Property
from app.schemas.pagination import require_cursor_id, require_cursor_value

# (expression, SQL type, descending). The id is always the final tie-breaker.
KeySpec = tuple[Any, Any, bool]


def json_key(value: Any) -> Any:
    """JSON-safe form of a keyset sort value."""
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def keyset_after(
    key_specs: list[KeySpec],
    id_desc: bool,
    cursor_values: list[Any],
    cursor_id: int,
) -> ColumnElement[bool]:
    """Rows that come after the cursor in the order (key_1 ... key_n, id).

    Each cursor value is cast to its key's SQL type, so timestamps and numbers
    compare correctly. A NULL cursor value follows Postgres order (NULL last for ASC,
    first for DESC).
    """
    terms: list[ColumnElement[bool]] = []
    equal_so_far: list[ColumnElement[bool]] = []
    for (expr, sql_type, desc), value in zip(key_specs, cursor_values, strict=True):
        # Postgres sorts NULL last for ASC and first for DESC. A NULL never matches =, < or >,
        # so a NULL on either side is compared with IS NULL / IS NOT NULL.
        if value is None:
            after = expr.is_not(None) if desc else false()
            same = expr.is_(None)
        else:
            rhs = cast(value, sql_type)
            after = expr < rhs if desc else or_(expr > rhs, expr.is_(None))
            same = expr == rhs
        terms.append(and_(*equal_so_far, after) if equal_so_far else after)
        equal_so_far.append(same)
    # properties.id is bigint. An Integer bind renders as ::INTEGER and overflows past int4,
    # so the cursor id is bound as BIGINT.
    cursor_id_bind = literal(cursor_id, BigInteger())
    id_after = Property.id < cursor_id_bind if id_desc else Property.id > cursor_id_bind
    terms.append(and_(*equal_so_far, id_after) if equal_so_far else id_after)
    return or_(*terms)


def cursor_kind(sql_type: Any) -> str:
    """The cursor value kind for a sort key's SQL type.

    Integer keys are checked against their SQL range (int4, or int8 for BigInteger),
    timestamps are ISO strings and every other key is a finite number.
    """
    if isinstance(sql_type, DateTime):
        return "datetime"
    if isinstance(sql_type, BigInteger):
        return "int8"
    if isinstance(sql_type, Integer):
        return "int4"
    return "number"


def cursor_kinds(key_specs: list[KeySpec]) -> list[str]:
    return [cursor_kind(sql_type) for _expr, sql_type, _desc in key_specs]


def read_cursor_key(
    cursor_payload: dict[str, Any], kinds: list[str]
) -> tuple[list[Any], int] | None:
    """The (key values, id) of the cursor, or None on the first page.

    ``kinds`` gives the value kind of each sort key. A cursor with no key, or whose shape
    or value types do not match the sort, gives 400 INVALID_CURSOR. The id is checked
    against the int8 range, because properties.id is bigint.
    """
    if not cursor_payload:
        return None
    key = cursor_payload.get("k")
    if (
        not isinstance(key, list)
        or len(key) != 2
        or not isinstance(key[0], list)
        or len(key[0]) != len(kinds)
    ):
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR")
    values = [require_cursor_value(value, kind) for value, kind in zip(key[0], kinds, strict=True)]
    return values, require_cursor_id(key[1], "int8")
