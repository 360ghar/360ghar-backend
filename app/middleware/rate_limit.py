from __future__ import annotations

import math
import time
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.cache import get_cache_manager
from app.core.logging import get_logger

logger = get_logger(__name__)

class RateLimitMiddleware:
    """Rate limiting middleware using fixed-window counter approach.

    Uses two windows (current and previous) to approximate
    a sliding window in O(1) time and space, instead of the
    previous O(n) list-based sliding window.

    Implemented as pure ASGI middleware to avoid BaseHTTPMiddleware
    deprecation in Starlette 1.0+ and to support streaming responses.
    """

    def __init__(
        self,
        app: ASGIApp,
        calls: int = 100,
        period: int = 60,
        scope: str = "global"
    ):
        self.app = app
        self.calls = calls
        self.period = period
        self.scope = scope

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Skip rate limiting for exempt paths
        if self._is_exempt_path(path):
            await self.app(scope, receive, send)
            return

        # Get client identifier from scope
        client_id = self._get_client_id_from_scope(scope)

        # Check rate limit
        if not await self.check_rate_limit(client_id, path):
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(self.period),
                    "X-RateLimit-Limit": str(self.calls),
                    "X-RateLimit-Period": str(self.period),
                },
            )
            await response(scope, receive, send)
            return

        # Inject rate-limit headers into the response
        original_send = send
        headers_added = False

        async def send_with_headers(message):
            nonlocal headers_added
            if message["type"] == "http.response.start" and not headers_added:
                headers_added = True
                headers = list(message.get("headers", []))
                headers.append((b"X-RateLimit-Limit", str(self.calls).encode()))
                headers.append((b"X-RateLimit-Period", str(self.period).encode()))
                message["headers"] = headers
            await original_send(message)

        await self.app(scope, receive, send_with_headers)

    def _is_exempt_path(self, path: str) -> bool:
        """Return True for endpoints that should not be rate limited."""
        exempt_paths = {
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/openapi.yaml",
        }
        if path in exempt_paths:
            return True

        # FastAPI docs are served under settings.API_V1_STR (e.g. /api/v1/docs)
        if path.endswith("/docs") or path.endswith("/redoc"):
            return True
        if path.endswith("/openapi.json") or path.endswith("/openapi.yaml"):
            return True

        # MCP endpoints use streaming, exempt from rate limiting
        if path.startswith("/mcp"):
            return True

        # SSE endpoints are long-lived streaming connections: a single held-open
        # connection would otherwise consume a client's per-IP request budget on
        # connect. List them explicitly so new routes can't be silently exempted
        # by an accidental ``/sse`` suffix match.
        sse_paths = {
            "/api/v1/flatmates/sse",
            "/api/v1/notifications/sse",
        }
        if path in sse_paths:
            return True

        return False

    def _get_client_id_from_scope(self, scope: Scope) -> str:
        """Get unique client identifier from ASGI scope."""
        # Try to get authenticated user ID from scope state
        state = scope.get("state", {})
        if "user_id" in state:
            return f"user:{state['user_id']}"

        # Extract headers from scope
        headers = dict(scope.get("headers", []))
        forwarded = headers.get(b"x-forwarded-for", b"").decode("utf-8", errors="ignore")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            client = scope.get("client")
            ip = client[0] if client else "unknown"

        return f"ip:{ip}"

    def get_client_id(self, request: Request) -> str:
        """Get unique client identifier from Request (for EndpointRateLimiter)."""
        if hasattr(request.state, "user_id"):
            return f"user:{request.state.user_id}"

        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0]
        else:
            ip = request.client.host if request.client else "unknown"

        return f"ip:{ip}"

    async def check_rate_limit(self, client_id: str, path: str) -> bool:
        """Check rate limit using fixed-window counter approach.

        Uses two windows (current and previous) to approximate
        a sliding window in O(1) time and space.
        """
        cache = get_cache_manager()

        now = int(time.time())
        current_window = now // self.period
        previous_window = current_window - 1

        current_key = f"rate_limit:{self.scope}:{client_id}:{current_window}"
        previous_key = f"rate_limit:{self.scope}:{client_id}:{previous_window}"

        # Get counts from both windows
        current_count = await cache.get(current_key) or 0
        previous_count = await cache.get(previous_key) or 0

        # Calculate weighted count (previous window contribution decays over time).
        # Use math.ceil so the previous window is never under-counted due to
        # integer truncation — without this, a single request in the previous
        # window is silently dropped when weight < 1.0, allowing the limit to
        # be exceeded by 1.
        elapsed_in_window = now % self.period
        weight = 1.0 - (elapsed_in_window / self.period)
        estimated_count = math.ceil(previous_count * weight) + current_count

        if estimated_count >= self.calls:
            logger.warning("Rate limit exceeded for %s on %s", client_id, path)
            return False

        # Increment current window
        await cache.set(current_key, current_count + 1, ttl=self.period * 2)

        return True

class EndpointRateLimiter:
    """Decorator for endpoint-specific rate limiting"""

    def __init__(self, calls: int = 10, period: int = 60):
        self.calls = calls
        self.period = period

    def __call__(self, func: Callable) -> Callable:
        async def wrapper(request: Request, *args, **kwargs):
            client_id = self.get_client_id(request)
            endpoint = f"{request.method}:{request.url.path}"

            if not await self.check_rate_limit(client_id, endpoint):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Max {self.calls} calls per {self.period} seconds",
                    headers={"Retry-After": str(self.period)}
                )

            return await func(request, *args, **kwargs)

        return wrapper

    def get_client_id(self, request: Request) -> str:
        """Get client identifier from request"""
        if hasattr(request.state, "user_id") and request.state.user_id:
            return f"user:{request.state.user_id}"

        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0]
        else:
            ip = request.client.host if request.client else "unknown"

        return f"ip:{ip}"

    async def check_rate_limit(self, client_id: str, endpoint: str) -> bool:
        """Check rate limit for specific endpoint"""
        cache = get_cache_manager()
        key = f"endpoint_limit:{endpoint}:{client_id}"

        count = await cache.get(key) or 0

        if count >= self.calls:
            return False

        await cache.set(key, count + 1, ttl=self.period)
        return True
