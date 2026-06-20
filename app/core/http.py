"""Shared httpx.AsyncClient singletons for connection reuse.

Creating a new ``httpx.AsyncClient`` per request allocates a fresh SSL
context, DNS resolver, and connection pool — then tears it all down after
one call.  Using shared clients avoids that overhead and enables TCP
connection keep-alive across requests.

Four domain-specific clients are provided:

| Client                | Default timeout | Max connections | Keepalive | Used by                            |
|-----------------------|-----------------|-----------------|-----------|------------------------------------|
| scraper               | 30 s            | 10              | 3         | data-hub scrapers, jamabandi       |
| blog                  | 120 s           | 5               | 2         | Perplexity, SerpAPI                |
| general               | 30 s            | 5               | 2         | misc HTTP, image downloads         |
| supabase_auth_http    | 10 s            | 10              | 5         | verify_token, admin user ops       |

Per-request ``timeout=`` overrides are supported — httpx applies the
per-request value over the client default.

Lifecycle:
    - Clients are lazily created on first access.
    - ``close_all_clients()`` is called during app shutdown from lifespan.
"""

from __future__ import annotations

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_scraper_client: httpx.AsyncClient | None = None
_blog_client: httpx.AsyncClient | None = None
_general_client: httpx.AsyncClient | None = None
_supabase_auth_client: httpx.AsyncClient | None = None


def _make_client(
    timeout: float = 60.0,
    max_connections: int = 10,
    max_keepalive: int = 3,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=follow_redirects,
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
        ),
    )


def get_scraper_client() -> httpx.AsyncClient:
    """Shared HTTP client for data-hub scrapers."""
    global _scraper_client
    if _scraper_client is None or _scraper_client.is_closed:
        _scraper_client = _make_client(timeout=60.0, max_connections=10, max_keepalive=3)
    return _scraper_client


def get_blog_client() -> httpx.AsyncClient:
    """Shared HTTP client for blog generation (Perplexity, SerpAPI)."""
    global _blog_client
    if _blog_client is None or _blog_client.is_closed:
        _blog_client = _make_client(timeout=120.0, max_connections=5, max_keepalive=2)
    return _blog_client


def get_general_client() -> httpx.AsyncClient:
    """Shared HTTP client for misc outbound calls (image downloads, geocoding, etc.)."""
    global _general_client
    if _general_client is None or _general_client.is_closed:
        _general_client = _make_client(timeout=60.0, max_connections=20, max_keepalive=10)
    return _general_client


def get_supabase_auth_http_client() -> httpx.AsyncClient:
    """Shared HTTP client for Supabase Auth (verify_token, admin user ops).

    Tuned for short, latency-sensitive calls against GoTrue (default
    ``/auth/v1`` endpoints).  Uses a 10 s default timeout and a larger
    keep-alive pool than the general client because token verification
    happens on every authenticated request.
    """
    global _supabase_auth_client
    if _supabase_auth_client is None or _supabase_auth_client.is_closed:
        _supabase_auth_client = _make_client(
            timeout=10.0, max_connections=10, max_keepalive=5
        )
    return _supabase_auth_client


async def close_all_clients() -> None:
    """Close all shared HTTP clients. Called during app shutdown."""
    global _scraper_client, _blog_client, _general_client, _supabase_auth_client
    for name, client in (
        ("scraper", _scraper_client),
        ("blog", _blog_client),
        ("general", _general_client),
        ("supabase_auth_http", _supabase_auth_client),
    ):
        if client is not None and not client.is_closed:
            await client.aclose()
            logger.info("Closed shared HTTP client: %s", name)

    _scraper_client = None
    _blog_client = None
    _general_client = None
    _supabase_auth_client = None
