"""GET /blog/posts query keys: unknown keys and the admin-only status filter give 422."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.blogs import BlogCategory, BlogPost, BlogTag

pytestmark = pytest.mark.asyncio


async def test_category_id_is_rejected_as_unknown_key(client: AsyncClient) -> None:
    r = await client.get("/api/v1/blog/posts", params={"category_id": 1})
    assert r.status_code == 422, r.text
    fields = r.json()["error"]["details"]["fields"]
    assert any(item["field"] == "query.category_id" for item in fields)


async def test_keywords_alias_is_rejected(client: AsyncClient) -> None:
    r = await client.get("/api/v1/blog/posts", params={"keywords": "real-estate"})
    assert r.status_code == 422, r.text
    fields = r.json()["error"]["details"]["fields"]
    assert any(item["field"] == "query.keywords" for item in fields)


async def test_public_status_filter_is_rejected(client: AsyncClient) -> None:
    r = await client.get("/api/v1/blog/posts", params={"status": "draft"})
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "STATUS_FILTER_ADMIN_ONLY"
    assert error["details"]["field"] == "query.status"


async def test_public_list_without_status_still_works(client: AsyncClient) -> None:
    r = await client.get("/api/v1/blog/posts", params={"tags": "guides"})
    assert r.status_code == 200, r.text
    assert "items" in r.json()


@pytest_asyncio.fixture
async def published_post_with_taxonomy(db_session) -> dict:
    """One published post with one category and one tag."""
    suffix = uuid.uuid4().hex[:8]
    category = BlogCategory(name=f"Known {suffix}", slug=f"known-cat-{suffix}")
    tag = BlogTag(name=f"Known {suffix}", slug=f"known-tag-{suffix}")
    post = BlogPost(
        title=f"Filter Post {suffix}",
        slug=f"filter-post-{suffix}",
        content="Content " * 10,
        active=True,
        status="published",
        published_at=datetime.now(timezone.utc),
        categories=[category],
        tags=[tag],
    )
    db_session.add(post)
    await db_session.flush()
    return {"post_id": post.id, "category_slug": category.slug, "tag_slug": tag.slug}


async def _listed_ids(client: AsyncClient, **params) -> list[int]:
    r = await client.get("/api/v1/blog/posts", params=params)
    assert r.status_code == 200, r.text
    return [item["id"] for item in r.json()["items"]]


async def test_unfiltered_list_shows_the_published_post(
    client: AsyncClient, published_post_with_taxonomy: dict
) -> None:
    assert published_post_with_taxonomy["post_id"] in await _listed_ids(client)


async def test_known_category_and_tag_return_the_post(
    client: AsyncClient, published_post_with_taxonomy: dict
) -> None:
    ids = await _listed_ids(
        client,
        categories=published_post_with_taxonomy["category_slug"],
        tags=published_post_with_taxonomy["tag_slug"],
    )
    assert ids == [published_post_with_taxonomy["post_id"]]


async def test_unknown_category_returns_an_empty_page(
    client: AsyncClient, published_post_with_taxonomy: dict
) -> None:
    r = await client.get("/api/v1/blog/posts", params={"categories": "no-such-category-slug"})
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    assert r.json()["has_more"] is False


async def test_unknown_tag_returns_an_empty_page(
    client: AsyncClient, published_post_with_taxonomy: dict
) -> None:
    r = await client.get("/api/v1/blog/posts", params={"tags": "no-such-tag-slug"})
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    assert r.json()["has_more"] is False
