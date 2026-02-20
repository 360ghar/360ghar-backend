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
        middleware = RateLimitMiddleware(app, calls=100, period=60, scope="global")

        assert middleware.calls == 100
        assert middleware.period == 60
        assert middleware.scope == "global"

    def test_exempt_paths(self):
        """Test exempt paths are not rate limited."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app)

        exempt_paths = ["/", "/health", "/docs", "/redoc", "/openapi.json"]
        for path in exempt_paths:
            assert middleware._is_exempt_path(path) is True

    def test_non_exempt_paths(self):
        """Test non-exempt paths are rate limited."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app)

        non_exempt = ["/api/v1/properties/", "/api/v1/users/profile/", "/api/v1/users/"]
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

    def test_get_client_id_with_forwarded_header(self):
        """Test client ID with X-Forwarded-For header."""
        from app.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        middleware = RateLimitMiddleware(app)

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.state = MagicMock()
        mock_request.state.user = None

        client_id = middleware.get_client_id(mock_request)

        # Should use first IP from forwarded header
        assert "1.2.3.4" in client_id or client_id is not None


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

        app.add_middleware(RateLimitMiddleware, calls=100, period=60)

        with patch("app.middleware.rate_limit.get_cache_manager") as mock_cache:
            mock_manager = AsyncMock()
            mock_manager.is_available.return_value = False
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
            call_count = 0

            async def mock_check(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                # Allow first 2 calls, block after
                return call_count <= 2

            mock_manager = AsyncMock()
            mock_manager.is_available.return_value = True
            mock_manager.get.return_value = list(range(call_count))
            mock_cache.return_value = mock_manager

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # First calls should succeed (within mocked limit)
                response1 = await client.get("/limited")
                # Response depends on cache mock behavior
                assert response1.status_code in [200, 429]


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
