from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.services.ai.image_gen import service
from app.services.ai.image_gen.schemas import ImageGenMode, ImageGenRequest


def _response(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text or str(body or {})
    resp.json.return_value = body or {}
    resp.headers = httpx.Headers({})
    return resp


def _ok(b64: str = "aGVsbG8=") -> MagicMock:
    return _response(200, {"data": [{"b64_json": b64}]})


@pytest.fixture
def client():
    mock = MagicMock()
    mock.post = AsyncMock(return_value=_ok())
    mock.get = AsyncMock()
    with (
        patch.object(service.settings, "AGNES_AI_API_KEY", "test-key"),
        patch.object(service, "get_general_client", return_value=mock),
        patch.object(service, "_retry_wait", lambda _state: 0),
    ):
        yield mock


def _txt(prompt: str = "A bright modern living room") -> ImageGenRequest:
    return ImageGenRequest(mode=ImageGenMode.TEXT_TO_IMAGE, prompt=prompt)


@pytest.mark.asyncio
async def test_text_to_image_payload(client):
    result = await service.generate_image(_txt())

    assert result.success is True
    _, kwargs = client.post.await_args
    body = kwargs["json"]
    assert body["model"] == service.settings.AGNES_IMAGE_MODEL
    assert body["size"] == "1K"
    assert body["ratio"] == "1:1"
    assert body["extra_body"] == {"response_format": "b64_json"}
    assert "response_format" not in body
    assert "image" not in body["extra_body"]
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert client.post.await_args.args[0].endswith("/images/generations")


@pytest.mark.asyncio
async def test_image_to_image_sends_data_url_in_extra_body(client):
    request = ImageGenRequest(
        mode=ImageGenMode.IMAGE_TO_IMAGE,
        prompt="Repaint the walls sage green",
        image="QUJD",
        mime_type="image/png",
        ratio="16:9",
    )

    await service.generate_image(request)

    body = client.post.await_args.kwargs["json"]
    assert body["extra_body"] == {
        "response_format": "b64_json",
        "image": ["data:image/png;base64,QUJD"],
    }
    assert body["ratio"] == "16:9"
    assert "response_format" not in body


@pytest.mark.asyncio
async def test_b64_response_becomes_data_url(client):
    result = await service.generate_image(_txt())
    assert result.image == "data:image/png;base64,aGVsbG8="


@pytest.mark.asyncio
async def test_url_response_is_downloaded_as_data_url(client):
    client.post.return_value = _response(200, {"data": [{"url": "https://cdn.example/x.png"}]})
    download = MagicMock()
    download.headers = httpx.Headers({"content-type": "image/png; charset=binary"})
    download.content = b"\x89PNG"
    download.raise_for_status = MagicMock()
    client.get.return_value = download

    result = await service.generate_image(_txt())

    assert result.image == "data:image/png;base64,iVBORw=="


@pytest.mark.asyncio
async def test_persistent_429_maps_to_quota_exceeded_after_five_attempts(client):
    client.post.return_value = _response(429, text="rate limited")

    result = await service.generate_image(_txt())

    assert result.success is False
    assert result.code == "QUOTA_EXCEEDED"
    assert client.post.await_count == 5


@pytest.mark.asyncio
async def test_retries_503_then_succeeds(client):
    client.post.side_effect = [_response(503, text="busy"), _response(503, text="busy"), _ok()]

    result = await service.generate_image(_txt())

    assert result.success is True
    assert client.post.await_count == 3


@pytest.mark.asyncio
async def test_400_safety_maps_to_content_blocked(client):
    client.post.return_value = _response(400, text="Request blocked by safety filter")

    result = await service.generate_image(_txt())

    assert result.code == "CONTENT_BLOCKED"
    assert client.post.await_count == 1


@pytest.mark.asyncio
async def test_missing_key_returns_service_unavailable(client):
    with patch.object(service.settings, "AGNES_AI_API_KEY", None):
        result = await service.generate_image(_txt())

    assert result.code == "SERVICE_UNAVAILABLE"
    client.post.assert_not_awaited()


def test_invalid_ratio_is_rejected():
    with pytest.raises(ValidationError):
        ImageGenRequest(mode=ImageGenMode.TEXT_TO_IMAGE, prompt="abc", ratio="5:4")


@pytest.mark.asyncio
async def test_non_object_data_item_returns_no_image():
    assert await service._extract_image({"data": ["not-an-object"]}) is None
