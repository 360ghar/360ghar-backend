from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.base import AIMessage, AIProviderConfig, AIRole, VisionInput
from app.services.ai.providers.agnes import AgnesProvider


def _provider() -> AgnesProvider:
    return AgnesProvider(AIProviderConfig(api_key="test-key", model="agnes-3.0-flash"))


def test_endpoint_uses_configured_base_url():
    with patch("app.services.ai.providers.agnes.settings") as cfg:
        cfg.AGNES_API_BASE = "https://apihub.agnes-ai.com/v1"
        assert _provider()._get_api_url() == "https://apihub.agnes-ai.com/v1/chat/completions"


def test_provider_reports_name_and_vision_support():
    provider = _provider()
    assert provider.name == "Agnes AI"
    assert provider.supports_vision is True


@pytest.mark.asyncio
async def test_vision_input_is_sent_as_openai_image_url():
    provider = _provider()
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    provider._make_request = AsyncMock(return_value=response)  # type: ignore[method-assign]

    result = await provider.complete(
        [AIMessage(role=AIRole.USER, content="describe")],
        VisionInput(image_base64="QUJD", mime_type="image/png"),
    )

    assert result == "ok"
    _, url, _, payload = provider._make_request.await_args.args
    assert url.endswith("/chat/completions")
    content = payload["messages"][0]["content"]
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
