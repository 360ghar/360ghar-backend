from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from tenacity import stop_after_attempt, wait_none

from app.services.ai import AIProviderError, AIProviderType
from app.services.ai.base import AIProvider, AIProviderConfig
from app.services.tour_ai import helpers as tour_ai_helpers


class _FakeProvider(AIProvider):
    """Minimal AIProvider stand-in for fallback tests."""

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


def test_resolve_fallback_provider_picks_glm_for_gemini_primary():
    primary = _FakeProvider("Gemini")
    glm_fallback = _FakeProvider("GLM")
    with patch("app.services.tour_ai.helpers.get_ai_provider", return_value=glm_fallback) as m:
        out = tour_ai_helpers._resolve_fallback_provider(primary)
    assert out is glm_fallback
    m.assert_called_once_with(AIProviderType.GLM)


def test_resolve_fallback_provider_picks_gemini_for_glm_primary():
    primary = _FakeProvider("GLM-4.7")
    gemini_fallback = _FakeProvider("Gemini")
    with patch("app.services.tour_ai.helpers.get_ai_provider", return_value=gemini_fallback) as m:
        out = tour_ai_helpers._resolve_fallback_provider(primary)
    assert out is gemini_fallback
    m.assert_called_once_with(AIProviderType.GEMINI)


def test_resolve_fallback_provider_returns_none_when_fallback_unconfigured():
    primary = _FakeProvider("Gemini")
    with patch("app.services.tour_ai.helpers.get_ai_provider", side_effect=ValueError("no key")):
        out = tour_ai_helpers._resolve_fallback_provider(primary)
    assert out is None


async def test_complete_json_with_retry_returns_primary_result_when_it_succeeds():
    primary = _FakeProvider("Gemini", complete_json_result={"score": 9})
    out = await tour_ai_helpers._complete_json_with_retry(primary, messages=[])
    assert out == {"score": 9}


async def test_complete_json_with_retry_falls_back_when_primary_raises():
    primary = _FakeProvider(
        "Gemini",
        complete_json_exc=AIProviderError("boom", provider="Gemini"),
    )
    fallback = _FakeProvider("GLM", complete_json_result={"score": 7})
    with patch("app.services.tour_ai.helpers.get_ai_provider", return_value=fallback):
        out = await tour_ai_helpers._complete_json_with_retry(primary, messages=[])
    assert out == {"score": 7}


async def test_complete_json_with_retry_reraises_when_no_fallback_available():
    primary = _FakeProvider(
        "Gemini",
        complete_json_exc=AIProviderError("boom", provider="Gemini"),
    )
    with patch("app.services.tour_ai.helpers.get_ai_provider", side_effect=ValueError("no key")):
        with pytest.raises(AIProviderError):
            await tour_ai_helpers._complete_json_with_retry(primary, messages=[])


async def test_complete_json_with_retry_propagates_fallback_error_when_fallback_also_fails():
    primary = _FakeProvider(
        "Gemini",
        complete_json_exc=AIProviderError("primary boom", provider="Gemini"),
    )
    fallback = _FakeProvider(
        "GLM",
        complete_json_exc=AIProviderError("fallback boom", provider="GLM"),
    )
    with patch("app.services.tour_ai.helpers.get_ai_provider", return_value=fallback):
        with pytest.raises(AIProviderError, match="fallback boom"):
            await tour_ai_helpers._complete_json_with_retry(primary, messages=[])
