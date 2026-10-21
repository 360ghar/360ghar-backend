"""Weak ETags and 304 Not Modified for GET JSON responses under /api/v1."""

from __future__ import annotations

import hashlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Headers that describe the body. A 304 has no body, so these are dropped.
_BODY_HEADERS = {b"content-length", b"content-type"}


def make_etag(body: bytes) -> str:
    """Weak ETag from the exact body bytes. Per-user bodies give per-user tags."""
    return f'W/"{hashlib.blake2b(body, digest_size=16).hexdigest()}"'


def etag_matches(if_none_match: str, etag: str) -> bool:
    """RFC 9110 weak comparison of an If-None-Match list (or ``*``) against ``etag``."""
    opaque = etag.removeprefix("W/")
    for tag in if_none_match.split(","):
        tag = tag.strip()
        if tag == "*" or tag.removeprefix("W/") == opaque:
            return True
    return False


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


def _vary_on_authorization(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Add Authorization to the Vary header, merged into one header when one exists."""
    for i, (key, value) in enumerate(headers):
        if key.lower() == b"vary":
            if b"authorization" in value.lower():
                return headers
            return [*headers[:i], (key, value + b", Authorization"), *headers[i + 1 :]]
    return [*headers, (b"vary", b"Authorization")]


class ETagMiddleware:
    """Add a weak ETag to 200 GET/HEAD JSON responses and answer If-None-Match with 304.

    Pure ASGI middleware, like ``CacheControlMiddleware``. Streaming (SSE), non-200,
    non-JSON responses and responses that already carry an ETag pass through untouched.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if (
            scope["type"] != "http"
            or scope.get("method") not in ("GET", "HEAD")
            or not scope.get("path", "").startswith("/api/v1")
        ):
            await self.app(scope, receive, send)
            return

        if_none_match = _header(scope.get("headers", []), b"if-none-match")
        start: Message | None = None
        chunks: list[bytes] = []

        async def send_with_etag(message: Message):
            nonlocal start
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                content_type = (_header(headers, b"content-type") or b"").split(b";")[0].strip()
                if (
                    message.get("status") == 200
                    and content_type.lower() == b"application/json"
                    and _header(headers, b"etag") is None
                ):
                    start = message  # hold until the full body is known
                    return
            elif message["type"] == "http.response.body" and start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                await self._finish(start, b"".join(chunks), if_none_match, send)
                return
            await send(message)

        await self.app(scope, receive, send_with_etag)

    @staticmethod
    async def _finish(start: Message, body: bytes, if_none_match: bytes | None, send: Send):
        etag = make_etag(body)
        headers = _vary_on_authorization(
            [*start.get("headers", []), (b"etag", etag.encode("latin-1"))]
        )
        if if_none_match is not None and etag_matches(if_none_match.decode("latin-1"), etag):
            headers = [(k, v) for k, v in headers if k.lower() not in _BODY_HEADERS]
            await send({"type": "http.response.start", "status": 304, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": body})
