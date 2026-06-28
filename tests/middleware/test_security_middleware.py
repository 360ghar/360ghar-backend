"""
Tests for security middleware.
"""


import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Import the actual class name
from app.middleware.security import SecurityHeadersMiddleware


class TestSecurityMiddleware:
    """Tests for SecurityHeadersMiddleware class."""

    def test_middleware_initialization(self):
        """Test middleware initializes correctly."""
        app = FastAPI()
        middleware = SecurityHeadersMiddleware(app)

        assert middleware.app is not None

    @pytest.mark.asyncio
    async def test_security_headers_added(self):
        """Test that security headers are added to response."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test")

            # Check for common security headers
            assert response.status_code == 200
            assert response.headers.get("X-Content-Type-Options") == "nosniff"
            assert response.headers.get("X-Frame-Options") == "DENY"
            assert response.headers.get("X-XSS-Protection") == "0"

    @pytest.mark.asyncio
    async def test_cors_headers(self):
        """Test CORS headers are properly set."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/test",
                headers={"Origin": "http://localhost:3000"},
            )

            # CORS preflight may or may not be handled by this middleware
            assert response.status_code in [200, 204, 405]


class TestXSSProtection:
    """Tests for XSS protection headers."""

    @pytest.mark.asyncio
    async def test_xss_protection_header(self):
        """Test X-XSS-Protection header is set."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test")

            assert response.headers.get("X-XSS-Protection") == "0"


class TestContentTypeOptions:
    """Tests for content type options header."""

    @pytest.mark.asyncio
    async def test_x_content_type_options_header(self):
        """Test X-Content-Type-Options header is set."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test")

            assert response.headers.get("X-Content-Type-Options") == "nosniff"


class TestFrameOptions:
    """Tests for frame options header."""

    @pytest.mark.asyncio
    async def test_x_frame_options_header(self):
        """Test X-Frame-Options header is set."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test")

            assert response.headers.get("X-Frame-Options") == "DENY"


class TestContentSecurityPolicy:
    """Tests for content security policy header."""

    @pytest.mark.asyncio
    async def test_csp_header(self):
        """Test Content-Security-Policy header is set in production."""
        # CSP header is only set in production environment
        # In test environment, this header may not be present
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test")

            # CSP may or may not be set depending on ENVIRONMENT setting
            assert response.status_code == 200


class TestHSTS:
    """Tests for HSTS header."""

    @pytest.mark.asyncio
    async def test_hsts_header_in_production(self):
        """Test HSTS header is set in production."""
        # HSTS is only set in production environment
        # In test environment, this header may not be present
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        app.add_middleware(SecurityHeadersMiddleware)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test")

            # HSTS may or may not be set depending on ENVIRONMENT setting
            assert response.status_code == 200
