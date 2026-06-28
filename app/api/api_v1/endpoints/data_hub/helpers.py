"""Shared dependencies and helpers for data hub endpoints."""

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

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
    """Execute count + data queries, returning empty results on DB errors.

    Fetches ``limit + 1`` rows so the caller can detect ``has_more`` without
    a second data query. When ``with_total`` is False the count query is
    skipped and ``total`` is returned as ``None``.
    """
    try:
        total: int | None = None
        if with_total:
            total = (await db.execute(count_q)).scalar_one()
        rows = (await db.execute(data_q.offset(offset).limit(limit + 1))).scalars().all()
    except (ProgrammingError, OperationalError) as exc:
        logger.error("Data-hub table query failed for %s (tables may not exist yet): %s", model.__name__, exc)
        total = 0 if with_total else None
        rows = []
    return rows, total
