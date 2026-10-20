from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
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
