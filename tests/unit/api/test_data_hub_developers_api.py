"""Unit tests for the developer intelligence endpoints (Phase 3 REST surface)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.api_v1.endpoints.data_hub import developers as developers_api
from app.config import settings
from app.schemas.pagination import CursorParams

_TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)")

_DEVELOPER_FIELDS: dict[str, Any] = {
    "id": 1,
    "slug": "alpha-builders",
    "name": "Alpha Builders",
    "legal_name": "Alpha Builders Private Limited",
    "logo_url": None,
    "website_url": "https://alpha.test",
    "headquarters": "Gurugram",
    "founded_year": 2005,
    "is_listed": False,
    "cin": "U12345HR2005PTC000001",
    "summary": "A summary",
    "dossier": "A dossier",
    "geographies": ["Gurugram"],
    "last_successful_run_id": None,
}

_SCORE_FIELDS: dict[str, Any] = {
    "delivery": 80,
    "regulatory": 70,
    "complaints": 60,
    "financials": 50,
    "market_reception": 40,
    "total_score": 60,
    "project_count": 3,
    "delivered_count": 1,
    "under_construction_count": 2,
    "complaint_count": 4,
    "computed_at": datetime(2026, 1, 2, tzinfo=UTC),
}


def _developer(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(**{**_DEVELOPER_FIELDS, **overrides})


def _score(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(**{**_SCORE_FIELDS, **overrides})


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


def _page(limit: int = 20) -> CursorParams:
    return CursorParams(cursor=None, limit=limit, include_total=False)


def _compiled(stmt: Any) -> str:
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    return sql.replace("%%", "%")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        (developers_api.list_developers, {"q": None, "order_by": "name", "page": _page()}),
        (developers_api.get_developer, {"slug": "alpha-builders"}),
        (developers_api.get_developer_score, {"slug": "alpha-builders"}),
    ],
)
async def test_developer_routes_fail_closed_before_database_query(
    endpoint: Any, kwargs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(**kwargs, db=db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "HRERA_DISABLED"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_developers_orders_by_name_and_joins_the_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()

    await developers_api.list_developers(q=None, order_by="name", page=_page(), db=db)

    sql = str(db.execute.await_args_list[0].args[0])
    assert "LEFT OUTER JOIN developer_scores" in sql
    assert "ORDER BY developers.name" in sql
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_list_developers_orders_by_total_score_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()

    await developers_api.list_developers(q=None, order_by="score", page=_page(), db=db)

    sql = str(db.execute.await_args_list[0].args[0])
    assert "ORDER BY developer_scores.total_score DESC NULLS LAST, developers.id" in sql


@pytest.mark.asyncio
async def test_list_developers_applies_the_name_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()

    await developers_api.list_developers(q="alpha", order_by="name", page=_page(), db=db)

    assert "developers.name ILIKE '%alpha%'" in _compiled(db.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_list_developers_counts_projects_and_complaints_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"developers", "developer_scores"}): [
                _FakeResult(rows=[(_developer(), _score())])
            ],
            frozenset({"rera_projects"}): [_FakeResult(rows=[("alpha-builders", 7)])],
            frozenset({"rera_complaints"}): [_FakeResult(rows=[("alpha-builders", 2)])],
        }
    )

    page = await developers_api.list_developers(
        q=None, order_by="name", page=_page(), db=db
    )

    item = page["items"][0]
    assert item.total_score == 60.0
    assert item.project_count == 7
    assert item.complaint_count == 2
    assert db.execute.await_count == 3


@pytest.mark.asyncio
async def test_list_developers_pages_with_a_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    rows = [
        (_developer(id=index, slug=f"dev-{index}", name=f"Dev {index}"), None)
        for index in (1, 2, 3)
    ]
    db = _routed_db(
        {
            frozenset({"developers", "developer_scores"}): [_FakeResult(rows=rows)],
            frozenset({"rera_projects"}): [_FakeResult(rows=[])],
            frozenset({"rera_complaints"}): [_FakeResult(rows=[])],
        }
    )

    page = await developers_api.list_developers(
        q=None, order_by="name", page=_page(limit=2), db=db
    )

    assert [item.slug for item in page["items"]] == ["dev-1", "dev-2"]
    assert page["has_more"] is True
    assert page["next_cursor"]
    # A developer with no score row still serializes, with a null score.
    assert page["items"][0].total_score is None

    # Page two: the returned cursor moves the SQL offset past page one.
    second_db = _routed_db(
        {
            frozenset({"developers", "developer_scores"}): [_FakeResult(rows=rows[2:])],
            frozenset({"rera_projects"}): [_FakeResult(rows=[])],
            frozenset({"rera_complaints"}): [_FakeResult(rows=[])],
        }
    )
    second = await developers_api.list_developers(
        q=None,
        order_by="name",
        page=CursorParams(cursor=page["next_cursor"], limit=2, include_total=False),
        db=second_db,
    )

    assert [item.slug for item in second["items"]] == ["dev-3"]
    assert second["has_more"] is False
    assert "OFFSET 2" in _compiled(second_db.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_developer_detail_returns_404_for_an_unknown_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"developers"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException) as exc_info:
        await developers_api.get_developer("missing", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_developer_detail_returns_the_score_and_a_capped_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    project = SimpleNamespace(
        id=5,
        slug="alpha-one",
        rera_number="HRERA-1",
        project_name="Alpha One",
        developer_name="Alpha Builders",
        developer_slug="alpha-builders",
        location=None,
        district="Gurugram",
        total_units=None,
        total_area_sqm=None,
        possession_date=None,
        status="registered",
        complaint_count=0,
        source_url=None,
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        last_successful_run_id=None,
    )
    db = _routed_db(
        {
            frozenset({"developers"}): [_FakeResult(scalar=_developer())],
            frozenset({"developer_scores"}): [_FakeResult(scalar=_score())],
            frozenset({"rera_projects"}): [_FakeResult(scalar=9)],
            frozenset({"rera_complaints"}): [_FakeResult(scalar=1)],
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(project, None)])
            ],
            frozenset({"data_hub_evidence_assertions", "source_documents"}): [
                _FakeResult(rows=[])
            ],
        }
    )

    detail = await developers_api.get_developer("alpha-builders", db=db)

    assert detail.name == "Alpha Builders"
    assert detail.cin == "U12345HR2005PTC000001"
    assert detail.geographies == ["Gurugram"]
    assert detail.project_count == 9
    assert detail.complaint_count == 1
    assert detail.score is not None and detail.score.total_score == 60.0
    assert [item.slug for item in detail.projects] == ["alpha-one"]
    portfolio_stmt = db.execute.await_args_list[4].args[0]
    assert f"LIMIT {developers_api.DEVELOPER_PROJECTS_LIMIT}" in _compiled(portfolio_stmt)
    assert db.execute.await_count == 6


@pytest.mark.asyncio
async def test_developer_detail_without_a_score_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"developers"}): [_FakeResult(scalar=_developer())],
            frozenset({"developer_scores"}): [_FakeResult(scalar=None)],
            frozenset({"rera_projects"}): [_FakeResult(scalar=0)],
            frozenset({"rera_complaints"}): [_FakeResult(scalar=0)],
            frozenset({"rera_projects", "rera_project_profiles"}): [_FakeResult(rows=[])],
        }
    )

    detail = await developers_api.get_developer("alpha-builders", db=db)

    assert detail.score is None
    assert detail.total_score is None
    assert detail.projects == []


@pytest.mark.asyncio
async def test_developer_score_returns_404_for_an_unknown_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"developers"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException) as exc_info:
        await developers_api.get_developer_score("missing", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_developer_score_returns_404_when_no_score_row_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"developers"}): [_FakeResult(scalar=_developer())],
            frozenset({"developer_scores"}): [_FakeResult(scalar=None)],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await developers_api.get_developer_score("alpha-builders", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_developer_score_serializes_every_pillar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"developers"}): [_FakeResult(scalar=_developer())],
            frozenset({"developer_scores"}): [_FakeResult(scalar=_score())],
        }
    )

    score = await developers_api.get_developer_score("alpha-builders", db=db)

    assert score.delivery == 80.0
    assert score.regulatory == 70.0
    assert score.complaints == 60.0
    assert score.financials == 50.0
    assert score.market_reception == 40.0
    assert score.total_score == 60.0
    assert score.computed_at == datetime(2026, 1, 2, tzinfo=UTC)
