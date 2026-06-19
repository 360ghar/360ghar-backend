"""Tests for blog post status lifecycle and public preview-by-token.

Covers:
- draft creation (default status)
- publish via status update
- archive via status update
- scheduled posts + auto-publish via ``publish_scheduled_posts``
- preview token generation (admin) and public fetch by token
- non-admin cannot generate a preview token
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blogs import BlogPost
from app.services.blog import publish_scheduled_posts

pytestmark = pytest.mark.asyncio


def _create_payload(title: str, **extra) -> dict:
    payload = {
        "title": title,
        "content": "<p>This is a sufficiently long blog post body.</p>",
        "excerpt": "Excerpt",
    }
    payload.update(extra)
    return payload


@pytest_asyncio.fixture
async def draft_post(admin_authenticated_client: AsyncClient) -> dict:
    response = await admin_authenticated_client.post(
        "/api/v1/blog/posts",
        json=_create_payload("Draft Status Post", status="draft"),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_create_post_defaults_to_draft(admin_authenticated_client: AsyncClient):
    response = await admin_authenticated_client.post(
        "/api/v1/blog/posts",
        json=_create_payload("Default Draft Post"),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "draft"
    assert data["active"] is False


async def test_create_post_with_draft_status(draft_post: dict):
    assert draft_post["status"] == "draft"
    assert draft_post["active"] is False


async def test_publish_post_via_status_update(
    admin_authenticated_client: AsyncClient, draft_post: dict
):
    response = await admin_authenticated_client.put(
        f"/api/v1/blog/posts/{draft_post['id']}",
        json={"status": "published"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "published"
    assert data["active"] is True
    assert data["published_at"] is not None


async def test_archive_post_via_status_update(
    admin_authenticated_client: AsyncClient, draft_post: dict
):
    # First publish, then archive.
    r = await admin_authenticated_client.put(
        f"/api/v1/blog/posts/{draft_post['id']}",
        json={"status": "published"},
    )
    assert r.status_code == 200

    r = await admin_authenticated_client.put(
        f"/api/v1/blog/posts/{draft_post['id']}",
        json={"status": "archived"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "archived"
    assert data["active"] is False


async def test_schedule_requires_scheduled_at(admin_authenticated_client: AsyncClient):
    response = await admin_authenticated_client.post(
        "/api/v1/blog/posts",
        json=_create_payload("Schedule Missing At", status="scheduled"),
    )
    # BadRequestException -> 400
    assert response.status_code == 400, response.text


async def test_schedule_and_auto_publish(
    admin_authenticated_client: AsyncClient, db_session: AsyncSession
):
    scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    response = await admin_authenticated_client.post(
        "/api/v1/blog/posts",
        json=_create_payload(
            "Scheduled Auto Publish",
            status="scheduled",
            scheduled_at=scheduled_at.isoformat(),
        ),
    )
    assert response.status_code == 200, response.text
    post = response.json()
    assert post["status"] == "scheduled"
    assert post["active"] is False

    # Run the scheduled-publish service step.
    published_count = await publish_scheduled_posts(db_session)
    assert published_count >= 1

    refreshed = await db_session.get(BlogPost, post["id"])
    assert refreshed.status == "published"
    assert refreshed.active is True
    assert refreshed.published_at is not None


async def test_preview_token_generation_and_public_fetch(
    admin_authenticated_client: AsyncClient,
    client: AsyncClient,
    draft_post: dict,
):
    # Non-admin cannot generate a token.
    # (covered separately; here admin generates)

    gen = await admin_authenticated_client.post(
        f"/api/v1/blog/posts/{draft_post['id']}/preview-token"
    )
    assert gen.status_code == 200, gen.text
    token_data = gen.json()
    assert token_data["preview_token"]
    assert token_data["preview_url"].endswith(token_data["preview_token"])

    # Public (no auth) fetch by token works for a draft.
    fetch = await client.get(f"/api/v1/blog/posts/preview/{token_data['preview_token']}")
    assert fetch.status_code == 200, fetch.text
    fetched = fetch.json()
    assert fetched["id"] == draft_post["id"]
    assert fetched["status"] == "draft"
    # Public-safe response must not expose the preview token itself.
    assert "preview_token" not in fetched


async def test_non_admin_cannot_generate_preview_token(
    db_session: AsyncSession, authenticated_client: AsyncClient
):
    # Create a draft post directly (avoids mixing admin + user client fixtures,
    # which share the same dependency-overrides map on test_app).
    import uuid as _uuid

    from app.models.blogs import BlogPost as BlogPostModel

    post = BlogPostModel(
        title="Non Admin Preview Post",
        slug=f"non-admin-preview-{_uuid.uuid4().hex[:8]}",
        content="<p>Body content for the non-admin preview test.</p>",
        active=False,
        status="draft",
    )
    db_session.add(post)
    await db_session.flush()
    await db_session.refresh(post)

    response = await authenticated_client.post(
        f"/api/v1/blog/posts/{post.id}/preview-token"
    )
    assert response.status_code == 403, response.text


async def test_preview_unknown_token_returns_404(client: AsyncClient):
    response = await client.get("/api/v1/blog/posts/preview/does-not-exist")
    assert response.status_code == 404, response.text


async def test_admin_status_filter_on_list(
    admin_authenticated_client: AsyncClient, draft_post: dict
):
    # draft_post is a draft; ensure admin can filter to drafts only.
    response = await admin_authenticated_client.get(
        "/api/v1/blog/posts", params={"status": "draft"}
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert all(item["status"] == "draft" for item in items)
    assert any(item["id"] == draft_post["id"] for item in items)
