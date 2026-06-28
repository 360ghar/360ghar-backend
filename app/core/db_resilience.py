from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, DisconnectionError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


async def apply_statement_timeout(session: AsyncSession, timeout_ms: int) -> None:
    """Bound how long statements in the current transaction may run.

    Uses ``SET LOCAL`` so the timeout is scoped to the active transaction and
    never leaks across PgBouncer-pooled clients. Without this, a stalled query
    (e.g. blocked on a lock or a throttled DB backend) holds a pooler
    connection until the server-default ``statement_timeout`` (2 minutes on
    this deployment), which exhausts the transaction-mode pool and cascades.
    A bounded timeout makes such a stall fail fast and free the connection.

    ``timeout_ms`` is an int from configuration (never user input), so it is
    inlined — ``SET`` does not accept bind parameters in PostgreSQL.
    """
    if timeout_ms <= 0:
        return
    await session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))


def is_statement_timeout(exc: Exception) -> bool:
    """True if the error is a server-side ``statement_timeout`` cancellation.

    Kept separate from :func:`is_transient_db_error` so the retry helper does
    NOT auto-retry timeouts (the backend is stalled — retrying just holds
    another connection), while endpoints can still map them to a retryable
    503 instead of a 500.
    """
    message = str(exc).lower()
    return (
        "statement timeout" in message
        or "canceling statement due to" in message
        or "querycanceled" in message
    )

TRANSIENT_DB_ERROR_CODES = {"EDBHANDLEREXITED", "ECHECKOUTTIMEOUT"}
_TRANSIENT_DB_MESSAGE_MARKERS = (
    "connection to database closed",
    "unable to check out connection from the pool",
)


def extract_db_error_code(exc: Exception) -> str | None:
    text = str(exc)
    for code in TRANSIENT_DB_ERROR_CODES:
        if code in text:
            return code
    match = re.search(r"\((E[A-Z0-9_]{3,})\)", text)
    return match.group(1) if match else None


def _is_pool_exhaustion_error(exc: Exception) -> bool:
    """Pool exhaustion is a capacity problem — retrying makes it worse."""
    return "QueuePool limit" in str(exc) or "3o7r" in str(exc)


def is_transient_db_error(exc: Exception) -> bool:
    if isinstance(exc, (DisconnectionError, SATimeoutError)):
        return True
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True

    message = str(exc).lower()
    if any(marker in message for marker in _TRANSIENT_DB_MESSAGE_MARKERS):
        return True
    if any(code in str(exc) for code in TRANSIENT_DB_ERROR_CODES):
        return True
    return False


async def _reset_session_for_retry(session: AsyncSession) -> None:
    try:
        await session.rollback()
    except Exception:
        pass
    try:
        await session.invalidate()
    except Exception:
        pass


async def execute_with_transient_retry(
    session: AsyncSession,
    operation: Callable[[], Awaitable[T]],
    *,
    operation_name: str,
) -> T:
    try:
        return await operation()
    except Exception as exc:
        if not is_transient_db_error(exc):
            raise

        error_code = extract_db_error_code(exc) or "UNKNOWN_TRANSIENT_DB_ERROR"

        # Pool exhaustion is a capacity problem — retrying holds the session
        # open and queues another checkout, making it worse. Fail fast instead.
        if _is_pool_exhaustion_error(exc):
            logger.error(
                "Pool exhaustion detected; skipping retry to reduce pressure",
                extra={"operation": operation_name, "error_code": error_code},
                exc_info=True,
            )
            raise

        logger.warning(
            "Transient DB error detected; retrying once",
            extra={"operation": operation_name, "error_code": error_code, "attempt": 1},
        )
        await _reset_session_for_retry(session)
        await asyncio.sleep(random.uniform(0.05, 0.2))

        try:
            return await operation()
        except Exception as retry_exc:
            retry_code = extract_db_error_code(retry_exc) or error_code
            logger.error(
                "Transient DB error persisted after retry",
                extra={"operation": operation_name, "error_code": retry_code, "attempt": 2},
                exc_info=True,
            )
            raise
