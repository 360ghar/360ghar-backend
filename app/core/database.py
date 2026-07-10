from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import suppress

import sentry_sdk
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger

logger = get_logger(__name__)

_SUPABASE_POOLER_HOST_SUFFIX = ".pooler.supabase.com"
_SUPABASE_SESSION_POOLER_PORT = 5432
_SUPABASE_TRANSACTION_POOLER_PORT = 6543
_SESSION_POOLER_SAFE_CLIENT_BUDGET = 12


def _psycopg_connect_args(*, application_name: str) -> dict:
    """Build psycopg connect_args for PgBouncer/Supavisor safety.

    ``statement_timeout`` is set at connection open (libpq ``options``) so
    request sessions do not need ``SET LOCAL`` on every acquire — that would
    open a transaction and pin a transaction-mode backend for the whole
    request lifetime even when no SQL is running.
    """
    args: dict = {
        "application_name": application_name,
        "prepare_threshold": None,  # Disable prepared statements for PgBouncer
        "connect_timeout": settings.DB_CONNECT_TIMEOUT_S,
    }
    timeout_ms = settings.DB_READ_STATEMENT_TIMEOUT_MS
    if timeout_ms > 0:
        args["options"] = f"-c statement_timeout={int(timeout_ms)}"
    return args

# Base class for all models
class Base(DeclarativeBase):
    pass


def _database_url_host_port(database_url: str) -> tuple[str | None, int | None]:
    try:
        url = make_url(database_url)
    except Exception:
        logger.warning("Could not parse DATABASE_URL for pooler validation")
        return None, None
    return url.host, url.port


def _database_pool_budget(
    db_pool_size: int,
    db_max_overflow: int,
    db_bg_pool_size: int,
    db_bg_max_overflow: int,
) -> int:
    return db_pool_size + db_max_overflow + db_bg_pool_size + db_bg_max_overflow


def _validate_database_pooler_config(
    *,
    database_url: str,
    serverless_enabled: bool,
    environment: str,
    db_pool_size: int,
    db_max_overflow: int,
    db_bg_pool_size: int,
    db_bg_max_overflow: int,
) -> None:
    """Guard against Supabase pooler modes that can exhaust client slots."""
    host, port = _database_url_host_port(database_url)
    is_supabase_pooler = bool(host and host.endswith(_SUPABASE_POOLER_HOST_SUFFIX))
    is_session_pooler = is_supabase_pooler and port == _SUPABASE_SESSION_POOLER_PORT
    is_transaction_pooler = is_supabase_pooler and port == _SUPABASE_TRANSACTION_POOLER_PORT
    is_production = environment.lower() == "production"
    budget = _database_pool_budget(
        db_pool_size,
        db_max_overflow,
        db_bg_pool_size,
        db_bg_max_overflow,
    )

    if is_production and is_supabase_pooler and not is_transaction_pooler:
        raise RuntimeError(
            "Production Supabase pooler URLs must use the transaction pooler "
            f"on port 6543; got port {port or 'unknown'}"
        )

    if serverless_enabled and is_session_pooler:
        message = (
            "SERVERLESS_ENABLED=true must use the Supabase transaction pooler "
            "on port 6543, not the session pooler on port 5432"
        )
        logger.warning(message)

    if not serverless_enabled and is_session_pooler and budget > _SESSION_POOLER_SAFE_CLIENT_BUDGET:
        message = (
            "Supabase session-pooler client budget is too high: "
            f"{budget} > {_SESSION_POOLER_SAFE_CLIENT_BUDGET}. Reduce DB_POOL_SIZE/"
            "DB_MAX_OVERFLOW/DB_BG_POOL_SIZE/DB_BG_MAX_OVERFLOW or use port 6543."
        )
        logger.warning(message)

    pooler_mode = "none"
    if is_session_pooler:
        pooler_mode = "supabase_session"
    elif is_transaction_pooler:
        pooler_mode = "supabase_transaction"
    elif is_supabase_pooler:
        pooler_mode = "supabase_unknown"

    logger.info(
        "Database pool configuration",
        extra={
            "event": "database_pool_config",
            "host": host,
            "port": port,
            "pooler_mode": pooler_mode,
            "serverless": serverless_enabled,
            "client_budget": 0 if serverless_enabled else budget,
        },
    )


_validate_database_pooler_config(
    database_url=settings.DATABASE_URL,
    serverless_enabled=settings.SERVERLESS_ENABLED,
    environment=settings.ENVIRONMENT,
    db_pool_size=settings.DB_POOL_SIZE,
    db_max_overflow=settings.DB_MAX_OVERFLOW,
    db_bg_pool_size=settings.DB_BG_POOL_SIZE,
    db_bg_max_overflow=settings.DB_BG_MAX_OVERFLOW,
)


# Log database connection info
logger.info("Connecting to database with psycopg for PgBouncer compatibility")

# Shared connection args for PgBouncer/Supavisor compatibility.
_connect_args = _psycopg_connect_args(application_name="360ghar_backend")
_bg_connect_args = _psycopg_connect_args(application_name="360ghar_bg")

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
logger.info(
    "Main database engine initialized",
    extra={
        "event": "database_engine_initialized",
        "pool_label": "main",
        "pool_class": "NullPool" if _use_null_pool else "AsyncAdaptedQueuePool",
        "pool_size": 0 if _use_null_pool else settings.DB_POOL_SIZE,
        "max_overflow": 0 if _use_null_pool else settings.DB_MAX_OVERFLOW,
    },
)

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
logger.info(
    "Background database engine initialized",
    extra={
        "event": "database_engine_initialized",
        "pool_label": "background",
        "pool_class": "NullPool" if _use_null_pool else "AsyncAdaptedQueuePool",
        "pool_size": 0 if _use_null_pool else settings.DB_BG_POOL_SIZE,
        "max_overflow": 0 if _use_null_pool else settings.DB_BG_MAX_OVERFLOW,
    },
)

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
def _db_unavailable(exc: BaseException, *, error_code: str) -> ServiceUnavailableException:
    """Map acquire/connect failures to a retryable 503 for API clients."""
    return ServiceUnavailableException(
        detail="Database is temporarily unavailable. Please retry shortly.",
        headers={"Retry-After": "30"},
        details={"error_code": error_code, "endpoint": "get_db"},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session, failing fast if checkout hangs.

    Acquisition (pool checkout / NullPool connect) is hard-bounded by
    ``DB_ACQUIRE_TIMEOUT_S``. The timeout deliberately does **not** cover the
    request body — only opening the session — so normal request work is not
    truncated.

    Statement timeout is applied at connection open (libpq options), not via
    ``SET LOCAL`` here, so idle request sessions do not pin a Supavisor
    transaction-mode backend before the first real query.
    """
    session_start = time.monotonic()
    session_cm = AsyncSessionLocal()
    session: AsyncSession | None = None
    try:
        # Bound only acquire; do not wrap the yielded body.
        async with asyncio.timeout(settings.DB_ACQUIRE_TIMEOUT_S):
            session = await session_cm.__aenter__()
    except TimeoutError as e:
        with suppress(Exception):
            await session_cm.__aexit__(*sys.exc_info())
        logger.error(
            "DB session acquire timed out after %.1fs",
            settings.DB_ACQUIRE_TIMEOUT_S,
            extra={"event": "db_acquire_timeout", "error_code": "DB_ACQUIRE_TIMEOUT"},
        )
        raise _db_unavailable(e, error_code="DB_ACQUIRE_TIMEOUT") from e
    except SATimeoutError as e:
        with suppress(Exception):
            await session_cm.__aexit__(*sys.exc_info())
        logger.error(
            "DB pool checkout timed out: %s",
            e,
            extra={"event": "db_pool_timeout", "error_code": "DB_POOL_TIMEOUT"},
        )
        raise _db_unavailable(e, error_code="DB_POOL_TIMEOUT") from e
    except BaseException:
        with suppress(Exception):
            await session_cm.__aexit__(*sys.exc_info())
        raise

    assert session is not None
    try:
        yield session
    except HTTPException:
        # Propagate HTTP errors without logging as DB errors
        await session.rollback()
        raise
    except RequestValidationError:
        # FastAPI request validation failures are user input errors, not
        # database session failures. Roll back any implicit transaction
        # and let the validation handler produce the 422 response.
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
            # Includes pooler checkout wait under NullPool/serverless, so
            # this is "session lifetime" not necessarily a code-level leak.
            logger.warning(
                "DB session lifetime %.1fs (includes pooler checkout wait) — "
                "investigate slow queries or pool saturation",
                hold_time,
                stack_info=True,
            )
        await session_cm.__aexit__(None, None, None)


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
