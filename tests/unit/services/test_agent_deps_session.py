"""AgentDeps must not pin a long-lived DB session across LLM waits."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai_agent.deps import AgentDeps, run_with_short_db_session


@pytest.mark.asyncio
async def test_short_session_opens_and_closes_via_factory():
    session = MagicMock()
    session.new = set()
    session.dirty = set()
    session.deleted = set()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=cm)

    deps = AgentDeps(user=None, user_role="guest", session_factory=factory)
    async with deps.short_session() as db:
        assert db is session

    factory.assert_called_once()
    cm.__aenter__.assert_awaited_once()
    cm.__aexit__.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_with_short_db_session_binds_and_restores():
    session = MagicMock()
    session.new = set()
    session.dirty = set()
    session.deleted = set()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=cm)

    deps = AgentDeps(user=None, user_role="guest", db=None, session_factory=factory)
    seen: dict[str, object] = {}

    async def operation():
        seen["db"] = deps.db
        return {"ok": True}

    result = await run_with_short_db_session(deps, operation)

    assert result == {"ok": True}
    assert seen["db"] is session
    assert deps.db is None
    factory.assert_called_once()


@pytest.mark.asyncio
async def test_run_with_short_db_session_without_factory_uses_injected_db():
    session = AsyncMock()
    deps = AgentDeps(user=None, user_role="guest", db=session, session_factory=None)

    async def operation():
        return deps.db is session

    assert await run_with_short_db_session(deps, operation) is True
