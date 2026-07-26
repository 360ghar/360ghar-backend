"""HTTP middleware registration for the FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.cache_control import CacheControlMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import (
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.middleware.trailing_slash import StripTrailingSlashMiddleware

ALLOWED_CORS_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
ALLOWED_CORS_HEADERS = [
    "Accept",
    "Accept-Language",
    "Content-Language",
    "Content-Type",
    "Authorization",
    "X-Requested-With",
    "X-CSRF-Token",
    "X-API-Key",
    "Cache-Control",
    "Pragma",
    "Expires",
    "X-Process-Time",
    "X-Performance-Tier",
    # Streamable-HTTP MCP transport headers — required for browser-hosted MCP
    # clients to reach /mcp and /mcp-admin.
    "Mcp-Session-Id",
    "MCP-Protocol-Version",
    "Last-Event-ID",
]
EXPOSED_CORS_HEADERS = [
    "Content-Length",
    "Content-Range",
    "X-Process-Time",
    "X-Performance-Tier",
    "Mcp-Session-Id",
]
CORS_MAX_AGE_SECONDS = 86400


def register_middleware(app: FastAPI, *, testing: bool) -> None:
    """Register middleware in the same order as the original factory.

    Middleware executes in reverse registration order (bottom-up), so:
    - CORS is outermost (first inbound, last outbound)
    - Rate limiting sits just inside CORS
    - Security headers, request ID, logging are innermost
    """
    if settings.ENVIRONMENT == "development" or testing:
        cors_origins = ["*"]
        cors_credentials = False
    else:
        cors_origins = settings.CORS_ORIGINS
        cors_credentials = True

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_credentials,
        allow_methods=ALLOWED_CORS_METHODS,
        allow_headers=ALLOWED_CORS_HEADERS,
        expose_headers=EXPOSED_CORS_HEADERS,
        max_age=CORS_MAX_AGE_SECONDS,
    )

    # Rate limiting: 500 requests per minute per IP for general endpoints.
    # For stricter auth-endpoint limiting, use EndpointRateLimiter decorator
    # on individual routes (60 req/min).
    app.add_middleware(
        RateLimitMiddleware,
        calls=500,
        period=60,
        scope="global",
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CacheControlMiddleware)
    app.add_middleware(StripTrailingSlashMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware, prefix="")
