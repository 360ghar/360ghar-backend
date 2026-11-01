"""The cron dependency must never open a maintenance endpoint to the public."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.api_v1.dependencies.cron import require_cron_secret
from app.core.exceptions import ForbiddenException, ServiceUnavailableException


@pytest.mark.asyncio
async def test_missing_configuration_refuses_with_503():
    with patch("app.api.api_v1.dependencies.cron.settings") as mock_settings:
        mock_settings.CRON_SECRET = None
        with pytest.raises(ServiceUnavailableException) as exc_info:
            await require_cron_secret(x_cron_secret="anything")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_wrong_secret_is_forbidden():
    with patch("app.api.api_v1.dependencies.cron.settings") as mock_settings:
        mock_settings.CRON_SECRET = "expected"
        with pytest.raises(ForbiddenException):
            await require_cron_secret(x_cron_secret="wrong")


@pytest.mark.asyncio
async def test_matching_secret_passes():
    with patch("app.api.api_v1.dependencies.cron.settings") as mock_settings:
        mock_settings.CRON_SECRET = "expected"
        await require_cron_secret(x_cron_secret="expected")
