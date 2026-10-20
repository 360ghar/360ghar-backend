"""Shared contract primitives: write bodies, money, UTC datetimes, PATCH and public user refs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
)


class WriteModel(BaseModel):
    """Base for every write (request) body. Unknown keys fail with 422."""

    model_config = ConfigDict(extra="forbid")


class PatchModel(WriteModel):
    """Base for PATCH bodies. Only the keys the client sent are in ``model_fields_set``."""


def _reject_null(value: object) -> object:
    if value is None:
        raise ValueError("Input should not be null")
    return value


# Put on a PATCH field that must not be cleared: Annotated[str | None, NotNullable] = None.
NotNullable = BeforeValidator(_reject_null)


def apply_patch(obj: Any, body: BaseModel, *, exclude: Iterable[str] = ()) -> None:
    """Set only the fields the client sent (``model_fields_set``) on an ORM object."""
    skipped = set(exclude)
    for name in body.model_fields_set:
        if name not in skipped:
            setattr(obj, name, getattr(body, name))


def _to_money(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("Money must be a number")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Money must be a number") from exc
    if not amount.is_finite():
        raise ValueError("Money must be a finite number")
    try:
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:  # too many digits for the decimal context
        raise ValueError("Money is out of range") from exc
    # -0.0 + 0.0 is 0.0: a small negative amount must not serialize as -0.0.
    return float(rounded) + 0.0


# Money: accepts int, float, Decimal or str; rounds to 2 places; a JSON number on output.
# A bound such as Annotated[Money, Field(gt=0)] is enforced at validation. Pydantic writes it
# into the JSON schema as a raw "gt" key, because the before validator wraps the float schema.
# app.infrastructure.openapi renames those keys to the standard ones in docs/openapi.json.
Money = Annotated[float, BeforeValidator(_to_money)]


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    return _to_utc(value).isoformat().replace("+00:00", "Z")


# UtcDateTime: a naive value is read as UTC; output is ISO 8601 with a "Z" suffix.
# The serializer returns str, which drops "format" from the response schema. WithJsonSchema
# puts "format": "date-time" back, so generated clients get a date-time type.
UtcDateTime = Annotated[
    datetime,
    AfterValidator(_to_utc),
    PlainSerializer(_utc_iso, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


class PublicUserRef(BaseModel):
    """Public identity of a user: id, display name and avatar only."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str | None = Field(
        default=None, validation_alias=AliasChoices("display_name", "full_name", "name")
    )
    avatar_url: str | None = Field(
        default=None, validation_alias=AliasChoices("avatar_url", "profile_image_url")
    )
