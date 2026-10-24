"""Quarterly price points derived from a project's own filed figures.

This is a data-hub scraper in name only: the "scrape" phase reads Postgres
instead of the network, so a run still produces a ``ScrapeRun`` row, error
capture, and scheduler wiring without pretending an HTTP source exists.

The rule this module exists to enforce: **a price point is only ever written
when a filed figure supports it.** ``launch`` and ``filing`` points are numbers
the developer filed with HRERA. A point interpolated between them is written as
``derived`` so a computed number is never mistaken for a filed one. When the
dates that place a figure in time are missing, no point is written at all —
a guessed quarter is a claim, and the filing made no such claim.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import (
    ProjectPriceHistory,
    ReraProject,
    ReraProjectDocument,
    ReraProjectProfile,
)
from app.models.enums import ProjectPriceSource
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)

#: Upper bound on the projects examined in one run, so a single run cannot walk
#: the whole register. Projects with no price rows are visited first, so repeated
#: runs converge on full coverage.
DEFAULT_BATCH = 500

#: Unit type for a project-wide price. A per-type figure is only written when a
#: filing genuinely breaks the price down by unit type; no parser does that yet.
DEFAULT_UNIT_TYPE = "all"

QUARTERS_PER_YEAR = 4
PRICE_QUANTUM = Decimal("0.01")

# Natural key of a price point. Mirrors ``uq_project_price_history_point``.
PRICE_POINT_INDEX_ELEMENTS = ["rera_project_id", "quarter", "unit_type", "source"]


def quarter_key(value: date | datetime) -> str:
    """The ``"YYYY-QN"`` label of the quarter a date falls in."""
    quarter = (value.month - 1) // 3 + 1
    return f"{value.year}-Q{quarter}"


def quarter_index(quarter: str) -> int:
    """Monotonic index of a ``"YYYY-QN"`` label, so quarters can be subtracted."""
    year_text, separator, quarter_text = quarter.partition("-Q")
    if not separator or not quarter_text.isdigit():
        raise ValueError(f"Not a quarter label: {quarter!r}")
    number = int(quarter_text)
    if not 1 <= number <= QUARTERS_PER_YEAR:
        raise ValueError(f"Quarter out of range: {quarter!r}")
    return int(year_text) * QUARTERS_PER_YEAR + (number - 1)


def quarter_from_index(index: int) -> str:
    """Inverse of :func:`quarter_index`."""
    year, remainder = divmod(index, QUARTERS_PER_YEAR)
    return f"{year}-Q{remainder + 1}"


def quarter_start_date(quarter: str) -> date:
    """First day of the quarter named by ``"YYYY-QN"``."""
    year_text, _, quarter_text = quarter.partition("-Q")
    month = (int(quarter_text) - 1) * 3 + 1
    return date(int(year_text), month, 1)


def interpolate_price(start: Decimal, end: Decimal, step: int, total_steps: int) -> Decimal:
    """Linear price between two filed points, ``step`` of ``total_steps`` along."""
    fraction = Decimal(step) / Decimal(total_steps)
    return (start + (end - start) * fraction).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def _price_point(
    *,
    rera_project_id: int,
    quarter: str,
    price_per_sqft: Decimal,
    source: ProjectPriceSource,
    unit_type: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    return {
        "rera_project_id": rera_project_id,
        "quarter": quarter,
        "period_start": quarter_start_date(quarter),
        "unit_type": unit_type,
        "price_per_sqft": price_per_sqft,
        "source": source,
        "recorded_at": recorded_at,
    }


def derive_price_points(
    *,
    rera_project_id: int,
    launch_price_per_sqft: Decimal | None,
    launch_quarter: str | None,
    current_price_per_sqft: Decimal | None,
    current_quarter: str | None,
    unit_type: str = DEFAULT_UNIT_TYPE,
    recorded_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Price points this project's own filings support — and nothing else.

    * ``launch`` needs a launch price *and* a date to place it in a quarter.
    * ``filing`` needs a current price *and* a date to place it in a quarter.
    * ``derived`` points are written only when both filed points exist, the two
      prices differ, and there is at least one whole quarter strictly between
      them. Each one is labelled ``derived``.
    """
    recorded_at = recorded_at or datetime.now(UTC)
    points: list[dict[str, Any]] = []

    if launch_price_per_sqft is not None and launch_quarter is not None:
        points.append(
            _price_point(
                rera_project_id=rera_project_id,
                quarter=launch_quarter,
                price_per_sqft=Decimal(launch_price_per_sqft),
                source=ProjectPriceSource.launch,
                unit_type=unit_type,
                recorded_at=recorded_at,
            )
        )
    if current_price_per_sqft is not None and current_quarter is not None:
        points.append(
            _price_point(
                rera_project_id=rera_project_id,
                quarter=current_quarter,
                price_per_sqft=Decimal(current_price_per_sqft),
                source=ProjectPriceSource.filing,
                unit_type=unit_type,
                recorded_at=recorded_at,
            )
        )

    # Interpolation needs both filed prices and both quarters.
    if (
        launch_price_per_sqft is None
        or current_price_per_sqft is None
        or launch_quarter is None
        or current_quarter is None
    ):
        return points

    launch_price = Decimal(launch_price_per_sqft)
    current_price = Decimal(current_price_per_sqft)
    if launch_price == current_price:
        # Nothing moved, so there is nothing to interpolate.
        return points

    launch_index = quarter_index(launch_quarter)
    current_index = quarter_index(current_quarter)
    total_steps = current_index - launch_index
    if total_steps < 2:
        # No whole quarter sits strictly between the two filed points.
        return points

    for offset in range(1, total_steps):
        points.append(
            _price_point(
                rera_project_id=rera_project_id,
                quarter=quarter_from_index(launch_index + offset),
                price_per_sqft=interpolate_price(
                    launch_price, current_price, offset, total_steps
                ),
                source=ProjectPriceSource.derived,
                unit_type=unit_type,
                recorded_at=recorded_at,
            )
        )
    return points


class ReraPriceHistoryScraper(BaseScraper):
    """Derive quarterly price points for projects that have a REP-I profile."""

    name = "rera_price_history"
    requires_playwright = False

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {
                "status": "disabled",
                "run_id": None,
                "reason": "hrera_disabled_by_configuration",
            }
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _work_list(self) -> list[dict[str, Any]]:
        """Projects with a profile, unpriced first, bounded by ``DEFAULT_BATCH``.

        Read in its own short-lived session so the derivation phase below holds
        no database connection.
        """
        from app.core.database import get_bg_session_factory

        price_rows = (
            select(func.count(ProjectPriceHistory.id))
            .where(ProjectPriceHistory.rera_project_id == ReraProject.id)
            .correlate(ReraProject)
            .scalar_subquery()
        )
        latest_document = (
            select(func.max(ReraProjectDocument.uploaded_on))
            .where(ReraProjectDocument.rera_project_id == ReraProject.id)
            .correlate(ReraProject)
            .scalar_subquery()
        )
        candidates = (
            select(
                ReraProject.id.label("rera_project_id"),
                ReraProject.registration_date.label("registration_date"),
                ReraProjectProfile.rera_received_date.label("rera_received_date"),
                ReraProjectProfile.launch_price_per_sqft.label("launch_price_per_sqft"),
                ReraProjectProfile.current_price_per_sqft.label("current_price_per_sqft"),
                ReraProjectProfile.updated_at.label("profile_updated_at"),
                latest_document.label("latest_document_on"),
                price_rows.label("price_rows"),
            )
            .join(ReraProjectProfile, ReraProjectProfile.rera_project_id == ReraProject.id)
            .subquery()
        )
        statement = (
            select(candidates)
            .order_by(candidates.c.price_rows, candidates.c.rera_project_id)
            .limit(DEFAULT_BATCH)
        )
        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            rows = (await db.execute(statement)).all()
        return [dict(row._mapping) for row in rows]

    async def _scrape(self) -> ScrapeResult:
        if not settings.HRERA_DATA_ENABLED:
            return ScrapeResult()
        result = ScrapeResult()
        coverage: dict[str, Any] = {
            "source": "rera_project_profiles",
            "projects_checked": 0,
            "projects_priced": 0,
            "projects_skipped": 0,
            "records_parsed": 0,
            "status": "failed",
        }
        try:
            work = await self._work_list()
        except Exception as exc:
            logger.warning("Could not read the price-history work list: %s", exc)
            result.errors.append(
                {
                    "stage": "work_list",
                    "error_type": type(exc).__name__,
                    "message": "The price-history work list could not be read",
                }
            )
            result.source_coverage.append(coverage)
            return result

        recorded_at = datetime.now(UTC)
        for item in work:
            coverage["projects_checked"] += 1
            launch_quarter = _filed_quarter(
                item.get("rera_received_date"), item.get("registration_date")
            )
            filing_quarter = _filed_quarter(
                item.get("latest_document_on"), item.get("profile_updated_at")
            )
            points = derive_price_points(
                rera_project_id=item["rera_project_id"],
                launch_price_per_sqft=item.get("launch_price_per_sqft"),
                launch_quarter=launch_quarter,
                current_price_per_sqft=item.get("current_price_per_sqft"),
                current_quarter=filing_quarter,
                recorded_at=recorded_at,
            )
            if points:
                coverage["projects_priced"] += 1
                result.records.extend(points)
            else:
                coverage["projects_skipped"] += 1

        coverage["records_parsed"] = len(result.records)
        coverage["status"] = "partial" if result.errors else "success"
        # The register was read successfully; a run with no derivable points is
        # still a successful read, not a failed scrape.
        result.successful_sources = 1
        result.source_coverage.append(coverage)
        return result

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {"found": 0, "upserted": 0, "failed": 0}
        found = len(records)
        upserted = 0
        failed = 0
        for record in records:
            record["_upsert_succeeded"] = False
            try:
                values = {
                    key: value
                    for key, value in record.items()
                    if hasattr(ProjectPriceHistory, key) and key not in ("id", "created_at")
                }
                async with db.begin_nested():
                    statement = pg_insert(ProjectPriceHistory).values(**values)
                    await db.execute(
                        statement.on_conflict_do_update(
                            index_elements=PRICE_POINT_INDEX_ELEMENTS,
                            set_={
                                "period_start": statement.excluded.period_start,
                                "price_per_sqft": statement.excluded.price_per_sqft,
                                "recorded_at": statement.excluded.recorded_at,
                            },
                        )
                    )
                upserted += 1
                record["_upsert_succeeded"] = True
            except Exception as exc:
                logger.warning(
                    "Failed to write price point for project %s quarter %s: %s",
                    record.get("rera_project_id"),
                    record.get("quarter"),
                    exc,
                )
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}


def _filed_quarter(primary: date | datetime | None, fallback: date | datetime | None) -> str | None:
    """Quarter of the primary date, else the fallback date, else nothing.

    ``None`` means the filing carries no date that can place the figure in a
    quarter. The caller must then skip the point rather than guess a quarter.
    """
    for candidate in (primary, fallback):
        if isinstance(candidate, datetime):
            return quarter_key(candidate)
        if isinstance(candidate, date):
            return quarter_key(candidate)
    return None
