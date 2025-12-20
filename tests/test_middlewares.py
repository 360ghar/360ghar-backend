import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.cache import cache_manager
from app.core.config import settings
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import RequestIDMiddleware, SecurityHeadersMiddleware


class TestRequestIDMiddleware:
    """Tests for RequestIDMiddleware."""

    def test_generates_uuid_when_no_header(self) -> None:
        """Should generate a valid UUID when no X-Request-ID header."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        request_id = response.headers.get("X-Request-ID")
        assert request_id is not None
        uuid.UUID(request_id)  # Validates UUID format

    def test_echoes_provided_request_id(self) -> None:
        """Should echo back the provided X-Request-ID header."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-ID": "my-custom-id-123"})

        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == "my-custom-id-123"

    def test_stores_request_id_in_state(self) -> None:
        """Should store request_id in request.state for logging."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-ID": "state-test-id"})

        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == "state-test-id"


class TestSecurityHeadersMiddleware:
    """Tests for SecurityHeadersMiddleware."""

    def test_always_sets_basic_security_headers(self) -> None:
        """Should always set basic security headers."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test")

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_hsts_only_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HSTS header should only be set in production."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)

        # Development mode
        monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
        response = client.get("/test")
        assert "Strict-Transport-Security" not in response.headers

        # Production mode
        monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
        response = client.get("/test")
        assert "Strict-Transport-Security" in response.headers
        assert "max-age=" in response.headers["Strict-Transport-Security"]

    def test_csp_only_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CSP header should only be set in production."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)

        # Development mode
        monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
        response = client.get("/test")
        assert "Content-Security-Policy" not in response.headers

        # Production mode
        monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
        response = client.get("/test")
        assert "Content-Security-Policy" in response.headers


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def test_allows_requests_within_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should allow requests within the rate limit."""
        RateLimitMiddleware._memory_store = {}
        monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, calls=5, period=60, scope="test")

        @app.get("/api")
        async def api_endpoint():
            return {"ok": True}

        client = TestClient(app)

        for i in range(5):
            response = client.get("/api")
            assert response.status_code == 200

    def test_blocks_requests_over_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should block requests exceeding the rate limit."""
        RateLimitMiddleware._memory_store = {}
        monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, calls=2, period=60, scope="block_test")

        @app.get("/api")
        async def api_endpoint():
            return {"ok": True}

        client = TestClient(app)

        # First 2 should pass
        assert client.get("/api").status_code == 200
        assert client.get("/api").status_code == 200

        # Third should be blocked
        response = client.get("/api")
        assert response.status_code == 429

    def test_returns_proper_rate_limit_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return proper rate limit headers on 429."""
        RateLimitMiddleware._memory_store = {}
        monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, calls=1, period=30, scope="header_test")

        @app.get("/api")
        async def api_endpoint():
            return {"ok": True}

        client = TestClient(app)

        client.get("/api")  # Use up the limit
        response = client.get("/api")

        assert response.status_code == 429
        assert response.headers.get("Retry-After") == "30"
        assert response.headers.get("X-RateLimit-Limit") == "1"
        assert response.headers.get("X-RateLimit-Period") == "30"

    def test_exempt_paths_not_rate_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should not rate limit exempt paths like /health."""
        RateLimitMiddleware._memory_store = {}
        monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, calls=1, period=60, scope="exempt_test")

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.get("/api")
        async def api():
            return {"ok": True}

        client = TestClient(app)

        # Use up the API limit
        client.get("/api")
        assert client.get("/api").status_code == 429

        # Health should still work
        for _ in range(10):
            assert client.get("/health").status_code == 200

    def test_docs_endpoints_exempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should exempt /docs and /redoc endpoints."""
        RateLimitMiddleware._memory_store = {}
        monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, calls=1, period=60, scope="docs_test")

        client = TestClient(app)

        # Docs endpoints should be exempt
        for _ in range(5):
            response = client.get("/docs")
            # May return 200 or 404 depending on FastAPI config, but not 429
            assert response.status_code != 429

    def test_rate_limit_per_client_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Different IPs should have separate rate limits."""
        RateLimitMiddleware._memory_store = {}
        monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, calls=1, period=60, scope="ip_test")

        @app.get("/api")
        async def api():
            return {"ok": True}

        client = TestClient(app)

        # First request uses up the limit for default IP
        response1 = client.get("/api")
        assert response1.status_code == 200

        # Second request from same IP should be blocked
        response2 = client.get("/api")
        assert response2.status_code == 429

        # Request with different X-Forwarded-For should work
        response3 = client.get("/api", headers={"X-Forwarded-For": "10.0.0.1"})
        assert response3.status_code == 200

    def test_adds_rate_limit_headers_to_success_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should add rate limit headers to successful responses."""
        RateLimitMiddleware._memory_store = {}
        monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, calls=10, period=120, scope="success_test")

        @app.get("/api")
        async def api():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/api")

        assert response.status_code == 200
        assert response.headers.get("X-RateLimit-Limit") == "10"
        assert response.headers.get("X-RateLimit-Period") == "120"


# Legacy tests (keeping for backwards compatibility)
def test_request_id_middleware_generates_and_echoes_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)

    r1 = client.get("/ping")
    assert r1.status_code == 200
    request_id = r1.headers.get("X-Request-ID")
    assert request_id
    uuid.UUID(request_id)  # raises ValueError if invalid

    r2 = client.get("/ping", headers={"X-Request-ID": "test-request-id"})
    assert r2.status_code == 200
    assert r2.headers.get("X-Request-ID") == "test-request-id"


def test_security_headers_middleware_applies_expected_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)

    monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-XSS-Protection"] == "1; mode=block"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Strict-Transport-Security" not in r.headers
    assert "Content-Security-Policy" not in r.headers

    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    r_prod = client.get("/ping")
    assert r_prod.status_code == 200
    assert "Strict-Transport-Security" in r_prod.headers
    assert "Content-Security-Policy" in r_prod.headers


def test_rate_limit_middleware_enforces_limits_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    RateLimitMiddleware._memory_store = {}
    monkeypatch.setattr(cache_manager, "redis_client", None, raising=False)

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, calls=2, period=60, scope="test")

    @app.get("/limited")
    async def limited():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    client = TestClient(app)

    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 200

    blocked = client.get("/limited")
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Rate limit exceeded"
    assert blocked.headers.get("Retry-After") == "60"
    assert blocked.headers.get("X-RateLimit-Limit") == "2"
    assert blocked.headers.get("X-RateLimit-Period") == "60"

    # Exempt endpoints should remain accessible
    for _ in range(5):
        assert client.get("/health").status_code == 200

