"""
Tests for app.services.media.url_verifier and the
ValidationUtils.verify_image_urls_async wrapper.

These tests lock in the regression that caused the 2026-06-17
hc_properties phantom-image incident: a well-formed Cloudinary URL that
returns HTTP 404 must be detected and dropped, while a reachable URL is
kept and third-party soft-failures do not block inserts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.media.url_verifier import (
    _is_first_party,
    verify_image_url,
    verify_image_urls,
)
from app.utils.validators import ValidationUtils

# URLs used as fixtures (never actually fetched; responses are mocked).
PHANTOM_URL = (
    "https://res.cloudinary.com/ddbhzlzy1/image/upload/360ghar/"
    "hc_properties/00171-ompee-drona-floors-palam-vihar-3bhk-builder-floor/"
    "listing_images/master_bedroom.webp"
)
WORKING_URL = (
    "https://res.cloudinary.com/ddbhzlzy1/image/upload/v1781553648/"
    "360ghar/properties/1531/entrance.webp"
)
THIRD_PARTY_URL = "https://www.nobroker.in/blog/wp-content/uploads/2023/11/Victory-Valley.jpg"


def _mock_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=httpx.Request("GET", WORKING_URL))


class TestIsFirstParty:
    def test_cloudinary_is_first_party(self):
        assert _is_first_party(WORKING_URL) is True
        assert _is_first_party(PHANTOM_URL) is True

    def test_third_party_is_not_first_party(self):
        assert _is_first_party(THIRD_PARTY_URL) is False

    def test_cloudinary_subdomain_is_first_party(self):
        assert _is_first_party("https://images.res.cloudinary.com/foo.jpg") is True


class TestVerifyImageUrl:
    @pytest.mark.asyncio
    async def test_2xx_passes(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(200))
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(WORKING_URL) is True

    @pytest.mark.asyncio
    async def test_3xx_passes(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(302))
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(WORKING_URL) is True

    @pytest.mark.asyncio
    async def test_404_fails_first_party(self):
        """Regression anchor: the phantom hc_properties URL must fail."""
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(404))
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(PHANTOM_URL) is False

    @pytest.mark.asyncio
    async def test_500_fails_first_party(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(503))
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(WORKING_URL) is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false_for_first_party(self):
        client = MagicMock()
        # First-party retries once, so both attempts must time out to fail.
        client.get = AsyncMock(
            side_effect=[
                httpx.TimeoutException("timed out"),
                httpx.TimeoutException("timed out"),
            ]
        )
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(WORKING_URL) is False

    @pytest.mark.asyncio
    async def test_first_party_retries_once_on_network_error(self):
        """A transient first-party error must NOT fail if the retry succeeds."""
        client = MagicMock()
        ok_resp = _mock_response(206)
        client.get = AsyncMock(
            side_effect=[httpx.ConnectError("transient"), ok_resp]
        )
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(WORKING_URL) is True

    @pytest.mark.asyncio
    async def test_network_error_third_party_soft_keeps(self):
        """Third-party soft-failure: keep URL despite network error."""
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(THIRD_PARTY_URL) is True

    @pytest.mark.asyncio
    async def test_404_third_party_soft_keeps(self):
        """Third-party 404 is soft: keep URL (don't break inserts on flaky CDNs)."""
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(404))
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            assert await verify_image_url(THIRD_PARTY_URL) is True

    @pytest.mark.asyncio
    async def test_non_http_returns_false(self):
        assert await verify_image_url("ftp://example.com/x.jpg") is False
        assert await verify_image_url("") is False
        assert await verify_image_url(None) is False  # type: ignore[arg-type]


class TestVerifyImageUrls:
    @pytest.mark.asyncio
    async def test_batch_drops_phantom_keeps_working(self):
        """Batch regression: one phantom + one working -> keep working only."""
        responses = {
            PHANTOM_URL: _mock_response(404),
            WORKING_URL: _mock_response(200),
        }

        async def _fake_get(url, **_kw):
            return responses[url]

        client = MagicMock()
        client.get = _fake_get
        with patch("app.services.media.url_verifier.get_general_client", return_value=client):
            kept, dropped = await verify_image_urls([PHANTOM_URL, WORKING_URL])
        assert kept == [WORKING_URL]
        assert dropped == [PHANTOM_URL]

    @pytest.mark.asyncio
    async def test_empty_input(self):
        kept, dropped = await verify_image_urls([])
        assert kept == [] and dropped == []


class TestValidationUtilsVerifyImageUrlsAsync:
    """The thin wrapper in validators.py delegates correctly."""

    @pytest.mark.asyncio
    async def test_wrapper_returns_kept_dropped(self):
        with patch(
            "app.services.media.url_verifier.verify_image_urls",
            new=AsyncMock(return_value=([WORKING_URL], [PHANTOM_URL])),
        ):
            kept, dropped = await ValidationUtils.verify_image_urls_async(
                [WORKING_URL, PHANTOM_URL]
            )
        assert kept == [WORKING_URL]
        assert dropped == [PHANTOM_URL]

    @pytest.mark.asyncio
    async def test_wrapper_empty(self):
        kept, dropped = await ValidationUtils.verify_image_urls_async([])
        assert kept == [] and dropped == []
