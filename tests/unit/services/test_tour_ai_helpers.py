from __future__ import annotations

import base64
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tenacity import stop_after_attempt, wait_none

from app.services.ai.base import AIProvider, AIProviderConfig
from app.services.tour_ai import helpers as tour_ai_helpers


class _FakeProvider(AIProvider):
    """Minimal AIProvider stand-in for tests."""

    def __init__(self, name: str, complete_json_result: dict[str, Any] | None = None,
                 complete_json_exc: Exception | None = None) -> None:
        super().__init__(AIProviderConfig(api_key="test", model=name))
        self._name = name
        self._result = complete_json_result
        self._exc = complete_json_exc

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_json_mode(self) -> bool:
        return True

    async def complete(self, messages, vision_input=None) -> str:
        raise NotImplementedError

    async def complete_json(self, messages, vision_input=None, json_schema=None):
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


@pytest.fixture(autouse=True)
def _fast_retry():
    """Pin the tenacity wrapper on _complete_json_with_retry to a single
    attempt with no wait so failure-path tests don't sleep."""
    fn = tour_ai_helpers._complete_json_with_retry
    original_stop = fn.retry.stop
    original_wait = fn.retry.wait
    fn.retry.stop = stop_after_attempt(1)
    fn.retry.wait = wait_none()
    try:
        yield
    finally:
        fn.retry.stop = original_stop
        fn.retry.wait = original_wait


def _fake_download_client(response_content: bytes, content_type: str = "image/jpeg") -> MagicMock:
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.content = response_content
    fake_response.headers = {"content-type": content_type}
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=fake_response)
    return fake_client


@pytest.mark.asyncio
async def test_download_image_as_base64_rejects_undecodable_bytes():
    fake_client = _fake_download_client(b"not an image")
    with patch("app.core.http.get_general_client", return_value=fake_client):
        with pytest.raises(ValueError, match="not a valid image"):
            await tour_ai_helpers._download_image_as_base64("https://example.com/scene.jpg")


@pytest.mark.asyncio
async def test_download_image_as_base64_accepts_real_image():
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="JPEG")
    real_bytes = buf.getvalue()

    fake_client = _fake_download_client(real_bytes)
    with patch("app.core.http.get_general_client", return_value=fake_client):
        image_base64, content_type = await tour_ai_helpers._download_image_as_base64(
            "https://example.com/scene.jpg"
        )

    assert content_type == "image/jpeg"
    assert base64.b64decode(image_base64) == real_bytes


async def test_complete_json_with_retry_returns_primary_result_when_it_succeeds():
    primary = _FakeProvider("Gemini", complete_json_result={"score": 9})
    out = await tour_ai_helpers._complete_json_with_retry(primary, messages=[])
    assert out == {"score": 9}


