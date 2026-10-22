"""Per-IP limits for the public AI endpoints, built on EndpointRateLimiter and CacheManager.incr.

One helper replaces the copy of the same dependency in each endpoint module::

    _limit = ai_limit("design-studio:generate", per_minute=10)

    @router.post("/generate", dependencies=[Depends(_limit)])

The same object is awaitable, so a handler can apply a limit only for some requests
(``await _daily(request)``). Each window is a fixed window that starts at the first call.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.middleware.rate_limit import EndpointRateLimiter, get_client_ip

MINUTE, HOUR, DAY = 60, 3600, 86400


class AILimit:
    def __init__(
        self,
        name: str,
        *,
        per_minute: int | None = None,
        per_hour: int | None = None,
        per_day: int | None = None,
    ):
        self.name = name
        windows = [(per_minute, MINUTE), (per_hour, HOUR), (per_day, DAY)]
        # Longest window first: a call the day cap refuses does not spend a minute of budget, and
        # Retry-After names the window that actually blocks.
        self.windows = [
            (EndpointRateLimiter(calls=calls, period=period), period)
            for calls, period in sorted(windows, key=lambda w: -w[1])
            if calls
        ]

    async def __call__(self, request: Request) -> None:
        """Count the call in every window. Raise 429 with Retry-After when one is full.

        A refused call costs nothing: the windows it already counted, and the full one, are
        given back. Windows run longest first, so Retry-After names the window that blocks."""
        client_id = f"ip:{get_client_ip(request)}"
        counted: list[tuple[EndpointRateLimiter, str]] = []
        for limiter, period in self.windows:
            endpoint = f"AI:{self.name}:{period}"
            allowed = await limiter.check_rate_limit(client_id, endpoint)
            counted.append((limiter, endpoint))
            if not allowed:
                for done, name in counted:
                    await done.refund(client_id, name)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Rate limit exceeded. Please try again later.",
                    },
                    headers={"Retry-After": str(period)},
                )


def ai_limit(
    name: str, *, per_minute: int | None = None, per_hour: int | None = None, per_day: int | None = None
) -> AILimit:
    return AILimit(name, per_minute=per_minute, per_hour=per_hour, per_day=per_day)
