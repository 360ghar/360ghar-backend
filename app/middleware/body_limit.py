from __future__ import annotations

from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.infrastructure.errors import error_response

# Public endpoints that take a large body. FastAPI reads the whole body before it
# runs dependencies or validators, so the cap has to sit in front of the router.
BODY_LIMITS: Mapping[str, int] = {
    "/api/v1/design-studio/generate": 7_200_000,  # 7,000,000 base64 chars plus the prompt
    "/api/v1/design-studio/stage": 7_200_000,  # 5 MB photo as base64 plus the choices
    "/api/v1/ai/listing-draft": 36_000_000,  # 8 photos of 3 MiB decoded as base64 (33.6 MB) plus the hints and JSON
    "/api/v1/ai/legal-draft": 32 * 1024,  # strict text fields only; a small cap stops a huge unknown-key body
    "/api/v1/vastu/analyze": 6 * 1024 * 1024,  # 5 MB image plus multipart framing
}


class BodyLimitMiddleware:
    """Reject a request body above the per-path cap with 413, before it is buffered.

    A declared Content-Length is checked up front. A chunked body is counted as it
    arrives: past the cap the stream is cut and the client gets 413.
    """

    def __init__(self, app: ASGIApp, limits: Mapping[str, int] = BODY_LIMITS):
        self.app = app
        self.limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self.limits.get(scope.get("path", "")) if scope["type"] == "http" else None
        if limit is None or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._too_large(scope, receive, send, limit)
            return

        received = 0
        rejected = False

        async def counting_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request" and not rejected:
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer now, then tell the app the client is gone so it stops reading.
                    rejected = True
                    await self._too_large(scope, receive, send, limit)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if not rejected:
                await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            # The app fails on the cut stream (ClientDisconnect). The 413 is already sent.
            if not rejected:
                raise

    @staticmethod
    async def _too_large(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        response = error_response(
            413,
            "PAYLOAD_TOO_LARGE",
            f"Request body is larger than {limit // 1024} KB",
        )
        await response(scope, receive, send)
