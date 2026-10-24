"""Unit tests for the project intelligence endpoints (Phase 3 REST surface).

The database is mocked: the fake routes each statement to a canned result by the
set of tables the statement reads, so a query-count assertion proves the endpoint
issues a fixed number of statements instead of one per row.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.api_v1.endpoints.data_hub import projects as projects_api
from app.config import settings
from app.models.enums import ProjectPersonRole, ProjectPriceSource, ProjectStage
from app.schemas.data_hub import ProjectDetailResponse
from app.schemas.pagination import CursorParams

_TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)")

_PROFILE_FIELDS: dict[str, Any] = {
    "portal_project_id": None,
    "licensed_land_acres": None,
    "land_area_sqm": None,
    "proposed_far": None,
    "permissible_far": None,
    "towers": None,
    "floors": None,
    "total_units": None,
    "units_per_acre": None,
    "rera_received_date": None,
    "construction_start_date": None,
    "proposed_completion_date": None,
    "launch_price_per_sqft": None,
    "current_price_per_sqft": None,
    "latitude": None,
    "longitude": None,
    "stage": None,
}

_PROJECT_FIELDS: dict[str, Any] = {
    "id": 1,
    "slug": "alpha-one",
    "rera_number": "HRERA-1",
    "project_name": "Alpha One",
    "developer_name": "Alpha Builders",
    "developer_slug": "alpha-builders",
    "location": "Sector 1",
    "district": "Gurugram",
    "total_units": None,
    "total_area_sqm": None,
    "possession_date": None,
    "status": "registered",
    "complaint_count": 0,
    "source_url": "https://haryanarera.gov.in/view_project/search_project",
    "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    "last_successful_run_id": None,
}


def _profile(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(**{**_PROFILE_FIELDS, **overrides})


def _project(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(**{**_PROJECT_FIELDS, **overrides})


class _ScalarRows:
    def __init__(self, values: list[Any]) -> None:
        self._values = list(values)

    def all(self) -> list[Any]:
        return list(self._values)


class _FakeResult:
    """The small slice of ``sqlalchemy.Result`` the endpoints actually use."""

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
    """A db whose execute() answers by table set. Repeated keys pop in call order."""
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


def _detail_db(
    *,
    project: SimpleNamespace,
    profile: SimpleNamespace | None,
    cost: Any = None,
    statutory: Any = None,
    bank_account: Any = None,
    land_usage: Any = (),
    expenditure: Any = (),
    documents: Any = (),
    facilities: Any = (),
    nocs: Any = (),
    people: Any = (),
    unit_configs: Any = (),
    specifications: Any = (),
    price_history: Any = (),
    nearby: Any = (),
) -> AsyncMock:
    return _routed_db(
        {
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(project, profile)]),
                _FakeResult(rows=list(nearby)),
            ],
            frozenset(
                {
                    "rera_projects",
                    "rera_project_costs",
                    "rera_statutory_approvals",
                    "rera_project_bank_accounts",
                }
            ): [_FakeResult(rows=[(cost, statutory, bank_account)])],
            frozenset({"rera_land_usage"}): [_FakeResult(scalars=land_usage)],
            frozenset({"rera_quarterly_expenditure"}): [_FakeResult(scalars=expenditure)],
            frozenset({"rera_project_documents"}): [_FakeResult(scalars=documents)],
            frozenset({"rera_project_facilities"}): [_FakeResult(scalars=facilities)],
            frozenset({"rera_project_nocs"}): [_FakeResult(scalars=nocs)],
            frozenset({"rera_project_people"}): [_FakeResult(scalars=people)],
            frozenset({"rera_project_unit_configs"}): [_FakeResult(scalars=unit_configs)],
            frozenset({"rera_project_specifications"}): [_FakeResult(scalars=specifications)],
            frozenset({"project_price_history"}): [_FakeResult(scalars=price_history)],
            frozenset({"data_hub_evidence_assertions", "source_documents"}): [
                _FakeResult(rows=[])
            ],
        }
    )


def _page(limit: int = 20) -> CursorParams:
    return CursorParams(cursor=None, limit=limit, include_total=False)


_BASE_LIST_KWARGS: dict[str, Any] = {
    "district": None,
    "stage": None,
    "developer_slug": None,
    "q": None,
    "min_units": None,
    "max_units": None,
}


def _compiled(stmt: Any) -> str:
    """SQL with literals inlined. ``literal_binds`` doubles ``%``, so undo that."""
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    return sql.replace("%%", "%")


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        (projects_api.list_projects, {**_BASE_LIST_KWARGS, "page": _page()}),
        (projects_api.get_project, {"slug": "alpha-one"}),
        (projects_api.list_nearby_projects, {"slug": "alpha-one"}),
        (projects_api.list_project_price_history, {"slug": "alpha-one"}),
        (projects_api.list_project_documents, {"slug": "alpha-one"}),
        (projects_api.get_project_faq, {"slug": "alpha-one"}),
    ],
)
async def test_project_routes_fail_closed_before_database_query(
    endpoint: Any, kwargs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(**kwargs, db=db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "HRERA_DISABLED"
    db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"district": "Gurugram"}, "rera_projects.district = 'Gurugram'"),
        (
            {"stage": ProjectStage.under_construction},
            "rera_project_profiles.stage = 'under_construction'",
        ),
        ({"developer_slug": "alpha-builders"}, "rera_projects.developer_slug = 'alpha-builders'"),
        ({"q": "alpha"}, "rera_projects.project_name ILIKE '%alpha%'"),
        ({"q": "alpha"}, "rera_projects.developer_name ILIKE '%alpha%'"),
        (
            {"min_units": 100},
            "coalesce(rera_project_profiles.total_units, rera_projects.total_units) >= 100",
        ),
        (
            {"max_units": 500},
            "coalesce(rera_project_profiles.total_units, rera_projects.total_units) <= 500",
        ),
    ],
)
async def test_list_projects_applies_each_advertised_filter(
    kwargs: dict[str, Any], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()

    await projects_api.list_projects(**{**_BASE_LIST_KWARGS, **kwargs}, page=_page(), db=db)

    assert expected in _compiled(db.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_list_projects_uses_one_statement_ordered_by_primary_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()

    await projects_api.list_projects(**_BASE_LIST_KWARGS, page=_page(), db=db)

    sql = str(db.execute.await_args_list[0].args[0]).lower()
    assert db.execute.await_count == 1
    assert "order by rera_projects.id" in sql
    assert "count(" not in sql


@pytest.mark.asyncio
async def test_list_projects_excludes_rows_without_a_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _empty_db()

    await projects_api.list_projects(**_BASE_LIST_KWARGS, page=_page(), db=db)

    assert "rera_projects.slug IS NOT NULL" in str(db.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_list_projects_pages_with_a_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    rows = [(_project(id=index, slug=f"p-{index}"), None) for index in (1, 2, 3)]
    db = _routed_db(
        {
            frozenset({"rera_projects", "rera_project_profiles"}): [_FakeResult(rows=rows)],
            frozenset({"data_hub_evidence_assertions", "source_documents"}): [
                _FakeResult(rows=[])
            ],
        }
    )

    page = await projects_api.list_projects(
        district=None,
        stage=None,
        developer_slug=None,
        q=None,
        min_units=None,
        max_units=None,
        page=_page(limit=2),
        db=db,
    )

    assert len(page["items"]) == 2
    assert page["has_more"] is True
    assert page["next_cursor"]
    assert page["items"][0].slug == "p-1"


# ---------------------------------------------------------------------------
# GET /projects/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_detail_returns_404_for_an_unknown_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {frozenset({"rera_projects", "rera_project_profiles"}): [_FakeResult(rows=[])]}
    )

    with pytest.raises(HTTPException) as exc_info:
        await projects_api.get_project("missing", db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("with_children", [False, True])
async def test_project_detail_issues_a_fixed_number_of_queries(
    with_children: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No N+1: the statement count does not depend on how many child rows exist."""
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    count = 20 if with_children else 0
    db = _detail_db(
        project=_project(),
        profile=_profile(total_units=120, towers=3, licensed_land_acres=12),
        cost=SimpleNamespace(total_cost=1000),
        land_usage=[
            SimpleNamespace(particular=f"use-{i}", area_sqm=1, area_acres=1, percentage=1)
            for i in range(count)
        ],
        documents=[
            SimpleNamespace(
                ordinal=i, description=f"doc-{i}", uploaded_on=None, view_url=None
            )
            for i in range(count)
        ],
        people=[
            SimpleNamespace(
                role=ProjectPersonRole.director,
                name=f"person-{i}",
                pan_last4="1234",
                photo_url=None,
                email=None,
                phones=None,
                address=None,
            )
            for i in range(count)
        ],
        nearby=[(_project(id=9, slug="nearby-9"), None)],
    )

    detail = await projects_api.get_project("alpha-one", db=db)

    assert db.execute.await_count == 13
    assert len(detail.land_usage) == count
    assert len(detail.documents) == count
    assert [item.slug for item in detail.nearby] == ["nearby-9"]


@pytest.mark.asyncio
async def test_project_detail_never_leaks_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two model exclusions are hard requirements: contact details never serialize."""
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _detail_db(
        project=_project(),
        profile=_profile(total_units=120),
        bank_account=SimpleNamespace(
            bank_name="Test Bank",
            branch_name="Test Branch",
            ifsc="TEST0001",
            micr="000001",
            branch_code="001",
            account_number="9999888877776666",
            operators="Ops Secret Person",
        ),
        people=[
            SimpleNamespace(
                role=ProjectPersonRole.managing_director,
                name="Test Person",
                pan_last4="1234",
                photo_url="https://example.test/photo.jpg",
                email="person@example.com",
                phones="+91 9000000001",
                address="Unit 7, Secret Test Tower, Testville",
            )
        ],
    )

    body = (await projects_api.get_project("alpha-one", db=db)).model_dump_json()

    for leaked in (
        "account_number",
        "operators",
        "email",
        "phones",
        "address",
        "9999888877776666",
        "Ops Secret Person",
        "person@example.com",
        "+91 9000000001",
        "Secret Test Tower",
    ):
        assert leaked not in body
    assert "Test Bank" in body
    assert "Test Person" in body
    forbidden = {"account_number", "operators", "email", "phones", "address"}
    assert forbidden.isdisjoint(ProjectDetailResponse.model_fields)


@pytest.mark.asyncio
async def test_project_detail_serializes_every_nested_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _detail_db(
        project=_project(possession_date=date(2027, 3, 1)),
        profile=_profile(
            total_units=120,
            towers=3,
            licensed_land_acres=12,
            proposed_far=2.5,
            proposed_completion_date=date(2028, 12, 31),
            current_price_per_sqft=12500,
            stage=ProjectStage.under_construction,
        ),
        cost=SimpleNamespace(
            land_cost=1,
            construction_cost=2,
            infrastructure_cost=3,
            other_cost=4,
            total_cost=10,
        ),
        statutory=SimpleNamespace(
            loi_number="LOI-1",
            loi_date=None,
            licence_number="LIC-1",
            licence_date=None,
            electric_load_kw=100,
            water_available=True,
            storm_water_available=False,
            sewerage_available=True,
            plan_approvals={"fire": True},
        ),
        land_usage=[
            SimpleNamespace(particular="plots", area_sqm=1, area_acres=2, percentage=3)
        ],
        expenditure=[
            SimpleNamespace(category="apartment", year=2026, quarter=1, particular="x", amount=5)
        ],
        documents=[
            SimpleNamespace(ordinal=1, description="Approval", uploaded_on=None, view_url="u")
        ],
        facilities=[SimpleNamespace(facility="Clubhouse", estimated_cost=7, status="done")],
        nocs=[
            SimpleNamespace(
                facility="Water", provider_agency="Agency", approved=True, approval_reference="R"
            )
        ],
        unit_configs=[
            SimpleNamespace(
                ordinal=1,
                unit_type="3BHK",
                carpet_area_sqm=100,
                built_up_area_sqm=120,
                super_built_up_area_sqm=140,
                carpet_efficiency=0.7,
                units=10,
                towers=1,
                parkings=2,
                price=1,
            )
        ],
        specifications=[
            SimpleNamespace(scope="unit", unit_type="all", spec_key="flooring", spec_value="tiles")
        ],
        price_history=[
            SimpleNamespace(
                quarter="2026-Q1",
                period_start=date(2026, 1, 1),
                unit_type="all",
                price_per_sqft=12000,
                source=ProjectPriceSource.filing,
            )
        ],
    )

    detail = await projects_api.get_project("alpha-one", db=db)

    assert detail.slug == "alpha-one"
    assert detail.district == "Gurugram"
    assert detail.stage is ProjectStage.under_construction
    assert detail.land_area_acres == 12.0
    assert detail.cost is not None and detail.cost.total_cost == 10.0
    assert detail.statutory is not None and detail.statutory.plan_approvals == {"fire": True}
    assert len(detail.expenditure) == 1
    assert len(detail.facilities) == 1
    assert len(detail.nocs) == 1
    assert len(detail.unit_configs) == 1
    assert len(detail.specifications) == 1
    assert detail.price_history[0].source is ProjectPriceSource.filing
    assert detail.profile is not None and detail.profile.towers == 3
    assert detail.faq


# ---------------------------------------------------------------------------
# Nearby / price history / documents / FAQ
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nearby_excludes_the_project_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(_project(), None)]),
                _FakeResult(rows=[(_project(id=2, slug="beta-two"), None)]),
            ],
            frozenset({"data_hub_evidence_assertions", "source_documents"}): [
                _FakeResult(rows=[])
            ],
        }
    )

    items = await projects_api.list_nearby_projects("alpha-one", db=db)

    nearby_sql = str(db.execute.await_args_list[1].args[0])
    assert "rera_projects.id !=" in nearby_sql
    assert "rera_projects.district =" in nearby_sql
    assert [item.slug for item in items] == ["beta-two"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        projects_api.list_nearby_projects,
        projects_api.list_project_price_history,
        projects_api.list_project_documents,
        projects_api.get_project_faq,
    ],
)
async def test_project_subroutes_return_404_for_an_unknown_slug(
    endpoint: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {frozenset({"rera_projects", "rera_project_profiles"}): [_FakeResult(rows=[])]}
    )

    with pytest.raises(HTTPException) as exc_info:
        await endpoint("missing", db=db)

    assert exc_info.value.status_code == 404


def test_empty_profile_produces_no_faq_items() -> None:
    """No filing profile means nothing to answer: no questions with null answers."""
    items = projects_api.build_project_faq(_project(), None, None, [])

    assert items == []


@pytest.mark.asyncio
async def test_faq_route_returns_an_empty_list_without_a_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = _routed_db(
        {
            frozenset({"rera_projects", "rera_project_profiles"}): [
                _FakeResult(rows=[(_project(), None)])
            ],
            frozenset({"rera_project_costs"}): [_FakeResult(scalar=None)],
            frozenset({"rera_project_documents"}): [_FakeResult(scalars=[])],
        }
    )

    faq = await projects_api.get_project_faq("alpha-one", db=db)

    assert faq.items == []


def test_faq_skips_questions_whose_answer_is_missing() -> None:
    project = _project(developer_name=None, possession_date=None)
    profile = _profile(total_units=None, towers=None, licensed_land_acres=None)

    questions = [item.question for item in projects_api.build_project_faq(project, profile, None, [])]

    assert questions == ["What is the RERA registration number of Alpha One?"]
    assert all(item.answer for item in projects_api.build_project_faq(project, profile, None, []))


def test_faq_answers_every_filed_value_it_asks_about() -> None:
    project = _project(possession_date=date(2027, 3, 1))
    profile = _profile(
        total_units=120,
        towers=3,
        licensed_land_acres=12.5,
        proposed_completion_date=date(2028, 12, 31),
    )
    cost = SimpleNamespace(total_cost=1234567)

    items = projects_api.build_project_faq(project, profile, cost, [1, 2, 3])
    answers = {item.question: item.answer for item in items}

    assert len(items) == 9
    assert answers["What is the RERA registration number of Alpha One?"] == "HRERA-1"
    assert answers["Who is the developer of Alpha One?"] == "Alpha Builders"
    assert answers["How many units does Alpha One have?"].startswith("120 units")
    assert answers["How many towers does Alpha One have?"].startswith("3 towers")
    assert answers["What is the land area of Alpha One?"].startswith("12.5000 acres")
    assert answers["When is possession expected for Alpha One?"] == "2027-03-01"
    assert answers["When is Alpha One expected to be completed?"] == "2028-12-31"
    assert answers["What is the estimated cost of Alpha One?"].startswith("INR 1,234,567")
    assert answers["How many documents are on file for Alpha One?"] == "3"
    assert all(item.answer for item in items)


@pytest.mark.asyncio
async def test_a_project_filed_under_the_state_marker_has_no_nearby_projects() -> None:
    """``Haryana`` is the scanner's no-district marker, not a place."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.api.api_v1.endpoints.data_hub import projects as projects_api

    db = AsyncMock()

    rows = await projects_api._nearby_rows(db, SimpleNamespace(id=1, district="Haryana"))

    assert rows == []
    db.execute.assert_not_awaited()
