"""Tests for the async DB session dependencies.

Covers the read-only commit fix: ``get_db`` / ``get_bg_db`` must NOT issue a
``commit()`` when the request did not mutate any persistent state. Read-only
GET paths should not force a write transaction against the database / PgBouncer.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def _awaited_and_caller_cleanup(gen):
    """Drive the async generator to completion for test purposes."""
    return gen


@pytest.mark.asyncio
async def test_get_db_does_not_commit_when_session_is_clean():
    """A read-only request (no new/dirty/deleted) must not trigger commit."""
    from app.core import database as db_module

    fake_session = MagicMock(spec=AsyncSession)
    fake_session.new = set()
    fake_session.dirty = set()
    fake_session.deleted = set()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.close = AsyncMock()

    factory = MagicMock(return_value=fake_session)
    # Make ``async with factory() as session`` yield our fake session
    factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocal", factory)

        gen = db_module.get_db()
        # Prime the generator
        yielded = await gen.__anext__()
        assert yielded is fake_session
        # End the request without an exception -> else branch
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    fake_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_db_commits_when_session_has_pending_changes():
    """A request that mutated state must still commit on clean exit."""
    from app.core import database as db_module

    fake_session = MagicMock(spec=AsyncSession)
    fake_session.new = {object()}  # something pending
    fake_session.dirty = set()
    fake_session.deleted = set()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.close = AsyncMock()

    factory = MagicMock(return_value=fake_session)
    factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocal", factory)

        gen = db_module.get_db()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception():
    """On exception, rollback must fire and commit must not."""
    from app.core import database as db_module

    fake_session = MagicMock(spec=AsyncSession)
    fake_session.new = set()
    fake_session.dirty = set()
    fake_session.deleted = set()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.close = AsyncMock()

    factory = MagicMock(return_value=fake_session)
    factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocal", factory)

        gen = db_module.get_db()
        await gen.__anext__()
        with pytest.raises(ValueError):
            await gen.athrow(ValueError, "boom", None)

    fake_session.rollback.assert_awaited()
    fake_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_bg_db_does_not_commit_when_session_is_clean():
    """Background dependency also must skip commit for read-only work."""
    from app.core import database as db_module

    fake_session = MagicMock(spec=AsyncSession)
    fake_session.new = set()
    fake_session.dirty = set()
    fake_session.deleted = set()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.close = AsyncMock()

    factory = MagicMock(return_value=fake_session)
    factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocalBG", factory)

        gen = db_module.get_bg_db()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    fake_session.commit.assert_not_awaited()


def test_get_db_signature_is_unchanged_async_generator():
    """Regression guard: get_db must remain an async generator dependency."""
    from app.core import database as db_module

    assert inspect.isasyncgenfunction(db_module.get_db)
    assert inspect.isasyncgenfunction(db_module.get_bg_db)
