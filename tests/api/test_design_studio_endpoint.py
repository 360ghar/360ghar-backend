"""Design studio image generation is public: no login, IP rate limited."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.ai.image_gen.schemas import ImageGenResponse


@pytest.mark.asyncio
async def test_generate_works_without_auth(client: AsyncClient):
    fake = ImageGenResponse(success=True, image="data:image/png;base64,aGVsbG8=")
    with patch(
        "app.services.ai.image_gen.service.generate_image",
        new_callable=AsyncMock,
        return_value=fake,
    ):
        response = await client.post(
            "/api/v1/design-studio/generate",
            json={"mode": "text-to-image", "prompt": "A calm bedroom with teak furniture"},
        )

    assert response.status_code == 200
    assert response.json()["image"] == "data:image/png;base64,aGVsbG8="


@pytest.mark.asyncio
async def test_generate_is_rate_limited_per_ip(client: AsyncClient):
    fake = ImageGenResponse(success=True, image="data:image/png;base64,aGVsbG8=")
    headers = {"X-Forwarded-For": "203.0.113.77"}
    body = {"mode": "text-to-image", "prompt": "A calm bedroom with teak furniture"}
    store: dict[str, int] = {}

    class _MemoryCache:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ttl=None):
            store[key] = value

    with (
        patch("app.services.ai.image_gen.service.generate_image", new_callable=AsyncMock, return_value=fake),
        patch("app.middleware.rate_limit.get_cache_manager", return_value=_MemoryCache()),
    ):
        codes = [
            (await client.post("/api/v1/design-studio/generate", json=body, headers=headers)).status_code
            for _ in range(11)
        ]

    assert codes[:10] == [200] * 10
    assert codes[10] == 429
