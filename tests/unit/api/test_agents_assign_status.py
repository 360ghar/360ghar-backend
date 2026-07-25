"""Assign-agent empty inventory returns 404, not 503."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.api_v1.endpoints import agents as agents_module
from app.api.api_v1.endpoints.agents import router
from app.infrastructure.errors import register_exception_handlers


@pytest.mark.asyncio
async def test_assign_agent_no_agents_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/agents")

    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.is_active = True

    async def _user():
        return mock_user

    async def _db():
        yield MagicMock()

    app.dependency_overrides[agents_module.get_current_active_user] = _user
    app.dependency_overrides[agents_module.get_db] = _db

    monkeypatch.setattr(
        agents_module,
        "assign_agent_to_user",
        AsyncMock(return_value=None),
    )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/agents/assign")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NO_AGENTS_AVAILABLE"
