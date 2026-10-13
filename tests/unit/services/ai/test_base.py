from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.ai.base import (
    AI_MAX_RETRIES,
    AI_RETRY_MAX_WAIT,
    AIProvider,
    AIProviderConfig,
    AIProviderError,
    _is_retryable_error,
    _parse_retry_after_seconds,
    _retry_wait,
)


class _DummyProvider(AIProvider):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def supports_vision(self) -> bool:
        return False

    @property
    def supports_json_mode(self) -> bool:
        return True

    async def complete(self, messages, vision_input=None) -> str:
        raise NotImplementedError

    async def complete_json(self, messages, vision_input=None, json_schema=None):
        raise NotImplementedError


def test_parse_json_response_recovers_nested_object_from_wrapped_text():
    provider = _DummyProvider(AIProviderConfig(api_key="test", model="dummy"))

    result = provider._parse_json_response(
        'prefix {"floor_plan_analysis": {"rooms": [{"name": "Kitchen"}]}, "vastu_score": 8} suffix'
    )

    assert result["floor_plan_analysis"]["rooms"][0]["name"] == "Kitchen"
    assert result["vastu_score"] == 8


class TestRetryAfterParsing:
    def test_retry_in_seconds_from_gemini_body(self):
        body = (
            'You exceeded your current quota... Please retry in 11.29336209s. '
            'Quota exceeded for metric: ... free_tier_requests'
        )
        assert _parse_retry_after_seconds({}, body) == pytest.approx(11.29336209)

    def test_retry_after_header(self):
        assert _parse_retry_after_seconds({"Retry-After": "30"}, "") == 30.0

    def test_glm_five_hour_window(self):
        body = (
            '{"error":{"code":"1308","message":'
            '"Usage limit reached for 5 hour. Your limit will reset at 2026-07-11 04:46:29"}}'
        )
        delay = _parse_retry_after_seconds({}, body)
        assert delay is not None
        assert delay >= 60

    def test_glm_prefers_hours_window_over_reset_timestamp(self):
        # The hours window has no timezone ambiguity; always prefer it over
        # the naive "reset at" timestamp when both are present.
        body = (
            "Usage limit reached for 5 hour. "
            "Your limit will reset at 2099-01-01 00:00:00"
        )
        delay = _parse_retry_after_seconds({}, body)
        assert delay == pytest.approx(5 * 3600.0)

    def test_glm_hours_window_wins_over_sooner_reset_timestamp(self):
        # A TZ-skewed "reset at" timestamp that lands sooner than the stated
        # window must not shorten the trusted, unambiguous window.
        reset_soon = (datetime.now() + timedelta(minutes=90)).strftime("%Y-%m-%d %H:%M:%S")
        body = f"Usage limit reached for 5 hour. Your limit will reset at {reset_soon}"
        delay = _parse_retry_after_seconds({}, body)
        assert delay == pytest.approx(5 * 3600.0)


class TestIsRetryableError:
    def test_non_retryable_flag_wins(self):
        exc = AIProviderError(message="bad", provider="agnes", status_code=429, retryable=False)
        assert _is_retryable_error(exc) is False

    def test_soft_429_is_retryable(self):
        exc = AIProviderError(
            message="Retryable HTTP 429",
            provider="agnes",
            status_code=429,
            retryable=True,
        )
        assert _is_retryable_error(exc) is True

    def test_503_is_retryable(self):
        exc = AIProviderError(
            message="Retryable HTTP 503",
            provider="agnes",
            status_code=503,
            retryable=True,
        )
        assert _is_retryable_error(exc) is True


def test_retry_policy_is_five_attempts_capped_at_30s():
    assert AI_MAX_RETRIES == 5
    assert AI_RETRY_MAX_WAIT == 30


def test_retry_wait_honours_retry_after_within_cap():
    state = MagicMock()
    state.outcome.exception.return_value = AIProviderError(
        message="429", provider="agnes", status_code=429, retry_after_seconds=600.0,
    )
    assert _retry_wait(state) == 30.0


def test_retry_wait_uses_retry_after_below_cap():
    state = MagicMock()
    state.outcome.exception.return_value = AIProviderError(
        message="429", provider="agnes", status_code=429, retry_after_seconds=10.0,
    )
    assert _retry_wait(state) == 10.0


def test_retry_after_http_date_is_parsed():
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    when = format_datetime(datetime.now(UTC) + timedelta(seconds=20), usegmt=True)
    delay = _parse_retry_after_seconds(httpx.Headers({"Retry-After": when}), "")
    assert delay is not None and 15 <= delay <= 20


@pytest.mark.asyncio
async def test_make_request_retries_429_until_success():
    provider = _DummyProvider(AIProviderConfig(api_key="test", model="dummy"))

    limited = MagicMock(spec=httpx.Response)
    limited.status_code = 429
    limited.text = "rate limited"
    limited.headers = httpx.Headers({})

    ok = MagicMock(spec=httpx.Response)
    ok.status_code = 200
    ok.text = "{}"
    ok.headers = httpx.Headers({})

    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=[limited, limited, ok])

    with patch("app.services.ai.base._BACKOFF", MagicMock(return_value=0.0)):
        result = await provider._make_request(client, "https://example.com", {}, {})

    assert result.status_code == 200
    assert client.post.await_count == 3


@pytest.mark.asyncio
async def test_make_request_retries_soft_503():
    provider = _DummyProvider(AIProviderConfig(api_key="test", model="dummy"))

    fail = MagicMock(spec=httpx.Response)
    fail.status_code = 503
    fail.text = "high demand"
    fail.headers = httpx.Headers({})

    ok = MagicMock(spec=httpx.Response)
    ok.status_code = 200
    ok.text = "{}"
    ok.headers = httpx.Headers({})

    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=[fail, ok])

    with patch("app.services.ai.base._BACKOFF", MagicMock(return_value=0.0)):
        result = await provider._make_request(client, "https://example.com", {}, {})
    assert result.status_code == 200
    assert client.post.await_count == 2
