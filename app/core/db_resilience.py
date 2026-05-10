import asyncio
import random
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError, DisconnectionError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

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
