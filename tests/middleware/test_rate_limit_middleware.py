"""
Tests for rate limit middleware.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware class."""

    def test_middleware_initialization(self):
        """Test middleware initializes with correct defaults."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app, calls=500, period=60, scope="global")

        assert middleware.calls == 500
        assert middleware.period == 60
        assert middleware.scope == "global"

    def test_exempt_paths(self):
        """Test exempt paths are not rate limited."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app)

        exempt_paths = [
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/agent/chat",
            "/api/v1/agent/chat-public",
        ]
        for path in exempt_paths:
            assert middleware._is_exempt_path(path) is True

    def test_non_exempt_paths(self):
        """Test non-exempt paths are rate limited."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app)

        # The notifications SSE route does not exist, so its name is not exempt.
        non_exempt = [
            "/api/v1/properties/",
            "/api/v1/users/profile/",
            "/api/v1/users/",
            "/api/v1/notifications/sse",
        ]
        for path in non_exempt:
            assert middleware._is_exempt_path(path) is False

    def test_get_client_id_from_request(self):
        """Test client ID extraction from request."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app)

        # Create mock request
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.state = MagicMock()
        mock_request.state.user = None

        client_id = middleware.get_client_id(mock_request)

        assert client_id is not None
        assert len(client_id) > 0

    def test_get_client_id_with_forwarded_header(self, monkeypatch):
        """The client is the entry the trusted proxy appended. The first entry is client-supplied."""
        from app.config import settings
        from app.middleware.rate_limit import RateLimitMiddleware

        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        middleware = RateLimitMiddleware(FastAPI())

        request = Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")],
                "client": ("127.0.0.1", 1234),
            }
        )

        assert middleware.get_client_id(request) == "ip:5.6.7.8"


class TestRateLimitIntegration:
    """Integration tests for rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(self):
        """Test rate limit headers are included in response."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(RateLimitMiddleware, calls=500, period=60)

        with patch("app.middleware.rate_limit.get_cache_manager") as mock_cache:
            mock_manager = AsyncMock()
            mock_manager.is_available.return_value = False
            # Counter-based rate limiter expects integer counts from cache.get
            mock_manager.get.return_value = 0
            mock_cache.return_value = mock_manager

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/test")

                assert "X-RateLimit-Limit" in response.headers
                assert "X-RateLimit-Period" in response.headers

    @pytest.mark.asyncio
    async def test_exempt_endpoint_no_rate_limit(self):
        """Test exempt endpoints bypass rate limiting."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        app.add_middleware(RateLimitMiddleware, calls=1, period=60)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Should not be rate limited even with calls=1
            response1 = await client.get("/health")
            response2 = await client.get("/health")
            response3 = await client.get("/health")

            assert response1.status_code == 200
            assert response2.status_code == 200
            assert response3.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        """Test rate limit returns 429 when exceeded."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()

        @app.get("/limited")
        async def limited_endpoint():
            return {"message": "ok"}

        app.add_middleware(RateLimitMiddleware, calls=2, period=60)

        with patch("app.middleware.rate_limit.get_cache_manager") as mock_cache:
            mock_manager = AsyncMock()
            mock_manager.is_available.return_value = True
            # Simulate that cache already has 2 requests in the current window
            mock_manager.get.return_value = 2
            mock_cache.return_value = mock_manager

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/limited")
                # Should be rate limited since current_count (2) >= calls (2)
                assert response.status_code == 429


class TestRateLimitScopes:
    """Tests for rate limit scopes."""

    def test_global_scope(self):
        """Test global scope applies to all endpoints."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app, scope="global")

        assert middleware.scope == "global"

    def test_endpoint_scope(self):
        """Test endpoint scope can be configured."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app, scope="endpoint")

        assert middleware.scope == "endpoint"
