"""Design studio errors use fixed client text. Provider detail is logged, never returned."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.services.ai.image_gen import service
from app.services.ai.image_gen.service import _AgnesImageError

GENERATE_URL = "/api/v1/design-studio/generate"
BODY = {"mode": "text-to-image", "prompt": "A calm bedroom with teak furniture"}


@pytest.mark.asyncio
async def test_provider_body_is_absent_from_error_response(client: AsyncClient):
    """A provider error body never reaches the caller, even when it is short."""
    provider_body = "PROVIDER-SECRET-BODY quota details for project 9981"
    with patch.object(service, "_call_agnes", side_effect=_AgnesImageError(500, provider_body)):
        response = await client.post(GENERATE_URL, json=BODY)

    assert response.status_code == 422
    assert "PROVIDER-SECRET-BODY" not in response.text
    assert "9981" not in response.text
    error = response.json()["error"]
    assert error["message"] == "The image could not be generated. Try again."
    assert error["code"] == "GENERATION_FAILED"


@pytest.mark.asyncio
async def test_unexpected_exception_text_is_absent_from_error_response(client: AsyncClient):
    with patch.object(service, "_call_agnes", side_effect=RuntimeError("INTERNAL-DB-DETAIL 77")):
        response = await client.post(GENERATE_URL, json=BODY)

    assert response.status_code == 422
    assert "INTERNAL-DB-DETAIL" not in response.text


@pytest.mark.asyncio
async def test_quota_error_uses_fixed_text_and_status(client: AsyncClient):
    with patch.object(
        service, "_call_agnes", side_effect=_AgnesImageError(429, "rate limit for key abc")
    ):
        response = await client.post(GENERATE_URL, json=BODY)

    assert response.status_code == 429
    assert "abc" not in response.text
    assert response.json()["error"]["message"] == "Image generation limit reached. Try again later."


@pytest.mark.asyncio
async def test_missing_api_key_does_not_reveal_setup_state(client: AsyncClient):
    with patch.object(service.settings, "AGNES_AI_API_KEY", None):
        response = await client.post(GENERATE_URL, json=BODY)

    assert response.status_code == 503
    text = response.text.lower()
    assert "api key" not in text
    assert "configured" not in text
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
