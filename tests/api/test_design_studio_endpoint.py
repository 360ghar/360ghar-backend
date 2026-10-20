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
        patch(
            "app.services.ai.image_gen.service.generate_image",
            new_callable=AsyncMock,
            return_value=fake,
        ),
        patch("app.middleware.rate_limit.get_cache_manager", return_value=_MemoryCache()),
    ):
        codes = [
            (
                await client.post("/api/v1/design-studio/generate", json=body, headers=headers)
            ).status_code
            for _ in range(11)
        ]

        other_ip = await client.post(
            "/api/v1/design-studio/generate", json=body, headers={"X-Forwarded-For": "198.51.100.9"}
        )

    assert codes[:10] == [200] * 10
    assert codes[10] == 429
    assert other_ip.status_code == 200


@pytest.mark.asyncio
async def test_generate_answers_with_image_only_and_rejects_unknown_keys(client: AsyncClient):
    fake = ImageGenResponse(success=True, image="data:image/png;base64,aGVsbG8=")
    with patch(
        "app.services.ai.image_gen.service.generate_image",
        new_callable=AsyncMock,
        return_value=fake,
    ):
        ok = await client.post(
            "/api/v1/design-studio/generate",
            json={"mode": "text-to-image", "prompt": "A calm bedroom with teak furniture"},
        )
        rejected = await client.post(
            "/api/v1/design-studio/generate",
            json={
                "mode": "text-to-image",
                "prompt": "A calm bedroom with teak furniture",
                "mimeType": "image/png",
            },
        )

    assert ok.json() == {"image": "data:image/png;base64,aGVsbG8="}
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_image_over_the_7_million_character_cap_is_rejected(client: AsyncClient):
    """branch-drift-15: the source image cap is enforced at the request boundary."""
    fake = ImageGenResponse(success=True, image="data:image/png;base64,aGVsbG8=")
    with patch(
        "app.services.ai.image_gen.service.generate_image",
        new_callable=AsyncMock,
        return_value=fake,
    ) as generate:
        too_big = await client.post(
            "/api/v1/design-studio/generate",
            json={
                "mode": "image-to-image",
                "prompt": "Make it brighter",
                "image": "A" * 7_000_001,
                "mime_type": "image/png",
            },
        )
        at_cap = await client.post(
            "/api/v1/design-studio/generate",
            json={
                "mode": "image-to-image",
                "prompt": "Make it brighter",
                "image": "A" * 7_000_000,
                "mime_type": "image/png",
            },
        )

    assert too_big.status_code == 422
    assert at_cap.status_code == 200
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_ratio_outside_the_allowed_list_is_rejected(client: AsyncClient):
    """branch-drift-15: the ratio validator answers 422 and never calls the provider."""
    fake = ImageGenResponse(success=True, image="data:image/png;base64,aGVsbG8=")
    with patch(
        "app.services.ai.image_gen.service.generate_image",
        new_callable=AsyncMock,
        return_value=fake,
    ) as generate:
        bad = await client.post(
            "/api/v1/design-studio/generate",
            json={"mode": "text-to-image", "prompt": "A calm bedroom", "ratio": "5:7"},
        )
        good = await client.post(
            "/api/v1/design-studio/generate",
            json={"mode": "text-to-image", "prompt": "A calm bedroom", "ratio": "21:9"},
        )

    assert bad.status_code == 422
    assert good.status_code == 200
    assert generate.await_count == 1
