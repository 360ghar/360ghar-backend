"""Unit tests for the micro-market, market pulse, and map endpoints (Phase 3)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.api_v1.endpoints.data_hub import market as market_api
from app.config import settings
from app.models.enums import MarketSentiment, ProjectStage

_TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)")

_MARKET_FIELDS: dict[str, Any] = {
    "id": 1,
    "city": "Gurugram",
    "name": "Golf Course Road",
    "slug": "golf-course-road",
    "district": "Gurugram",
    "summary": "A summary",
    "latitude": 28.45,
    "longitude": 77.09,
}


def _market(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(**{**_MARKET_FIELDS, **overrides})


def _pulse(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "city": "Gurugram",
        "captured_on": date(2026, 1, 2),
        "sentiment": MarketSentiment.positive,
        "avg_price_per_sqft": 12000,
        "price_change_90d_pct": 3.5,
        "new_registrations": 12,
        "new_complaints": 2,
        "computed_at": datetime(2026, 1, 2, 6, tzinfo=UTC),
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


def _compiled(stmt: Any) -> str:
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    return sql.replace("%%", "%")


_BBOX = {"min_lat": 28.0, "max_lat": 29.0, "min_lng": 76.0, "max_lng": 78.0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        (market_api.list_micro_markets, {"city": None}),
        (market_api.get_micro_market, {"city": "Gurugram", "slug": "golf-course-road"}),
        (market_api.list_market_pulse, {"city": None}),
        (market_api.list_map_projects, dict(_BBOX)),
    ],
)
async def test_market_routes_fail_closed_before_database_query(
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
async def test_list_micro_markets_is_capped_and_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalars=[_market()])]})

    items = await market_api.list_micro_markets(city=None, db=db)

    stmt = db.execute.await_args_list[0].args[0]
    sql = str(stmt)
    assert "ORDER BY micro_markets.city, micro_markets.slug" in sql
    assert market_api.MICRO_MARKET_LIMIT in stmt.compile(dialect=postgresql.dialect()).params.values()
    assert [item.slug for item in items] == ["golf-course-road"]
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_list_micro_markets_applies_the_city_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalars=[])]})

    await market_api.list_micro_markets(city="Gurugram", db=db)

    # Case-insensitive on purpose: the site redirects an uppercase path to its
    # lowercase form, so the city arrives as "gurugram" while the filed district
    # is "Gurugram". An exact match would 404 the link the site itself emits.
    assert "lower(micro_markets.city) = 'gurugram'" in _compiled(
        db.execute.await_args_list[0].args[0]
    )


@pytest.mark.asyncio
async def test_the_city_filter_matches_a_filed_district_of_any_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalars=[])]})

    await market_api.list_micro_markets(city="  gUrUgRaM  ", db=db)

    assert "lower(micro_markets.city) = 'gurugram'" in _compiled(
        db.execute.await_args_list[0].args[0]
    )


@pytest.mark.asyncio
async def test_a_multi_word_city_matches_through_the_hyphenated_url_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Delhi's districts are multi-word ("New Delhi", "South West Delhi") and a path
    # segment cannot carry a space, so the site links the hyphen form. The API has to
    # answer it, or every Delhi micro-market page 404s on the site's own link.
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException):
        await market_api.get_micro_market(city="new-delhi", slug="sector-10", db=db)

    sql = _compiled(db.execute.await_args_list[0].args[0])
    assert "lower(micro_markets.city) = 'new delhi'" in sql
    assert "lower(micro_markets.city) = 'new-delhi'" in sql


@pytest.mark.asyncio
async def test_the_space_spelling_still_matches_a_multi_word_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The hyphen form is what the site links; the space form is what a reader may type.
    # Both have to reach the same place.
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException):
        await market_api.get_micro_market(city="South West Delhi", slug="sector-10", db=db)

    assert "lower(micro_markets.city) = 'south west delhi'" in _compiled(
        db.execute.await_args_list[0].args[0]
    )


@pytest.mark.asyncio
async def test_a_hyphen_inside_a_city_name_still_matches_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The exact branch is tried first, so a district filed with a hyphen is never
    # rewritten into a different place by the separator-insensitive branch.
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException):
        await market_api.get_micro_market(city="Baran-city", slug="sector-1", db=db)

    sql = _compiled(db.execute.await_args_list[0].args[0])
    assert "lower(micro_markets.city) = 'baran-city'" in sql
    assert "lower(micro_markets.city) = 'baran city'" in sql


@pytest.mark.asyncio
async def test_micro_market_detail_looks_the_city_up_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException):
        await market_api.get_micro_market(city="gurugram", slug="sector-76-77", db=db)

    assert "lower(micro_markets.city) = 'gurugram'" in _compiled(
        db.execute.await_args_list[0].args[0]
    )


@pytest.mark.asyncio
async def test_micro_market_detail_returns_404_for_an_unknown_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"micro_markets"}): [_FakeResult(scalar=None)]})

    with pytest.raises(HTTPException) as exc_info:
        await market_api.get_micro_market("Gurugram", "missing", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_micro_market_detail_reports_its_own_project_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"micro_markets"}): [_FakeResult(scalar=_market())],
            frozenset({"rera_projects"}): [_FakeResult(scalar=9)],
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(scalar=12500.0),
                _FakeResult(
                    rows=[
                        (ProjectStage.under_construction, 5),
                        (ProjectStage.completed, 4),
                    ]
                ),
            ],
        }
    )

    detail = await market_api.get_micro_market("Gurugram", "golf-course-road", db=db)

    assert detail.project_count == 9
    assert detail.avg_price_per_sqft == 12500.0
    assert detail.stage_breakdown == {
        "pre_launch": 0,
        "under_construction": 5,
        "near_possession": 0,
        "completed": 4,
    }
    assert db.execute.await_count == 4


@pytest.mark.asyncio
async def test_micro_market_stats_are_scoped_by_the_project_link_not_the_district(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this scoping exists to prevent, pinned at the query level.

    A market with no district must still report its own projects: the link is what
    scopes the count, so district is irrelevant. Scoping by district made every
    micro-market in one district report identical numbers under a different name.
    """
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"micro_markets"}): [_FakeResult(scalar=_market(district=None))],
            frozenset({"rera_projects"}): [_FakeResult(scalar=3)],
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(scalar=11000),
                _FakeResult(rows=[]),
            ],
        }
    )

    detail = await market_api.get_micro_market("Gurugram", "golf-course-road", db=db)

    assert detail.project_count == 3
    assert detail.avg_price_per_sqft == 11000.0
    compiled = [
        _compiled(call.args[0]) for call in db.execute.await_args_list[1:]
    ]
    assert all("rera_projects.micro_market_id" in sql for sql in compiled)
    assert not any("rera_projects.district" in sql for sql in compiled)


@pytest.mark.asyncio
async def test_market_pulse_keeps_the_latest_snapshot_per_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {frozenset({"market_pulse_snapshots"}): [_FakeResult(scalars=[_pulse()])]}
    )

    items = await market_api.list_market_pulse(city=None, db=db)

    # DISTINCT ON is PostgreSQL-only, so the statement must be read through that dialect.
    sql = str(db.execute.await_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    assert "DISTINCT ON (market_pulse_snapshots.city)" in sql
    assert (
        "ORDER BY market_pulse_snapshots.city, market_pulse_snapshots.captured_on DESC,"
        " market_pulse_snapshots.id DESC" in sql
    )
    assert items[0].sentiment is MarketSentiment.positive
    assert items[0].captured_on == date(2026, 1, 2)


@pytest.mark.asyncio
async def test_market_pulse_applies_the_city_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db({frozenset({"market_pulse_snapshots"}): [_FakeResult(scalars=[])]})

    await market_api.list_market_pulse(city="Gurugram", db=db)

    # Case-insensitive, like the micro-market `{city}` segment. The site 301s any
    # path with an uppercase letter to its lowercase form, so a client that reuses
    # a city it read off a URL would filter an exact match down to nothing.
    compiled = _compiled(db.execute.await_args_list[0].args[0])
    assert "lower(market_pulse_snapshots.city) = " in compiled
    assert "'gurugram'" in compiled


async def test_market_pulse_city_filter_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same city spelled three ways compiles to one filter."""
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    seen = set()
    for spelling in ("Gurugram", "gurugram", "GURUGRAM"):
        db = _routed_db({frozenset({"market_pulse_snapshots"}): [_FakeResult(scalars=[])]})
        await market_api.list_market_pulse(city=spelling, db=db)
        seen.add(_compiled(db.execute.await_args_list[0].args[0]))
    assert len(seen) == 1, seen


@pytest.mark.asyncio
async def test_map_projects_applies_the_bounding_box_and_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    project = SimpleNamespace(
        id=1,
        slug="alpha-one",
        project_name="Alpha One",
        developer_name="Alpha Builders",
    )
    profile = SimpleNamespace(latitude=28.5, longitude=77.1, stage=ProjectStage.under_construction)
    db = _routed_db(
        {
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(project, profile)])
            ]
        }
    )

    points = await market_api.list_map_projects(**_BBOX, db=db)

    stmt = db.execute.await_args_list[0].args[0]
    sql = _compiled(stmt)
    for expected in (
        "rera_project_profiles.latitude >= 28.0",
        "rera_project_profiles.latitude <= 29.0",
        "rera_project_profiles.longitude >= 76.0",
        "rera_project_profiles.longitude <= 78.0",
        "rera_project_profiles.latitude IS NOT NULL",
        "rera_project_profiles.longitude IS NOT NULL",
        "rera_projects.slug IS NOT NULL",
    ):
        assert expected in sql
    assert market_api.MAP_POINT_LIMIT in stmt.compile(dialect=postgresql.dialect()).params.values()
    assert len(points) == 1
    assert points[0].slug == "alpha-one"
    assert points[0].latitude == 28.5
    assert points[0].stage is ProjectStage.under_construction
