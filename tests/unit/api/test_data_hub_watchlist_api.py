"""Unit tests for the project watchlist endpoints (Phase 3 REST surface).

The watchlist service is stubbed in ``sys.modules`` so these tests do not depend
on the service module landing at the same time as the endpoints.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.api_v1.endpoints.data_hub import watchlist as watchlist_api
from app.config import settings
from app.schemas.data_hub import WatchlistItemCreate

_TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)")

_PROJECT_FIELDS: dict[str, Any] = {
    "id": 5,
    "slug": "alpha-one",
    "rera_number": "HRERA-1",
    "project_name": "Alpha One",
    "developer_name": "Alpha Builders",
    "developer_slug": "alpha-builders",
    "location": None,
    "district": "Gurugram",
    "total_units": None,
    "total_area_sqm": None,
    "possession_date": None,
    "status": "registered",
    "complaint_count": 0,
    "source_url": None,
    "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    "last_successful_run_id": None,
}


def _project(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(**{**_PROJECT_FIELDS, **overrides})


def _watchlist_row(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "id": 11,
        "rera_project_id": 5,
        "notes": "Watching this",
        "alert_prefs": {"watchlist_price_change": True},
        "created_at": datetime(2026, 1, 3, tzinfo=UTC),
    }
    return SimpleNamespace(**{**fields, **overrides})


class _ScalarRows:
    def __init__(self, values: list[Any]) -> None:
        self._values = list(values)

    def all(self) -> list[Any]:
        return list(self._values)


class _FakeResult:
    def __init__(self, *, rows: Any = (), scalars: Any = (), scalar: Any = None) -> None:
        self._rows = list(rows)
        self._scalars = list(scalars)
        self._scalar = scalar

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._scalars)

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


def _table_key(stmt: Any) -> frozenset[str]:
    sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
    return frozenset(_TABLE_RE.findall(sql))


def _routed_db(routes: dict[frozenset[str], list[_FakeResult]]) -> AsyncMock:
    queues = {key: list(value) for key, value in routes.items()}

    async def _execute(stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        queue = queues.get(_table_key(stmt))
        assert queue, f"unmapped statement in test: {_table_key(stmt)}"
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _empty_db() -> AsyncMock:
    result = MagicMock()
    result.all.return_value = []
    result.first.return_value = None
    result.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = result
    return db


@pytest.fixture
def watchlist_service(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Stand in for app.services.data_hub.watchlist, which lands in parallel."""
    module = ModuleType("app.services.data_hub.watchlist")
    module.add_to_watchlist = AsyncMock(return_value=_watchlist_row())
    module.list_watchlist = AsyncMock(return_value=[])
    module.remove_from_watchlist = AsyncMock(return_value=False)
    module.watched_project_ids = AsyncMock(return_value=set())
    module.users_watching_project = AsyncMock(return_value=[])
    monkeypatch.setitem(sys.modules, "app.services.data_hub.watchlist", module)
    return module


_USER = SimpleNamespace(id=7)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        (
            watchlist_api.add_watchlist_item,
            {"payload": WatchlistItemCreate(project_id=5)},
        ),
        (watchlist_api.list_watchlist_items, {}),
        (watchlist_api.delete_watchlist_item, {"project_id": 5}),
    ],
)
async def test_watchlist_routes_fail_closed_before_database_query(
    endpoint: Any, kwargs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(**kwargs, db=db, current_user=_USER)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "HRERA_DISABLED"
    db.execute.assert_not_awaited()


def test_watchlist_body_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        WatchlistItemCreate.model_validate({"project_id": 5, "unknown": True})


def test_watchlist_body_requires_a_project_id() -> None:
    with pytest.raises(ValidationError):
        WatchlistItemCreate.model_validate({"notes": "no project"})


@pytest.mark.asyncio
async def test_add_to_watchlist_returns_404_for_an_unknown_project(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"rera_projects"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException) as exc_info:
        await watchlist_api.add_watchlist_item(
            WatchlistItemCreate(project_id=99), db=db, current_user=_USER
        )

    assert exc_info.value.status_code == 404
    watchlist_service.add_to_watchlist.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_to_watchlist_refuses_a_project_with_no_public_page(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project with no slug is not watchable, because the row has no link.

    Every other project route filters on ``slug IS NOT NULL``: the slug is the
    public URL key, and a watched row exists to link to that page. Accepting one
    here would store a row the list can only render as ``#<id>`` with no name,
    link or figures.
    """
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"rera_projects"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException) as exc_info:
        await watchlist_api.add_watchlist_item(
            WatchlistItemCreate(project_id=5), db=db, current_user=_USER
        )

    assert exc_info.value.status_code == 404
    watchlist_service.add_to_watchlist.assert_not_awaited()
    # The refusal is the query's own filter, so it cannot drift from the read side.
    sql = str(db.execute.await_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    assert "rera_projects.slug IS NOT NULL" in sql


@pytest.mark.asyncio
async def test_add_to_watchlist_delegates_to_the_service_and_returns_the_project(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    row = _watchlist_row()
    watchlist_service.add_to_watchlist.return_value = row
    db = _routed_db(
        {
            frozenset({"rera_projects"}): [_FakeResult(scalar=5)],
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(_project(), None)])
            ],
            frozenset({"data_hub_evidence_assertions", "source_documents"}): [
                _FakeResult(rows=[])
            ],
        }
    )

    response = await watchlist_api.add_watchlist_item(
        WatchlistItemCreate(project_id=5, notes="Watching this", alert_prefs={"watchlist_price_change": True}),
        db=db,
        current_user=_USER,
    )

    assert watchlist_service.add_to_watchlist.await_args.kwargs == {
        "user_id": 7,
        "project_id": 5,
        "notes": "Watching this",
        "alert_prefs": {"watchlist_price_change": True},
    }
    assert response.id == 11
    # The public name is project_id; the column is rera_project_id.
    assert response.project_id == 5
    assert response.notes == "Watching this"
    assert response.alert_prefs == {"watchlist_price_change": True}
    assert response.project is not None and response.project.slug == "alpha-one"
    # The service only flushes, so the row is reloaded before it is serialized.
    db.refresh.assert_awaited_once_with(row)


@pytest.mark.asyncio
async def test_add_to_watchlist_maps_a_service_limit_error_to_409(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service raises WatchlistLimitExceeded (a ValueError) on a full watchlist."""
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    watchlist_service.add_to_watchlist.side_effect = ValueError(
        "Watchlist limit of 100 projects reached"
    )
    db = _routed_db({frozenset({"rera_projects"}): [_FakeResult(scalar=5)]})

    with pytest.raises(HTTPException) as exc_info:
        await watchlist_api.add_watchlist_item(
            WatchlistItemCreate(project_id=5), db=db, current_user=_USER
        )

    assert exc_info.value.status_code == 409
    assert "limit" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_add_to_watchlist_accepts_a_body_without_notes_or_prefs(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"rera_projects"}): [_FakeResult(scalar=5)],
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(_project(), None)])
            ],
            frozenset({"data_hub_evidence_assertions", "source_documents"}): [
                _FakeResult(rows=[])
            ],
        }
    )

    await watchlist_api.add_watchlist_item(
        WatchlistItemCreate(project_id=5), db=db, current_user=_USER
    )

    assert watchlist_service.add_to_watchlist.await_args.kwargs["notes"] is None
    assert watchlist_service.add_to_watchlist.await_args.kwargs["alert_prefs"] is None


@pytest.mark.asyncio
async def test_list_watchlist_returns_the_service_order_and_cards(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    watchlist_service.list_watchlist.return_value = [
        _watchlist_row(id=11, rera_project_id=5),
        _watchlist_row(id=10, rera_project_id=6, notes=None, alert_prefs=None),
    ]
    db = _routed_db(
        {
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(_project(), None)])
            ],
            frozenset({"data_hub_evidence_assertions", "source_documents"}): [
                _FakeResult(rows=[])
            ],
        }
    )

    items = await watchlist_api.list_watchlist_items(db=db, current_user=_USER)

    assert [item.id for item in items] == [11, 10]
    assert [item.project_id for item in items] == [5, 6]
    assert items[0].project is not None
    # The second project is not in the page: the card is null, the item still serializes.
    assert items[1].project is None
    assert watchlist_service.list_watchlist.await_args.kwargs == {"user_id": 7}
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_watchlist_makes_no_query_when_nothing_is_watched(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()

    items = await watchlist_api.list_watchlist_items(db=db, current_user=_USER)

    assert items == []
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_from_watchlist_returns_404_when_not_watched(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()
    watchlist_service.remove_from_watchlist.return_value = False

    with pytest.raises(HTTPException) as exc_info:
        await watchlist_api.delete_watchlist_item(project_id=5, db=db, current_user=_USER)

    assert exc_info.value.status_code == 404
    assert watchlist_service.remove_from_watchlist.await_args.kwargs == {
        "user_id": 7,
        "project_id": 5,
    }


@pytest.mark.asyncio
async def test_remove_from_watchlist_returns_204_when_removed(
    watchlist_service: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()
    watchlist_service.remove_from_watchlist.return_value = True

    result = await watchlist_api.delete_watchlist_item(
        project_id=5, db=db, current_user=_USER
    )

    assert result is None
    assert db.execute.await_count == 0


@pytest.mark.parametrize(
    "prefs",
    [{"watchlist_price_change": "false"}, {"watchlist_price_change": 0}, {"price": False}],
)
def test_alert_prefs_reject_unknown_keys_and_non_bool_values(prefs) -> None:
    """A string or number switch would be read as "on"; an unknown key does nothing."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WatchlistItemCreate(project_id=5, alert_prefs=prefs)
