"""Startup-time validation for the deep-link service configuration.

Called from the FastAPI lifespan hook (see ``app.infrastructure.lifespan``)
before the app begins serving requests. Surfaces misconfigurations that
the service layer would otherwise silently emit (e.g. a placeholder
Apple Team ID that produces an AASA file iOS will reject).
"""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.services.deeplinks.service import _PLACEHOLDER_TEAM_ID

logger = logging.getLogger(__name__)

# Apple Team IDs are exactly 10 uppercase alphanumeric characters.
_TEAM_ID_RE = re.compile(r"^[A-Z0-9]{10}$")


def _is_valid_team_id(team_id: str) -> bool:
    return bool(team_id) and team_id != _PLACEHOLDER_TEAM_ID and bool(_TEAM_ID_RE.match(team_id))


def validate_deeplink_config() -> None:
    """Validate deep-link configuration at app startup.

    Behaviour:
      * If ``DEEPLINK_FAIL_ON_PLACEHOLDER`` is False, logs a warning and
        returns. Local dev and CI can boot with the placeholder values.
      * If True, raises :class:`RuntimeError` when the Apple Team ID is
        the placeholder or fails the 10-char alphanumeric check.

    Production deployments must set ``DEEPLINK_FAIL_ON_PLACEHOLDER=True``
    so a misconfigured Team ID is caught at deploy time, not at the first
    time an iOS device tries to verify an AASA fetch (which would fail
    silently and break Universal Links for every user).
    """
    # Read the raw setting directly rather than via service._team_id(): that
    # helper logs its own warning as a side-effect, which would double-log
    # (or noise before the RuntimeError) when this validator also reports.
    team_id = settings.DEEPLINK_APPLE_TEAM_ID.strip()
    if _is_valid_team_id(team_id):
        return

    message = (
        f"DEEPLINK_APPLE_TEAM_ID={team_id!r} is invalid; expected a real "
        f"10-character alphanumeric Apple Team ID. The "
        f"apple-app-site-association file will emit invalid appID values "
        f"and iOS Universal Links will not verify."
    )
    if settings.DEEPLINK_FAIL_ON_PLACEHOLDER:
        raise RuntimeError(message)
    logger.warning(message)
