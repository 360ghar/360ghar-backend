from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.dialects import postgresql

from app.api.api_v1.endpoints import blog as blog_api
from app.api.api_v1.endpoints import content as content_api
from app.api.api_v1.endpoints.data_hub import rera as rera_api
from app.api.api_v1.endpoints.data_hub import scraper as scraper_api
from app.config import settings
from app.core.exceptions import NotFoundException
from app.infrastructure.errors import _http_error_response
from app.schemas.blog import BlogPost, BlogTag
from app.schemas.data_hub import DataHubProvenanceSummary
from app.schemas.pagination import CursorParams
from app.services.blog import is_hrera_derived_digest, list_blog_posts


@pytest.mark.asyncio
@pytest.mark.parametrize("scraper_name", ["rera_projects", "rera_complaints"])
async def test_manual_hrera_trigger_is_denied_before_import(scraper_name, monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    import_scraper = MagicMock(side_effect=AssertionError("scraper import must not happen"))
    monkeypatch.setattr(scraper_api, "import_module", import_scraper)

    with pytest.raises(HTTPException) as exc_info:
        await scraper_api.trigger_scraper(
            scraper_name, current_user=MagicMock(id=1)
        )

    assert exc_info.value.status_code == 503
    import_scraper.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        (
            rera_api.list_rera_projects,
            {
                "status": None,
                "q": None,
                "page": CursorParams(cursor=None, limit=20, include_total=False),
            },
        ),
        (rera_api.verify_rera_project, {"rera_number": "HRERA-1"}),
        (
            rera_api.list_builders,
            {
                "q": None,
                "order_by": None,
                "page": CursorParams(cursor=None, limit=20, include_total=False),
            },
        ),
        (rera_api.get_builder, {"slug": "example-builder"}),
    ],
)
async def test_public_hrera_routes_fail_closed_before_database_query(
    endpoint, kwargs, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(**kwargs, db=db)

    assert exc_info.value.status_code == 503
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_locality_manifest_is_hidden_but_other_manifest_rows_remain(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    locality_db = AsyncMock()

    hidden_response = Response()
    hidden = await content_api.content_manifest(
        response=hidden_response,
        entity_type="locality",
        limit=100,
        db=locality_db,
    )

    assert hidden.items == []
    assert hidden_response.headers["Cache-Control"] == "no-store"
    locality_db.execute.assert_not_awaited()

    public_db = MagicMock()
    execute_result = MagicMock()
    execute_result.all.return_value = []
    public_db.execute = AsyncMock(return_value=execute_result)
    public_manifest_response = Response()
    await content_api.content_manifest(
        response=public_manifest_response, entity_type=None, limit=100, db=public_db
    )
    assert public_manifest_response.headers["Cache-Control"] == "no-store"
    statement = str(public_db.execute.await_args.args[0]).lower()
    assert "content_blocks.entity_type !=" in statement
    assert "locality" in public_db.execute.await_args.args[0].compile().params.values()


@pytest.mark.asyncio
async def test_locality_content_is_hidden_without_query_while_property_content_remains_readable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    db = MagicMock()
    db.execute = AsyncMock()

    locality_response = Response()
    with pytest.raises(NotFoundException) as locality_error:
        await content_api.get_content(
            response=locality_response,
            entity_type="locality",
            slug="sector-56",
            locale="en",
            db=db,
        )

    db.execute.assert_not_awaited()
    assert locality_response.headers["Cache-Control"] == "no-store"
    assert locality_error.value.headers == {"Cache-Control": "no-store"}
    error_response = _http_error_response(
        SimpleNamespace(
            url=SimpleNamespace(path="/api/v1/content/locality/sector-56")
        ),
        locality_error.value,
    )
    assert error_response.headers["Cache-Control"] == "no-store"

    execute_result = MagicMock()
    property_content = SimpleNamespace(entity_type="property", slug="123")
    execute_result.scalar_one_or_none.return_value = property_content
    db.execute = AsyncMock(return_value=execute_result)
    result = await content_api.get_content(
        response=Response(),
        entity_type="property",
        slug="123",
        locale="en",
        db=db,
    )
    assert result is property_content
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_rera_verification_is_unknown_or_verified_only_from_safe_summary(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    project = SimpleNamespace(
        id=1,
        rera_number="HRERA-1",
        status="registered",
        project_name="Project One",
    )
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = project
    db = MagicMock()
    db.execute = AsyncMock(return_value=query_result)
    monkeypatch.setattr(
        rera_api,
        "get_public_provenance_summaries",
        AsyncMock(return_value={1: DataHubProvenanceSummary()}),
    )

    unverified = await rera_api.verify_rera_project("HRERA-1", db=db)

    assert unverified.valid is None
    assert unverified.verification_status == "unverified"

    monkeypatch.setattr(
        rera_api,
        "get_public_provenance_summaries",
        AsyncMock(
            return_value={
                1: DataHubProvenanceSummary(verification_status="verified")
            }
        ),
    )
    verified = await rera_api.verify_rera_project("HRERA-1", db=db)
    assert verified.valid is True
    assert verified.verification_status == "verified"
    assert verified.official_source_url == rera_api._HRERA_PROJECT_SEARCH_URL
    assert verified.official_source_url.startswith("https://haryanarera.gov.in/")


def _post(title: str, slug: str, tags: list[BlogTag]) -> BlogPost:
    return BlogPost(
        id=1,
        title=title,
        slug=slug,
        content="<p>A test blog post with enough content.</p>",
        created_at=datetime(2026, 10, 23, tzinfo=UTC),
        active=True,
        status="published",
        categories=[],
        tags=tags,
    )


def test_digest_detection_covers_tagged_and_legacy_title_markers() -> None:
    digest_tag = BlogTag(
        id=1,
        name="Market digest",
        slug="market-digest",
        created_at=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert is_hrera_derived_digest(_post("A renamed digest", "digest-tag", [digest_tag]))
    assert is_hrera_derived_digest(
        _post("Gurugram property data digest: week 43 of 2026", "digest-title", [])
    )
    assert is_hrera_derived_digest(
        SimpleNamespace(title="A legacy title", tags=[], sources=[{"name": "HRERA registry"}])
    )
    assert not is_hrera_derived_digest(_post("A market story", "market-story", []))


def test_digest_detection_handles_cached_dictionary_payloads() -> None:
    assert is_hrera_derived_digest(
        {
            "title": "A renamed digest",
            "tags": [{"slug": "market-digest"}],
            "sources": [],
        }
    )
    assert is_hrera_derived_digest(
        {
            "title": "A legacy title",
            "tags": [],
            "sources": [{"name": "HRERA registry"}],
        }
    )


@pytest.mark.asyncio
async def test_public_blog_list_filters_cached_digest_items(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    digest_post = _post("Gurugram property data digest: week 43 of 2026", "digest", [])
    public_post = _post("A market story", "market-story", [])
    monkeypatch.setattr(
        blog_api,
        "list_posts_cached",
        AsyncMock(return_value=([digest_post, public_post], None, None)),
    )

    page = await blog_api.list_posts(
        q=None,
        categories=None,
        tags=None,
        status=None,
        page=CursorParams(cursor=None, limit=20, include_total=False),
        db=AsyncMock(),
        current_user=None,
    )

    assert [post.slug for post in page["items"]] == ["market-story"]


@pytest.mark.asyncio
async def test_public_blog_detail_and_preview_hide_cached_digest_items(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
    digest_post = _post("Gurugram property data digest: week 43 of 2026", "digest", [])
    monkeypatch.setattr(blog_api, "get_blog_post_cached", AsyncMock(return_value=digest_post))
    monkeypatch.setattr(
        blog_api, "get_post_by_preview_token", AsyncMock(return_value=digest_post)
    )

    with pytest.raises(HTTPException) as detail_error:
        await blog_api.get_post("digest", db=AsyncMock(), current_user=None)
    with pytest.raises(HTTPException) as preview_error:
        await blog_api.get_post_by_preview("token", db=AsyncMock())

    assert detail_error.value.status_code == 404
    assert preview_error.value.status_code == 404


@pytest.mark.asyncio
async def test_public_blog_query_excludes_known_digest_items_when_hrera_is_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False)
    db = MagicMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=execute_result)

    await list_blog_posts(
        db,
        q=None,
        categories=None,
        tags=None,
        cursor_payload={},
        limit=10,
    )

    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    parameters = str(compiled.params).lower()
    sql = str(compiled).lower()
    assert "blog_posts.sources @>" in sql
    assert "market-digest" in parameters
    assert "gurugram property data digest: week" in parameters


@pytest.mark.asyncio
async def test_public_blog_query_keeps_digest_items_when_hrera_is_on(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = MagicMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=execute_result)

    await list_blog_posts(
        db,
        q=None,
        categories=None,
        tags=None,
        cursor_payload={},
        limit=10,
    )

    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect())).lower()
    assert "blog_posts.sources @>" not in sql


def test_builder_detail_queries_have_stable_tie_breakers() -> None:
    project_sql = str(rera_api._builder_projects_query("builder")).lower()
    complaint_sql = str(rera_api._builder_complaints_query("builder")).lower()

    assert "order by rera_projects.id" in project_sql
    assert "rera_complaints.order_date desc, rera_complaints.id desc" in complaint_sql
