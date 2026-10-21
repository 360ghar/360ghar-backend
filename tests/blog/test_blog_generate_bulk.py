"""POST /blog/generate-bulk returns one CursorPage, not a bare array."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_generate_bulk_returns_one_cursor_page(admin_authenticated_client: AsyncClient):
    created = await admin_authenticated_client.post(
        "/api/v1/blog/posts",
        json={
            "title": "Bulk Generated Post",
            "content": "<p>This is a sufficiently long blog post body.</p>",
            "excerpt": "Excerpt",
        },
    )
    assert created.status_code == 201, created.text
    post = created.json()
    results = [
        {"blog": post, "images": []},
        {"blog": post, "images": ["https://img.example.com/a.jpg"]},
    ]

    with patch(
        "app.api.api_v1.endpoints.blog.generate_bulk_blogs",
        new_callable=AsyncMock,
        return_value=results,
    ):
        response = await admin_authenticated_client.post(
            "/api/v1/blog/generate-bulk", json={"count": 2}
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    assert len(body["items"]) == 2
    assert body["items"][1]["images"] == ["https://img.example.com/a.jpg"]
    assert body["limit"] == 2
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["total"] is None
