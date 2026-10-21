from __future__ import annotations

import hmac

from fastapi import Header

from app.config import settings
from app.core.exceptions import ForbiddenException, ServiceUnavailableException


async def require_cron_secret(x_cron_secret: str | None = Header(default=None)) -> None:
    """Allow a scheduled job that sends the shared secret in ``X-Cron-Secret``.

    503 when CRON_SECRET is not configured, so a missing secret never opens the endpoint.
    The compare is constant-time.
    """
    expected = settings.CRON_SECRET
    if not expected:
        raise ServiceUnavailableException("Cron access is not configured", error_code="CRON_DISABLED")
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret.encode(), expected.encode()):
        raise ForbiddenException("Invalid cron secret", error_code="CRON_FORBIDDEN")
