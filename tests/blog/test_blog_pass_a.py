"""Contract pass A (BE-content): blog preview token, PATCH rules, visibility and timestamps."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.blogs import BlogPost
from app.models.enums import BlogPostStatus
from app.schemas.blog import BlogPost as PublicBlogPost
from app.schemas.blog import BlogPostAdmin, BlogPostUpdate
from app.services.blog import _apply_status_update


def _post(**overrides) -> SimpleNamespace:
    base = {
        "status": BlogPostStatus.draft.value,
        "active": False,
        "published_at": None,
        "scheduled_at": None,
        "preview_token": "preview-abc",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPreviewToken:
    def test_public_post_schema_has_no_preview_token(self):
        assert "preview_token" not in PublicBlogPost.model_fields

    def test_admin_schema_carries_the_preview_token(self):
        assert "preview_token" in BlogPostAdmin.model_fields

    def test_status_change_clears_the_preview_token(self):
        post = _post()

        _apply_status_update(post, BlogPostUpdate(status=BlogPostStatus.published))

        assert post.preview_token is None
        assert post.status == BlogPostStatus.published.value

    def test_status_change_to_archived_clears_the_preview_token(self):
        post = _post(status=BlogPostStatus.published.value, active=True)

        _apply_status_update(post, BlogPostUpdate(status=BlogPostStatus.archived))

        assert post.preview_token is None

    def test_same_status_keeps_the_preview_token(self):
        post = _post()

        _apply_status_update(post, BlogPostUpdate(status=BlogPostStatus.draft))

        assert post.preview_token == "preview-abc"


class TestPatchSemantics:
    def test_sent_null_is_recorded_so_the_field_can_be_cleared(self):
        body = BlogPostUpdate(excerpt=None, cover_image_url=None, categories=None, tags=None)
        assert {"excerpt", "cover_image_url", "categories", "tags"} <= body.model_fields_set

    @pytest.mark.parametrize("field", ["title", "content", "active", "status"])
    def test_non_nullable_fields_reject_null(self, field):
        with pytest.raises(ValidationError):
            BlogPostUpdate.model_validate({field: None})

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(ValidationError):
            BlogPostUpdate.model_validate({"title": "New", "owner_id": 1})


class TestTimestamps:
    @pytest.mark.parametrize("table", ["blog_posts", "blog_categories", "blog_tags"])
    def test_blog_timestamps_are_timezone_aware(self, table):
        columns = BlogPost.metadata.tables[table].c
        assert columns.created_at.type.timezone is True


@pytest.mark.asyncio
async def test_unknown_query_key_on_post_list_is_422(blog_http):
    response = await blog_http.get("/api/v1/blog/posts?bogus=1")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_public_list_hides_archived_rows_that_still_have_active_true(blog_http, db_session):
    tag = uuid.uuid4().hex[:8]
    archived = BlogPost(
        title=f"Archived {tag}",
        slug=f"archived-{tag}",
        content="Content " * 10,
        active=True,
        status=BlogPostStatus.archived.value,
    )
    published = BlogPost(
        title=f"Published {tag}",
        slug=f"published-{tag}",
        content="Content " * 10,
        active=True,
        status=BlogPostStatus.published.value,
    )
    db_session.add_all([archived, published])
    await db_session.commit()

    response = await blog_http.get("/api/v1/blog/posts?include_total=true&limit=100")

    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert f"Published {tag}" in titles
    assert f"Archived {tag}" not in titles


@pytest.fixture
async def blog_http(client):
    return client
