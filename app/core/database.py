from __future__ import annotations

import time
from collections.abc import AsyncGenerator

import sentry_sdk
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Base class for all models
class Base(DeclarativeBase):
    pass

# Log database connection info
logger.info("Connecting to database with psycopg for PgBouncer compatibility")

# Shared connection args for PgBouncer compatibility
_connect_args = {
    "application_name": "360ghar_backend",
    "prepare_threshold": None,  # Disable prepared statements for PgBouncer
}

_bg_connect_args = {
    "application_name": "360ghar_bg",
    "prepare_threshold": None,
}

# ── Serverless: NullPool prevents persistent connections that generate ────────
# outbound packets, which would keep Railway from scaling to zero.
# PgBouncer handles server-side pooling, so client-side pooling is not needed.
# Trade-off: each request creates a fresh connection (adds ~10-50ms latency).
_use_null_pool = settings.SERVERLESS_ENABLED

if _use_null_pool:
    logger.info("Serverless mode — using NullPool (no persistent DB connections)")

# ── Main engine: HTTP/MCP request traffic ─────────────────────────────────────
# PgBouncer (Supabase) handles server-side pooling — keep the app-side
# pool small to avoid exhausting PgBouncer's transaction-mode slots.
_main_engine_kwargs: dict = {
    "echo": settings.DEBUG,
    "future": True,
    "connect_args": _connect_args,
}
if _use_null_pool:
    _main_engine_kwargs["poolclass"] = NullPool
else:
    _main_engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )

engine = create_async_engine(settings.ASYNC_DATABASE_URL, **_main_engine_kwargs)

# ── Background engine: schedulers, scrapers, long-running tasks ───────────────
# Isolated from the main pool so background work can't starve API traffic.
# In serverless mode, this engine is unused (schedulers are skipped) but
# still created to avoid import errors; NullPool means zero overhead.
_bg_engine_kwargs: dict = {
    "echo": settings.DEBUG,
    "future": True,
    "connect_args": _bg_connect_args,
}
if _use_null_pool:
    _bg_engine_kwargs["poolclass"] = NullPool
else:
    _bg_engine_kwargs.update(
        pool_size=settings.DB_BG_POOL_SIZE,
        max_overflow=settings.DB_BG_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )

bg_engine = create_async_engine(settings.ASYNC_DATABASE_URL, **_bg_engine_kwargs)

# ── Slow-checkout logging ──────────────────────────────────────────────────────
_SLOW_CHECKOUT_THRESHOLD_S = 5.0
_SESSION_HOLD_WARN_S = 30.0
_disposing = False  # set True during engine.dispose() to suppress teardown noise


def _on_checkout(dbapi_conn, connection_record, connection_proxy):
    connection_record.info["_checkout_start"] = time.monotonic()


def _make_checkin_logger(pool_label: str, pool):
    def _on_checkin(dbapi_conn, connection_record):
        if _disposing:
            return
        start = connection_record.info.pop("_checkout_start", None)
        if start is not None:
            elapsed = time.monotonic() - start
            if elapsed > _SLOW_CHECKOUT_THRESHOLD_S:
                logger.warning(
                    "Slow pool checkout: %.1fs (pool: %s, size: %d, checkedout: %d, overflow: %d)",
                    elapsed,
                    pool_label,
                    pool.size(),
                    pool.checkedout(),
                    pool.overflow(),
                )
    return _on_checkin


if not _use_null_pool:
    for _eng, _label in [(engine, "main"), (bg_engine, "background")]:
        _pool = _eng.sync_engine.pool
        event.listen(_eng.sync_engine, "checkout", _on_checkout)
        event.listen(_eng.sync_engine, "checkin", _make_checkin_logger(_label, _pool))

# ── Session factories ──────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

AsyncSessionLocalBG = async_sessionmaker(
    bg_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── FastAPI dependencies ───────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        session_start = time.monotonic()
        try:
            yield session
        except HTTPException:
            # Propagate HTTP errors without logging as DB errors
            await session.rollback()
            raise
        except Exception as e:
            logger.error("Database session error: %s", e)
            sentry_sdk.set_context("database", {
                "error_type": type(e).__name__,
                "error_message": str(e),
            })
            await session.rollback()
            raise
        else:
            # Commit only if the session actually has pending changes.
            # Read-only requests (GETs, detail views) should not force a
            # write transaction against the database / PgBouncer. Services
            # that explicitly call ``await session.commit()`` are unaffected
            # because by the time we reach this branch those changes have
            # already been committed and the session is clean.
            if session.new or session.dirty or session.deleted:
                await session.commit()
        finally:
            hold_time = time.monotonic() - session_start
            if hold_time > _SESSION_HOLD_WARN_S:
                logger.warning(
                    "DB session held for %.1fs — possible connection leak",
                    hold_time,
                    stack_info=True,
                )


async def get_bg_db() -> AsyncGenerator[AsyncSession, None]:
    """Background task dependency — uses the isolated background pool."""
    async with AsyncSessionLocalBG() as session:
        try:
            yield session
        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            logger.error("Background database session error: %s", e)
            sentry_sdk.set_context("database", {
                "error_type": type(e).__name__,
                "error_message": str(e),
            })
            await session.rollback()
            raise
        else:
            # Only commit if the background task actually mutated state.
            if session.new or session.dirty or session.deleted:
                await session.commit()


def mark_engines_disposing() -> None:
    """Suppress slow-checkout warnings during engine.dispose() teardown."""
    global _disposing
    _disposing = True


def get_async_session_factory():
    """
    Get the async session factory for use in background tasks.

    This allows background tasks to create their own database sessions
    independent of the FastAPI request lifecycle.

    Returns:
        async_sessionmaker: The session factory
    """
    return AsyncSessionLocal


def get_bg_session_factory():
    """
    Get the background async session factory (isolated pool).

    Use this for schedulers, scrapers, and other long-running background
    tasks that should not compete with HTTP/MCP request traffic.

    Returns:
        async_sessionmaker: The background session factory
    """
    return AsyncSessionLocalBG
