"""Tests for the async DB session dependencies.

Covers the read-only commit fix: ``get_db`` / ``get_bg_db`` must NOT issue a
``commit()`` when the request did not mutate any persistent state. Read-only
GET paths should not force a write transaction against the database / PgBouncer.
"""

from __future__ import annotations

import inspect
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession


def _fake_session(*, pending: bool = False) -> MagicMock:
    """Session mock for get_db / get_bg_db dependency tests."""
    fake_session = MagicMock(spec=AsyncSession)
    fake_session.new = {object()} if pending else set()
    fake_session.dirty = set()
    fake_session.deleted = set()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.close = AsyncMock()
    fake_session.execute = AsyncMock(return_value=None)
    return fake_session


def _session_factory(fake_session: MagicMock) -> MagicMock:
    factory = MagicMock(return_value=fake_session)
    factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.mark.asyncio
async def test_get_db_does_not_commit_when_session_is_clean():
    """A read-only request (no new/dirty/deleted) must not trigger commit."""
    from app.core import database as db_module

    fake_session = _fake_session()
    factory = _session_factory(fake_session)

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
    # Statement timeout is applied at connection open (libpq options), not via
    # SET LOCAL on every acquire — so no execute is required here.
    fake_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_db_does_not_open_transaction_on_acquire():
    """Acquiring a session must not run SET LOCAL (which pins Supavisor backends)."""
    from app.core import database as db_module

    fake_session = _fake_session()
    factory = _session_factory(fake_session)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocal", factory)
        gen = db_module.get_db()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    fake_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_psycopg_connect_args_include_statement_timeout():
    from app.core import database as db_module

    args = db_module._psycopg_connect_args(application_name="test_app")
    assert args["application_name"] == "test_app"
    assert args["prepare_threshold"] is None
    assert "statement_timeout=" in args.get("options", "")


@pytest.mark.asyncio
async def test_get_db_commits_when_session_has_pending_changes():
    """A request that mutated state must still commit on clean exit."""
    from app.core import database as db_module

    fake_session = _fake_session(pending=True)
    factory = _session_factory(fake_session)

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

    fake_session = _fake_session()
    factory = _session_factory(fake_session)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocal", factory)

        gen = db_module.get_db()
        await gen.__anext__()
        with pytest.raises(ValueError):
            await gen.athrow(ValueError, "boom", None)

    fake_session.rollback.assert_awaited()
    fake_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_db_does_not_log_request_validation_as_database_error(caplog):
    """FastAPI 422 request validation must not be mislabeled as a DB error."""
    from app.core import database as db_module

    fake_session = _fake_session()
    factory = _session_factory(fake_session)
    validation_exc = RequestValidationError([
        {
            "loc": ("body", "age"),
            "msg": "Input should be less than or equal to 100",
            "type": "less_than_equal",
        }
    ])

    caplog.set_level(logging.ERROR, logger="app.core.database")

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocal", factory)

        gen = db_module.get_db()
        await gen.__anext__()
        with pytest.raises(RequestValidationError):
            await gen.athrow(validation_exc)

    fake_session.rollback.assert_awaited()
    fake_session.commit.assert_not_awaited()
    assert "Database session error" not in caplog.text


@pytest.mark.asyncio
async def test_get_bg_db_does_not_commit_when_session_is_clean():
    """Background dependency also must skip commit for read-only work."""
    from app.core import database as db_module

    fake_session = _fake_session()
    factory = _session_factory(fake_session)

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


@pytest.mark.asyncio
async def test_get_db_raises_503_when_acquire_times_out():
    """Hung pooler checkout must fail fast with ServiceUnavailableException."""
    import asyncio

    from app.core import database as db_module
    from app.core.exceptions import ServiceUnavailableException

    hang = asyncio.Event()

    class _HangingSessionCM:
        async def __aenter__(self):
            await hang.wait()  # cancelled by asyncio.timeout in get_db
            raise AssertionError("should not complete")

        async def __aexit__(self, *args):
            return None

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(db_module, "AsyncSessionLocal", lambda: _HangingSessionCM())
        mp.setattr(db_module.settings, "DB_ACQUIRE_TIMEOUT_S", 0.05)

        gen = db_module.get_db()
        with pytest.raises(ServiceUnavailableException) as exc_info:
            await gen.__anext__()

    assert exc_info.value.status_code == 503
    assert exc_info.value.details.get("error_code") == "DB_ACQUIRE_TIMEOUT"
