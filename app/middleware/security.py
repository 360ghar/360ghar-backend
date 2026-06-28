from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime

from fastapi import Request, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.core.cache import get_cache_manager
from app.core.logging import RequestIDFilter as RequestIDFilter
from app.core.logging import get_logger, reset_request_id, set_request_id
from app.core.utils import make_tz_aware, utc_now

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    """
    Pure ASGI middleware for logging all incoming requests, including MCP paths.
    """

    def __init__(self, app: ASGIApp, prefix: str = ""):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            query = scope.get("query_string", b"").decode("utf-8", errors="ignore")

            full_path = f"{self.prefix}{path}" if self.prefix else path
            logger.debug(
                "Incoming request",
                extra={
                    "method": method,
                    "path": full_path,
                    "query": query[:100] if query else None,
                }
            )

        await self.app(scope, receive, send)


class RequestIDMiddleware:
    """Add unique request ID to each request for tracing.

    Implemented as pure ASGI middleware to avoid BaseHTTPMiddleware
    deprecation in Starlette 1.0+ and to support streaming responses.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Skip request ID only for MCP streaming tool routes.
        # OAuth endpoints (/mcp/oauth/*) still need request IDs.
        if path.startswith("/mcp") and not (
            path.startswith("/mcp/oauth")
            or path.startswith("/mcp-admin/oauth")
        ):
            await self.app(scope, receive, send)
            return

        # Generate or use existing request ID
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode("utf-8", errors="ignore")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Propagate request_id to logging context via contextvar
        request_id_token = set_request_id(request_id)

        # Store request ID in scope state
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        # Inject request ID into response headers
        original_send = send

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"X-Request-ID", request_id.encode()))
                message["headers"] = headers
            await original_send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            reset_request_id(request_id_token)


class SecurityHeadersMiddleware:
    """Add security headers to all responses.

    Implemented as pure ASGI middleware to avoid BaseHTTPMiddleware
    deprecation in Starlette 1.0+ and to support streaming responses.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Skip security headers only for MCP streaming tool routes.
        # OAuth endpoints (/mcp/oauth/*) and well-known paths still need headers.
        if path.startswith("/mcp") and not (
            path.startswith("/mcp/oauth")
            or path.startswith("/mcp-admin/oauth")
        ):
            await self.app(scope, receive, send)
            return

        # Inject security headers into the response
        original_send = send

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"X-Content-Type-Options", b"nosniff"))
                headers.append((b"X-Frame-Options", b"DENY"))
                headers.append((b"X-XSS-Protection", b"0"))
                headers.append((b"Referrer-Policy", b"strict-origin-when-cross-origin"))

                if settings.ENVIRONMENT == "production":
                    headers.append((b"Strict-Transport-Security", b"max-age=31536000; includeSubDomains"))
                    headers.append((b"Content-Security-Policy",
                        b"default-src 'self'; "
                        b"script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                        b"style-src 'self' 'unsafe-inline'; "
                        b"img-src 'self' data: https: https://res.cloudinary.com; "
                        b"font-src 'self' data:; "
                        b"connect-src 'self' https://api.supabase.co https://res.cloudinary.com"))

                message["headers"] = headers
            await original_send(message)

        await self.app(scope, receive, send_with_security_headers)


class APIKeyMiddleware:
    """API key validation for external API access.

    Implemented as pure ASGI middleware to avoid BaseHTTPMiddleware
    deprecation in Starlette 1.0+ and to support streaming responses.
    """

    def __init__(self, app: ASGIApp, required_paths: list[str] | None = None):
        self.app = app
        self.required_paths = required_paths or []

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Check if path requires API key
        if any(path.startswith(rp) for rp in self.required_paths):
            headers = dict(scope.get("headers", []))
            api_key = headers.get(b"x-api-key", b"").decode("utf-8", errors="ignore")

            if not api_key:
                response = JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "API key required"},
                )
                await response(scope, receive, send)
                return

            if not await self.validate_api_key(api_key):
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Invalid API key"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    async def validate_api_key(self, api_key: str) -> bool:
        """Validate API key against stored keys"""
        cache = get_cache_manager()

        # Check cache first
        cache_key = f"api_key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return bool(cached)

        # In production, check against database
        # For now, check against environment variable
        valid = any(hmac.compare_digest(api_key, k.strip()) for k in settings.VALID_API_KEYS.split(",") if k.strip())

        # Cache result
        await cache.set(cache_key, valid, ttl=300)

        return valid

class RequestSignatureValidator:
    """Validate request signatures for webhook security"""

    @staticmethod
    def generate_signature(
        secret: str,
        method: str,
        path: str,
        body: bytes,
        timestamp: str
    ) -> str:
        """Generate HMAC signature for request"""
        message = f"{method}:{path}:{body.decode('utf-8', errors='replace')}:{timestamp}"
        signature = hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature

    @staticmethod
    async def validate_request(
        request: Request,
        secret: str,
        max_age_seconds: int = 300
    ) -> bool:
        """Validate request signature and timestamp"""
        # Get signature and timestamp from headers
        signature = request.headers.get("X-Signature")
        timestamp = request.headers.get("X-Timestamp")

        if not signature or not timestamp:
            return False

        # Check timestamp age
        try:
            # Normalize ISO 8601 'Z' suffix for Python < 3.11 compatibility
            normalized_ts = timestamp.replace("Z", "+00:00")
            request_time = make_tz_aware(datetime.fromisoformat(normalized_ts))
            if request_time is None:
                return False
            if (utc_now() - request_time).total_seconds() > max_age_seconds:
                logger.warning("Request timestamp too old")
                return False
        except ValueError:
            return False

        # Get request body
        body = await request.body()

        # Generate expected signature
        expected_signature = RequestSignatureValidator.generate_signature(
            secret,
            request.method,
            request.url.path,
            body,
            timestamp
        )

        # Compare signatures
        return hmac.compare_digest(signature, expected_signature)

class IPWhitelistMiddleware:
    """IP whitelist middleware for admin endpoints.

    Implemented as pure ASGI middleware to avoid BaseHTTPMiddleware
    deprecation in Starlette 1.0+ and to support streaming responses.
    """

    def __init__(self, app: ASGIApp, whitelist: list[str] | None = None, paths: list[str] | None = None):
        self.app = app
        self.whitelist = whitelist or []
        self.paths = paths or ["/admin"]

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Check if path requires IP whitelisting
        if any(path.startswith(p) for p in self.paths):
            client_ip = self._get_client_ip(scope)

            if client_ip not in self.whitelist:
                logger.warning("Unauthorized IP access attempt: %s", client_ip)
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Access denied"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    def _get_client_ip(self, scope: Scope) -> str:
        """Get real client IP address from ASGI scope."""
        headers = dict(scope.get("headers", []))
        forwarded = headers.get(b"x-forwarded-for", b"").decode("utf-8", errors="ignore")
        if forwarded:
            return str(forwarded.split(",")[0].strip())

        real_ip = headers.get(b"x-real-ip", b"").decode("utf-8", errors="ignore")
        if real_ip:
            return str(real_ip)

        client = scope.get("client")
        return client[0] if client else "unknown"
