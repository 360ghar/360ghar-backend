"""Shared dependencies and helpers for data hub endpoints."""

from typing import Any

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_logger
from app.schemas.pagination import build_cursor_page

logger = get_logger(__name__)

_STAMP_DUTY_RATES: dict[str, float] = {"male": 7.0, "female": 5.0, "joint": 6.0}


async def _safe_list_query(
    db: AsyncSession,
    model,
    count_q,
    data_q,
    offset: int,
    limit: int,
    *,
    with_total: bool = True,
):
    """Execute count + data queries. A database error raises 503 instead of returning empty data.

    Fetches ``limit + 1`` rows so the caller can detect ``has_more`` without
    a second data query. When ``with_total`` is False the count query is
    skipped and ``total`` is returned as ``None``.

    The primary key is appended to the ORDER BY as a unique tiebreak. Offset
    pages then stay stable when rows share a sort value.
    """
    try:
        total: int | None = None
        if with_total:
            total = (await db.execute(count_q)).scalar_one()
        data_q = data_q.order_by(model.id)
        rows = (await db.execute(data_q.offset(offset).limit(limit + 1))).scalars().all()
    except (ProgrammingError, OperationalError) as exc:
        logger.error("Data-hub query failed for %s: %s", model.__name__, exc)
        raise ServiceUnavailableException(
            detail="Auction data is temporarily unavailable",
            error_code="DATA_UNAVAILABLE",
        ) from exc
    return rows, total


async def facet_execute(db: AsyncSession, stmt: Select[Any]):
    """Run a facet query (distinct values). A database error raises 503, as _safe_list_query does."""
    try:
        return await db.execute(stmt)
    except (ProgrammingError, OperationalError) as exc:
        logger.error("Data-hub facet query failed: %s", exc)
        raise ServiceUnavailableException(
            detail="Data is temporarily unavailable",
            error_code="DATA_UNAVAILABLE",
        ) from exc


def facet_page(values: list[Any]) -> dict[str, Any]:
    """Wrap a distinct-value list in one CursorPage.

    ponytail: facet lists are small (banks, cities, sectors). One page holds all of them.
    Add offset paging when a facet passes about 100 values.
    """
    return build_cursor_page(values, limit=len(values), next_payload=None)
