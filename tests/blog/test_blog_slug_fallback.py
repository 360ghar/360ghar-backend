"""A post title with no ASCII letters or digits still gets a stored slug."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_non_ascii_titles_get_generated_unique_slugs(admin_authenticated_client: AsyncClient):
    slugs = []
    for title in ("भारत में घर", "दिल्ली का बाज़ार"):
        response = await admin_authenticated_client.post(
            "/api/v1/blog/posts",
            json={
                "title": title,
                "content": "<p>This is a sufficiently long blog post body.</p>",
                "excerpt": "Excerpt",
            },
        )
        assert response.status_code == 201, response.text
        slugs.append(response.json()["slug"])

    assert slugs == ["post", "post-2"]
