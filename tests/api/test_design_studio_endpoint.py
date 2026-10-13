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
