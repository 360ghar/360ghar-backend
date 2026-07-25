from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import Response

from app import main as main_module
from app.api.api_v1.api import api_v1_ready_redirect


@pytest.mark.asyncio
async def test_health_is_liveness_without_database_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = AsyncMock(side_effect=AssertionError("health must not probe the database"))
    monkeypatch.setattr(main_module, "_probe_database_ready", probe)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    result = await main_module.health_check(request)

    assert result["status"] == "healthy"
    assert "database" not in result
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_ready_returns_200_when_database_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = AsyncMock(return_value=(True, "connected"))
    monkeypatch.setattr(main_module, "_probe_database_ready", probe)
    response = Response()

    result = await main_module.readiness_check(response)

    assert response.status_code == 200
    assert result["status"] == "ready"
    assert result["database"] == "connected"
    probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_ready_returns_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = AsyncMock(return_value=(False, "disconnected"))
    monkeypatch.setattr(main_module, "_probe_database_ready", probe)
    response = Response()

    result = await main_module.readiness_check(response)

    assert response.status_code == 503
    assert result["status"] == "unready"
    assert result["database"] == "disconnected"
    probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_v1_ready_redirects_to_root_ready() -> None:
    response = await api_v1_ready_redirect()

    assert response.status_code == 307
    assert response.headers["location"] == "/ready"
