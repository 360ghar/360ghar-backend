from __future__ import annotations

import inspect
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from app.services.ai_agent.agent_service import _jsonable, _jsonable_tool


class _Color(Enum):
    RED = "red"
    GREEN = "green"


class _Item(BaseModel):
    id: int
    label: str


def test_jsonable_passes_through_primitives_and_none():
    assert _jsonable(None) is None
    assert _jsonable("x") == "x"
    assert _jsonable(1) == 1
    assert _jsonable(1.5) == 1.5
    assert _jsonable(True) is True


def test_jsonable_coerces_temporal_decimal_uuid_enum():
    dt = datetime(2026, 7, 4, 12, 30, 45)
    assert _jsonable(dt) == "2026-07-04T12:30:45"
    assert _jsonable(date(2026, 7, 4)) == "2026-07-04"
    assert _jsonable(Decimal("3.5")) == 3.5
    assert _jsonable(UUID("12345678-1234-5678-1234-567812345678")) == "12345678-1234-5678-1234-567812345678"
    assert _jsonable(_Color.RED) == "red"


def test_jsonable_recurses_into_containers():
    payload = {
        "dt": datetime(2026, 1, 1),
        "nums": [Decimal("1"), Decimal("2")],
        "pair": (UUID("12345678-1234-5678-1234-567812345678"), _Color.GREEN),
        "set": {1, 2},
    }
    out = _jsonable(payload)
    assert out == {
        "dt": "2026-01-01T00:00:00",
        "nums": [1.0, 2.0],
        "pair": ["12345678-1234-5678-1234-567812345678", "green"],
        "set": [1, 2],
    }
    # dict keys are stringified
    assert _jsonable({1: "a"}) == {"1": "a"}


def test_jsonable_unwraps_pydantic_model():
    out = _jsonable(_Item(id=7, label="x"))
    assert out == {"id": 7, "label": "x"}


def test_jsonable_falls_back_to_str_for_unknown_types():
    class _Opaque:
        def __str__(self) -> str:
            return "opaque"

    assert _jsonable(_Opaque()) == "opaque"


def test_jsonable_tool_wraps_sync_return():
    def tool(*, value: Decimal) -> dict[str, Decimal]:
        return {"v": value}

    wrapped = _jsonable_tool(tool)
    assert wrapped(value=Decimal("2.5")) == {"v": 2.5}


async def test_jsonable_tool_wraps_async_return():
    async def tool(*, value: UUID) -> dict[str, UUID]:
        return {"id": value}

    wrapped = _jsonable_tool(tool)
    out = await wrapped(value=UUID("12345678-1234-5678-1234-567812345678"))
    assert out == {"id": "12345678-1234-5678-1234-567812345678"}


def test_jsonable_tool_preserves_signature():
    def tool(*, page: int, query: str) -> list[int]:
        return [page]

    wrapped = _jsonable_tool(tool)
    # functools.wraps copies __wrapped__; signature should be unchanged so
    # Pydantic AI's schema introspection sees the same parameters.
    assert inspect.signature(wrapped) == inspect.signature(tool)
    assert wrapped.__name__ == "tool"
