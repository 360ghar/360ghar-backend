"""Daily market pulse: one reading per city, per day.

This is a data-hub scraper in name only: the "scrape" phase reads Postgres
instead of the network, so a run still produces a ``ScrapeRun`` row and error
capture. The "city" is ``ReraProject.district``, because that is the unit the
HRERA register actually files against.

A city is its ``canonical_city`` form, the same identity ``micro_market`` stores
under. The register spells one district inconsistently, and both the aggregation
below and the ``(city, captured_on)`` uniqueness the model enforces key on the
city, so the filed spelling had to stop being the identity: ``Gurugram`` and
``gurugram`` were two cities, each holding a partial half of one place's numbers.

Every number here is an aggregate of rows already in this database. A reading
with no price points in the window writes ``None`` rather than 0, and the
sentiment then falls back to the only signal left — new registrations — with that
fallback stated in the code and in the snapshot itself.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import (
    MarketPulseSnapshot,
    ProjectPriceHistory,
    ReraComplaint,
    ReraProject,
)
from app.models.enums import MarketSentiment, ProjectPriceSource
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult
from app.services.data_hub.utils import canonical_city

logger = logging.getLogger(__name__)

#: Registrations and complaints counted in the trailing week.
RECENT_WINDOW_DAYS = 7

#: How far back the comparison price point is taken from.
PRICE_LOOKBACK_DAYS = 90

#: A move smaller than this, either way, is read as no direction.
SENTIMENT_THRESHOLD_PCT = Decimal("1")

#: Upper bound on cities per run, so one run cannot walk the whole register.
CITY_LIMIT = 200

VALUE_QUANTUM = Decimal("0.01")

# Natural key of a snapshot. Mirrors ``uq_market_pulse_snapshots_city_day``.
SNAPSHOT_INDEX_ELEMENTS = ["city", "captured_on"]

SNAPSHOT_UPDATE_FIELDS = (
    "sentiment",
    "avg_price_per_sqft",
    "price_change_90d_pct",
    "new_registrations",
    "new_complaints",
    "computed_at",
)


def mean_price(prices: Sequence[Decimal]) -> Decimal | None:
    """Mean of the given prices, two decimal places. ``None`` when there are none.

    An empty window is not a price of zero, so it must not be written as one.
    """
    values = [Decimal(price) for price in prices if price is not None]
    if not values:
        return None
    return (sum(values) / Decimal(len(values))).quantize(VALUE_QUANTUM, rounding=ROUND_HALF_UP)


def percent_change(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    """Percent change from ``previous`` to ``current``.

    ``None`` when either side is missing, or when the earlier side is zero —
    a percent change against zero is undefined, not infinite.
    """
    if current is None or previous is None or Decimal(previous) == 0:
        return None
    change = (Decimal(current) - Decimal(previous)) / Decimal(previous) * Decimal(100)
    return change.quantize(VALUE_QUANTUM, rounding=ROUND_HALF_UP)


def classify_sentiment(
    price_change_90d_pct: Decimal | None, new_registrations: int | None
) -> MarketSentiment:
    """Direction of the market from the price move, falling back to registrations.

    With comparable price points: above ``SENTIMENT_THRESHOLD_PCT`` is positive,
    below its negative is negative, anything between is neutral.

    With no comparable price points, registrations are the only signal left, and
    they only carry good news: filings in the window mean positive, a quiet window
    means neutral. A quiet window is not evidence of a falling market, so this
    fallback never reports negative.

    ``new_registrations`` is ``None`` when the city's projects carry no
    registration date to count, and then there is no signal at all: the reading is
    ``unknown`` rather than ``neutral``. That distinction is the whole point —
    ``neutral`` is published as "Steady", which a reader takes as a measured flat
    market, and reporting that from an absent date field would be a claim this
    code cannot support.
    """
    if price_change_90d_pct is not None:
        if price_change_90d_pct > SENTIMENT_THRESHOLD_PCT:
            return MarketSentiment.positive
        if price_change_90d_pct < -SENTIMENT_THRESHOLD_PCT:
            return MarketSentiment.negative
        return MarketSentiment.neutral
    if new_registrations is None:
        return MarketSentiment.unknown
    return MarketSentiment.positive if new_registrations > 0 else MarketSentiment.neutral


def compute_pulse(
    *,
    city: str,
    captured_on: date,
    latest_prices: Sequence[Decimal],
    prices_90d_ago: Sequence[Decimal],
    new_registrations: int | None,
    new_complaints: int | None,
    computed_at: datetime | None = None,
    paired_latest_prices: Sequence[Decimal] | None = None,
) -> dict[str, Any]:
    """One city's reading for one day, from plain values.

    ``avg_price_per_sqft`` is the mean of the most recent price point of each of
    the city's projects. ``price_change_90d_pct`` is the percent change from the
    mean of each project's most recent price point on or before ``captured_on``
    minus ``PRICE_LOOKBACK_DAYS``. Both are ``None`` when either side has no price
    points. When ``paired_latest_prices`` is given, the change compares it (the
    latest prices of exactly the projects in ``prices_90d_ago``) instead of every
    latest price, so both means cover one project set.

    ``new_registrations`` and ``new_complaints`` are ``None`` when the city has no
    source to count from — see ``_registrations`` and ``_complaints``. A ``None``
    is not a zero: it means the reading was not taken.
    """
    latest_mean = mean_price(latest_prices)
    earlier_mean = mean_price(prices_90d_ago)
    compared_mean = (
        mean_price(paired_latest_prices) if paired_latest_prices is not None else latest_mean
    )
    change = percent_change(compared_mean, earlier_mean)
    return {
        "city": city,
        "captured_on": captured_on,
        "sentiment": classify_sentiment(change, new_registrations),
        "avg_price_per_sqft": latest_mean,
        "price_change_90d_pct": change,
        "new_registrations": new_registrations,
        "new_complaints": new_complaints,
        "computed_at": computed_at or datetime.now(UTC),
    }


def _source_rank():
    """Order filed prices ahead of launch prices ahead of derived ones.

    Two sources can share a quarter (a project whose launch quarter is also its
    latest filing quarter), so the tie has to be broken on something stable.
    """
    return case(
        (ProjectPriceHistory.source == ProjectPriceSource.filing, 0),
        (ProjectPriceHistory.source == ProjectPriceSource.launch, 1),
        else_=2,
    )


class MarketPulseScraper(BaseScraper):
    """Write one ``MarketPulseSnapshot`` per city per day."""

    name = "market_pulse"
    requires_playwright = False

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {
                "status": "disabled",
                "run_id": None,
                "reason": "hrera_disabled_by_configuration",
            }
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _scrape(self) -> ScrapeResult:
        if not settings.HRERA_DATA_ENABLED:
            return ScrapeResult()
        result = ScrapeResult()
        coverage: dict[str, Any] = {
            "source": "rera_projects, rera_complaints, project_price_history",
            "cities_checked": 0,
            "cities_with_prices": 0,
            "records_parsed": 0,
            "status": "failed",
        }
        captured_on = datetime.now(UTC).date()
        try:
            from app.core.database import get_bg_session_factory

            session_factory = get_bg_session_factory()
            async with session_factory() as db:
                records = await self._aggregate(db, captured_on)
        except Exception as exc:
            logger.warning("Could not build the market pulse: %s", exc)
            result.errors.append(
                {
                    "stage": "aggregate",
                    "error_type": type(exc).__name__,
                    "message": "The market pulse could not be computed",
                }
            )
            result.source_coverage.append(coverage)
            return result

        coverage["cities_checked"] = len(records)
        coverage["cities_with_prices"] = sum(
            1 for record in records if record["avg_price_per_sqft"] is not None
        )
        coverage["records_parsed"] = len(records)
        result.records = records
        coverage["status"] = "partial" if result.errors else "success"
        # The register was read successfully; a city with no price points is
        # still a valid reading, not a failed scrape.
        result.successful_sources = 1
        result.source_coverage.append(coverage)
        return result

    async def _aggregate(self, db: AsyncSession, captured_on: date) -> list[dict[str, Any]]:
        """One reading per city, aggregated from the register's own rows.

        The caller owns the session: ``_scrape()`` opens a short-lived one, and a
        test can hand in its own.

        The filed districts are read as the register spells them, because that is
        what the SQL filters below have to match. Every dict keyed by a district
        then goes through ``canonical_city``, and the city list is deduped the same
        way, so two spellings of one district are one city holding both their
        numbers rather than two cities each holding half of them.
        """
        since = captured_on - timedelta(days=RECENT_WINDOW_DAYS)
        cutoff = captured_on - timedelta(days=PRICE_LOOKBACK_DAYS)
        filed_districts = await self._cities(db)
        if not filed_districts:
            return []
        cities = sorted({canonical_city(district) for district in filed_districts})
        registrations = await self._registrations(db, filed_districts, since, captured_on)
        complaints = await self._complaints(db, filed_districts, since, captured_on)
        latest = await self._latest_prices(db, filed_districts)
        earlier = await self._prices_as_of(db, filed_districts, cutoff)

        computed_at = datetime.now(UTC)
        records = []
        for city in cities:
            latest_by_project = latest.get(city, {})
            earlier_by_project = earlier.get(city, {})
            # The 90-day change compares one set of projects at both dates. A
            # project priced only now (launched inside the window) would move the
            # mean with no price change, so it counts in the average but not here.
            paired = sorted(set(latest_by_project) & set(earlier_by_project))
            records.append(
                compute_pulse(
                    city=city,
                    captured_on=captured_on,
                    latest_prices=list(latest_by_project.values()),
                    prices_90d_ago=[earlier_by_project[pid] for pid in paired],
                    paired_latest_prices=[latest_by_project[pid] for pid in paired],
                # Both maps carry an explicit ``None`` for a city they cannot
                # count, so a miss here means the map itself is short and the
                # reading is unknown rather than zero. Defaulting to ``0`` would
                # re-create the fabricated zero the counters exist to avoid.
                    new_registrations=registrations.get(city),
                    new_complaints=complaints.get(city),
                    computed_at=computed_at,
                )
            )
        return records

    async def _cities(self, db: AsyncSession) -> list[str]:
        """The districts the register files, as the register spells them.

        These are the SQL filter values, so they are returned verbatim: a district
        the register spells two ways must match its own rows under both spellings.
        ``_aggregate`` folds them to ``canonical_city``, which is the identity.
        """
        rows = (
            await db.execute(
                select(ReraProject.district)
                .where(ReraProject.district.isnot(None))
                .distinct()
                .order_by(ReraProject.district)
                .limit(CITY_LIMIT)
            )
        ).all()
        return [str(row[0]) for row in rows if row[0]]

    async def _registrations(
        self, db: AsyncSession, cities: Sequence[str], since: date, captured_on: date
    ) -> dict[str, int | None]:
        """Filings inside the window, per city, or ``None`` where uncountable.

        A count needs a date, and the Delhi register states no registration date:
        all 133 of its rows have ``registration_date`` NULL, while 14 of the 15
        Haryana rows carry one. Counting only the dated rows would report ``0`` for
        every Delhi city — including a Delhi city that filed this morning — so a
        city whose projects carry **no** date at all reports ``None`` instead. A
        city with at least one dated project reports its count, because a quiet
        window is then something the register actually stated.

        The same rule applies per city rather than globally, so adding dated rows
        for one district starts publishing its count without changing the others.

        Keys are ``canonical_city`` values, because that is what ``_aggregate``
        looks up by, and two spellings of one district must not become two entries.
        """
        cities_with_dates = {
            canonical_city(row[0])
            for row in (
                await db.execute(
                    select(ReraProject.district)
                    .where(
                        ReraProject.district.in_(cities),
                        ReraProject.registration_date.isnot(None),
                    )
                    .distinct()
                )
            ).all()
            if row[0]
        }
        rows = (
            await db.execute(
                select(ReraProject.district, func.count(ReraProject.id))
                .where(
                    ReraProject.district.in_(cities),
                    ReraProject.registration_date.isnot(None),
                    ReraProject.registration_date >= since,
                    ReraProject.registration_date <= captured_on,
                )
                .group_by(ReraProject.district)
            )
        ).all()
        counted = _sum_by_city(rows)
        result: dict[str, int | None] = {}
        for district in cities:
            city = canonical_city(district)
            if city not in result:
                result[city] = counted.get(city, 0) if city in cities_with_dates else None
        return result

    async def _complaints(
        self, db: AsyncSession, cities: Sequence[str], since: date, captured_on: date
    ) -> dict[str, int | None]:
        """Complaints inside the window, per city, or ``None`` where never collected for that city.

        The complaints scraper reads HRERA through Playwright, and ``rera_complaints``
        holds no rows at all: the count is zero because nothing has ever been
        collected, not because nothing was filed. Publishing ``0`` would tell a
        reader the authority received no complaint about the city in the window,
        which is a stronger claim than the empty table supports. ``None`` until the
        table has a row to count, after which the count is real.
        """
        # Coverage is per city: a city counts only when at least one complaint was
        # ever collected for its projects. The complaints scraper reads one
        # district at a time, so a row for Gurugram says nothing about Faridabad.
        covered = {
            canonical_city(row[0])
            for row in (
                await db.execute(
                    select(ReraProject.district)
                    .join(ReraComplaint, ReraComplaint.rera_number == ReraProject.rera_number)
                    .where(ReraProject.district.in_(cities))
                    .distinct()
                )
            ).all()
            if row[0]
        }
        counted: dict[str, int] = {}
        if covered:
            counted = _sum_by_city(
                (
                    await db.execute(
                        select(ReraProject.district, func.count(ReraComplaint.id))
                        .join(ReraProject, ReraProject.rera_number == ReraComplaint.rera_number)
                        .where(
                            ReraProject.district.in_(cities),
                            ReraComplaint.order_date.isnot(None),
                            ReraComplaint.order_date >= since,
                            ReraComplaint.order_date <= captured_on,
                        )
                        .group_by(ReraProject.district)
                    )
                ).all()
            )
        result: dict[str, int | None] = {}
        for district in cities:
            city = canonical_city(district)
            if city not in result:
                result[city] = counted.get(city, 0) if city in covered else None
        return result

    async def _latest_prices(
        self, db: AsyncSession, cities: Sequence[str]
    ) -> dict[str, dict[int, Decimal]]:
        rows = (
            await db.execute(
                select(
                    ReraProject.district,
                    ProjectPriceHistory.rera_project_id,
                    ProjectPriceHistory.price_per_sqft,
                )
                .join(ProjectPriceHistory, ProjectPriceHistory.rera_project_id == ReraProject.id)
                .where(
                    ReraProject.district.in_(cities),
                    ProjectPriceHistory.price_per_sqft.isnot(None),
                    ProjectPriceHistory.period_start.isnot(None),
                )
                .distinct(ReraProject.district, ProjectPriceHistory.rera_project_id)
                .order_by(
                    ReraProject.district,
                    ProjectPriceHistory.rera_project_id,
                    ProjectPriceHistory.period_start.desc(),
                    _source_rank(),
                    ProjectPriceHistory.recorded_at.desc(),
                )
            )
        ).all()
        return _group_prices(rows)

    async def _prices_as_of(
        self, db: AsyncSession, cities: Sequence[str], cutoff: date
    ) -> dict[str, dict[int, Decimal]]:
        """Each project's latest price in the lookback period before ``cutoff``.

        A point older than one more lookback period is not a 90-day-ago price, so
        it is left out rather than compared as one.
        """
        rows = (
            await db.execute(
                select(
                    ReraProject.district,
                    ProjectPriceHistory.rera_project_id,
                    ProjectPriceHistory.price_per_sqft,
                )
                .join(ProjectPriceHistory, ProjectPriceHistory.rera_project_id == ReraProject.id)
                .where(
                    ReraProject.district.in_(cities),
                    ProjectPriceHistory.price_per_sqft.isnot(None),
                    ProjectPriceHistory.period_start.isnot(None),
                    ProjectPriceHistory.period_start <= cutoff,
                    ProjectPriceHistory.period_start
                    > cutoff - timedelta(days=PRICE_LOOKBACK_DAYS),
                )
                .distinct(ReraProject.district, ProjectPriceHistory.rera_project_id)
                .order_by(
                    ReraProject.district,
                    ProjectPriceHistory.rera_project_id,
                    ProjectPriceHistory.period_start.desc(),
                    _source_rank(),
                    ProjectPriceHistory.recorded_at.desc(),
                )
            )
        ).all()
        return _group_prices(rows)

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
                    if hasattr(MarketPulseSnapshot, key) and key not in ("id", "created_at")
                }
                async with db.begin_nested():
                    statement = pg_insert(MarketPulseSnapshot).values(**values)
                    await db.execute(
                        statement.on_conflict_do_update(
                            index_elements=SNAPSHOT_INDEX_ELEMENTS,
                            set_={
                                field: getattr(statement.excluded, field)
                                for field in SNAPSHOT_UPDATE_FIELDS
                            },
                        )
                    )
                upserted += 1
                record["_upsert_succeeded"] = True
            except Exception as exc:
                logger.warning(
                    "Failed to write market pulse for %s on %s: %s",
                    record.get("city"),
                    record.get("captured_on"),
                    exc,
                )
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}


def _sum_by_city(rows: Sequence[Any]) -> dict[str, int]:
    """Total a per-district count under the city identity.

    Two spellings of one district are one city, so their counts add up rather than
    sitting in two entries — the same reason ``_group_prices`` keys on the city.

    Only districts with at least one counted row appear in the result. A district
    that is absent was not counted, which callers must treat as ``None`` rather
    than ``0``: see ``_registrations`` and ``_complaints``.
    """
    grouped: dict[str, int] = {}
    for district, count in rows:
        if district is None:
            continue
        city = canonical_city(district)
        grouped[city] = grouped.get(city, 0) + int(count or 0)
    return grouped


def _group_prices(rows: Sequence[Any]) -> dict[str, dict[int, Decimal]]:
    """Group one-price-per-project rows into ``{city: {project_id: price}}``."""
    grouped: dict[str, dict[int, Decimal]] = {}
    for district, project_id, price in rows:
        if district is None or price is None:
            continue
        grouped.setdefault(canonical_city(district), {})[project_id] = Decimal(price)
    return grouped
