from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.logging import get_logger

logger = get_logger(__name__)

# Public, read-only GET endpoints whose anonymous responses are safe to cache
# downstream (browser + CDN/Cloudflare). This collapses repeat GET traffic
# (crawlers, prerender, the Netlify build) before it ever reaches Postgres —
# the dominant Supabase pooler-egress driver. Authenticated responses are
# never cached here (see _PRIVATE_CACHE_HEADER below).
_CACHEABLE_PATH_PREFIXES = (
    "/api/v1/properties",
    "/api/v1/blog",
    "/api/v1/amenities",
    "/api/v1/faqs/public",
    "/api/v1/localities",
    "/api/v1/data-hub",
)

# Short edge/browser lifetime for anonymous public reads — fresh enough for a
# listings site, long enough to dedupe the bulk of repeat traffic.
_PUBLIC_CACHE_HEADER = b"public, max-age=300, s-maxage=300, stale-while-revalidate=600"
_PRIVATE_CACHE_HEADER = b"private, no-store"

# Cloudflare segments cache by Vary headers. Without these, an authenticated
# response could be cached and served to anonymous users.
_VARY_HEADER = b"Authorization, Accept-Encoding"

# Explicit signal to Cloudflare to never edge-cache authenticated responses.
# Cloudflare-CDN-Cache-Control takes precedence over s-maxage for Cloudflare's
# edge cache; Cache-Control: private, no-store is the browser-level fallback.
_CDN_NO_STORE = b"no-store"


class CacheControlMiddleware:
    """Attach Cache-Control headers to public anonymous GET responses.

    Modeled on ``SecurityHeadersMiddleware`` as pure ASGI middleware so it does
    not interfere with streaming responses (MCP, SSE, websockets).
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

        method = scope.get("method", "")
        path = scope.get("path", "")

        # Skip MCP streaming tool routes (OAuth/well-known still pass through).
        if path.startswith("/mcp") and not (
            path.startswith("/mcp/oauth") or path.startswith("/mcp-admin/oauth")
        ):
            await self.app(scope, receive, send)
            return

        is_cacheable = method in ("GET", "HEAD") and any(
            path.startswith(prefix) for prefix in _CACHEABLE_PATH_PREFIXES
        )

        if not is_cacheable:
            await self.app(scope, receive, send)
            return

        # Authenticated responses carry per-user data — never share them.
        request_headers = scope.get("headers", [])
        is_authed = any(name == b"authorization" for name, _ in request_headers)
        header_value = _PRIVATE_CACHE_HEADER if is_authed else _PUBLIC_CACHE_HEADER

        original_send = send

        async def send_with_cache_control(message):
            if message["type"] == "http.response.start":
                status = message.get("status", 200)
                if 200 <= status < 300:
                    existing_headers = message.get("headers", [])
                    already_set = any(
                        name.lower() == b"cache-control" for name, _ in existing_headers
                    )
                    new_headers = list(existing_headers)
                    # Vary is always needed on cacheable responses so
                    # Cloudflare segments its cache by auth state — even
                    # when the endpoint sets its own Cache-Control.
                    has_vary = any(name.lower() == b"vary" for name, _ in existing_headers)
                    if not has_vary:
                        new_headers.append((b"Vary", _VARY_HEADER))
                    # Never override a Cache-Control the endpoint set
                    # explicitly (e.g. a no-cache SSE response).
                    if not already_set:
                        new_headers.append((b"Cache-Control", header_value))
                        if is_authed:
                            # Cache-Control already says no-store, but
                            # Cloudflare-CDN-Cache-Control is the
                            # authoritative signal for Cloudflare's edge.
                            new_headers.append((b"Cloudflare-CDN-Cache-Control", _CDN_NO_STORE))
                    message["headers"] = new_headers
            await original_send(message)

        await self.app(scope, receive, send_with_cache_control)
