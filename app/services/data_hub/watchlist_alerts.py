"""Watchlist change alerts.

On each run this scraper reads every ``ProjectWatchlist`` row and asks whether the
project moved since the user was last told about it. A change is dispatched as a
typed notification; a run that finds no change sends nothing. That is the whole
point of the service, so every check is written to be silent unless the value
actually differs.

What "since the user was last told" means here
----------------------------------------------
``ProjectWatchlist`` has no per-alert "last notified" column, so the baseline is
the watch's own ``updated_at``:

* price — the newest ``ProjectPriceHistory`` point (source ``filing`` or
  ``launch``) recorded at or before ``updated_at`` is the value the user was last
  told; the newest point overall is the current value.
* possession — the newest ``DataHubEntityRevision`` created at or before
  ``updated_at`` carries the ``possession_date`` the register showed then; the
  current ``ReraProject.possession_date`` (or, failing that,
  ``ReraProjectProfile.proposed_completion_date``) is compared against it.
* new filing — the newest ``ReraProjectDocument.uploaded_on`` compared with the
  ``updated_at`` date.
* stage — **not implemented**. Revision snapshots store only the RERA fields
  (``RERA_FIELDS``), which have no stage and no construction-start date, so the
  revision history cannot reconstruct a previous stage. The pure helper
  ``stage_changed`` exists and is tested, but the scraper never supplies a stage
  baseline, so this check can never fire. See the module report.

After every alert for a watch dispatches, the watch's ``updated_at`` is advanced
so the same change is not re-sent on the next run.

Alert switches
--------------
``ProjectWatchlist.alert_prefs`` is opt-in: an absent key means the user wants the
alert, and only a key explicitly set to ``False`` turns that kind off. The keys are
the notification type keys (``watchlist_price_change``, ``watchlist_stage_change``,
``watchlist_possession_change``, ``watchlist_new_filing``).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import (
    DataHubEntityRevision,
    ProjectPriceHistory,
    ProjectWatchlist,
    ReraProject,
    ReraProjectDocument,
    ReraProjectProfile,
)
from app.models.enums import ProjectPriceSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.notification_dispatcher import dispatch_notification_to_user

logger = logging.getLogger(__name__)

# Change kind -> registered notification type key.
CHANGE_TYPE_KEYS: dict[str, str] = {
    "price": "watchlist_price_change",
    "stage": "watchlist_stage_change",
    "possession": "watchlist_possession_change",
    "filing": "watchlist_new_filing",
}

# Only the two official figures count as a price the user was told. ``derived``
# points are computed from them and would double-count the same move.
_PRICE_SOURCES = (ProjectPriceSource.filing, ProjectPriceSource.launch)

_ALERT_TITLES = {
    "price": "Price changed for a project you watch",
    "stage": "Construction stage changed for a project you watch",
    "possession": "Possession date changed for a project you watch",
    "filing": "New document filed for a project you watch",
}

_ALERT_BODIES = {
    "price": "the price per sq ft in the latest filing differs from the last figure you were shown.",
    "stage": "the construction stage in the latest filing differs from the last stage you were shown.",
    "possession": "the possession date in the latest filing differs from the last date you were shown.",
    "filing": "a new document was uploaded to the project filing.",
}


# ---------------------------------------------------------------------------
# Pure change detection
# ---------------------------------------------------------------------------


def _normalize_value(value: Any) -> Any:
    """Reduce a value to a comparable form.

    Numbers become ``Decimal`` (so ``100`` and ``Decimal('100.00')`` compare
    equal), enums become their value, and date-like strings become ``date`` (a
    revision snapshot stores dates as ISO strings while the model stores ``date``).
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, (int, float)):
        return Decimal(str(value)).normalize()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            try:
                return Decimal(value.strip()).normalize()
            except InvalidOperation:
                return value.strip()
    return value


def values_differ(previous: Any, current: Any) -> bool:
    """True only when both sides are present and differ.

    A missing side cannot evidence a change, so it returns ``False``. That keeps
    the service silent when there is no baseline to compare against.
    """
    if previous is None or current is None:
        return False
    return bool(_normalize_value(previous) != _normalize_value(current))


def price_changed(previous_price_per_sqft: Any, current_price_per_sqft: Any) -> bool:
    """True when the current price per sq ft differs from the previous one."""
    return values_differ(previous_price_per_sqft, current_price_per_sqft)


def stage_changed(previous_stage: Any, current_stage: Any) -> bool:
    """True when the current project stage differs from the previous one."""
    return values_differ(previous_stage, current_stage)


def possession_changed(previous_possession_date: Any, current_possession_date: Any) -> bool:
    """True when the current possession/completion date differs from the previous one."""
    return values_differ(previous_possession_date, current_possession_date)


def filing_is_new(previous_uploaded_on: Any, latest_uploaded_on: Any) -> bool:
    """True when a document was uploaded after the previous check.

    This is an ordering test, not an equality test: a filing that is newer than
    the baseline is a change, and a filing on or before it is not.
    """
    if previous_uploaded_on is None or latest_uploaded_on is None:
        return False
    return bool(_normalize_value(latest_uploaded_on) > _normalize_value(previous_uploaded_on))


def alert_pref_enabled(alert_prefs: dict | None, type_key: str) -> bool:
    """Opt-in default: a missing key is on, only an explicit ``False`` is off."""
    if not alert_prefs:
        return True
    return alert_prefs.get(type_key) is not False


def detect_change_kinds(
    *,
    previous_price_per_sqft: Any = None,
    current_price_per_sqft: Any = None,
    previous_stage: Any = None,
    current_stage: Any = None,
    previous_possession_date: Any = None,
    current_possession_date: Any = None,
    previous_filing_uploaded_on: Any = None,
    latest_filing_uploaded_on: Any = None,
    alert_prefs: dict | None = None,
) -> list[str]:
    """Return the change kinds to notify, in a stable order, honouring opt-outs.

    Pure: every input is a plain before/after value, so this is the single place
    the change rules live and the place the "no change produces no dispatch" case
    is decided. An empty list means nothing is sent.
    """
    kinds: list[str] = []
    if price_changed(previous_price_per_sqft, current_price_per_sqft):
        kinds.append("price")
    if stage_changed(previous_stage, current_stage):
        kinds.append("stage")
    if possession_changed(previous_possession_date, current_possession_date):
        kinds.append("possession")
    if filing_is_new(previous_filing_uploaded_on, latest_filing_uploaded_on):
        kinds.append("filing")
    return [kind for kind in kinds if alert_pref_enabled(alert_prefs, CHANGE_TYPE_KEYS[kind])]


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


class WatchlistAlertScraper(BaseScraper):
    """Dispatch an alert when a watched project actually changed."""

    name = "watchlist_alerts"
    requires_playwright = False

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {
                "status": "disabled",
                "run_id": None,
                "reason": "hrera_disabled_by_configuration",
            }
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _scrape(self) -> list[dict]:
        """Read the watchlist and build one record per genuine change.

        Runs in its own short-lived session so the database connection is not held
        while the caller works, mirroring ``AlertMatcherService``.
        """
        if not settings.HRERA_DATA_ENABLED:
            return []
        from app.core.database import get_bg_session_factory

        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            return await self._collect_changes(db)

    async def _collect_changes(self, db: AsyncSession) -> list[dict]:
        result = await db.execute(select(ProjectWatchlist))
        records: list[dict] = []
        for watch in result.scalars().all():
            records.extend(await self._changes_for_watch(db, watch))
        return records

    async def _changes_for_watch(self, db: AsyncSession, watch: ProjectWatchlist) -> list[dict]:
        baseline = watch.updated_at
        if baseline is None:
            return []
        project = await db.get(ReraProject, watch.rera_project_id)
        if project is None:
            return []

        previous_price = await self._price_point(db, project.id, recorded_at_or_before=baseline)
        current_price = await self._price_point(db, project.id)
        previous_possession = await self._possession_baseline(db, project.id, baseline)
        current_possession = await self._current_possession(db, project)
        latest_filing = await self._latest_filing_uploaded_on(db, project.id)

        kinds = detect_change_kinds(
            previous_price_per_sqft=previous_price.price_per_sqft if previous_price else None,
            current_price_per_sqft=current_price.price_per_sqft if current_price else None,
            # No stage baseline exists in the revision history (see module docstring),
            # so stage is never supplied a before value and can never fire.
            previous_stage=None,
            current_stage=None,
            previous_possession_date=previous_possession,
            current_possession_date=current_possession,
            previous_filing_uploaded_on=baseline.date(),
            latest_filing_uploaded_on=latest_filing,
            alert_prefs=watch.alert_prefs,
        )
        return [self._build_record(watch, project, kind) for kind in kinds]

    async def _price_point(
        self,
        db: AsyncSession,
        project_id: int,
        *,
        recorded_at_or_before: datetime | None = None,
    ) -> ProjectPriceHistory | None:
        stmt = select(ProjectPriceHistory).where(
            ProjectPriceHistory.rera_project_id == project_id,
            ProjectPriceHistory.source.in_(_PRICE_SOURCES),
        )
        if recorded_at_or_before is not None:
            stmt = stmt.where(ProjectPriceHistory.recorded_at <= recorded_at_or_before)
        stmt = stmt.order_by(ProjectPriceHistory.recorded_at.desc()).limit(1)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def _possession_baseline(
        self, db: AsyncSession, project_id: int, baseline: datetime
    ) -> Any:
        """The possession date the revision history showed at the baseline."""
        revision = (
            await db.execute(
                select(DataHubEntityRevision)
                .where(
                    DataHubEntityRevision.rera_project_id == project_id,
                    DataHubEntityRevision.created_at <= baseline,
                )
                .order_by(DataHubEntityRevision.revision_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if revision is None:
            return None
        return (revision.normalized_snapshot or {}).get("possession_date")

    async def _current_possession(self, db: AsyncSession, project: ReraProject) -> Any:
        if project.possession_date is not None:
            return project.possession_date
        profile = (
            await db.execute(
                select(ReraProjectProfile).where(ReraProjectProfile.rera_project_id == project.id)
            )
        ).scalar_one_or_none()
        if profile is None:
            return None
        return profile.proposed_completion_date

    async def _latest_filing_uploaded_on(self, db: AsyncSession, project_id: int) -> date | None:
        return (
            await db.execute(
                select(func.max(ReraProjectDocument.uploaded_on)).where(
                    ReraProjectDocument.rera_project_id == project_id
                )
            )
        ).scalar_one_or_none()

    def _build_record(self, watch: ProjectWatchlist, project: ReraProject, kind: str) -> dict:
        return {
            "watch_id": watch.id,
            "user_id": watch.user_id,
            "project_id": project.id,
            "kind": kind,
            "type_key": CHANGE_TYPE_KEYS[kind],
            "title": _ALERT_TITLES[kind],
            "body": f"{project.project_name}: {_ALERT_BODIES[kind]}",
            "data": {
                "kind": kind,
                "project_id": str(project.id),
                "slug": project.slug or "",
            },
            "deep_link": f"/data-hub/projects/{project.slug}" if project.slug else None,
        }

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        """Dispatch one notification per record and advance the watch baseline.

        A watch's ``updated_at`` moves only when every alert for that watch sent,
        so a failed dispatch is retried on the next run. One user's failure never
        aborts the batch.
        """
        if not settings.HRERA_DATA_ENABLED:
            return {"found": 0, "upserted": 0, "failed": 0}

        found = len(records)
        dispatched = 0
        failed = 0
        by_watch: dict[int, list[dict]] = {}
        for record in records:
            by_watch.setdefault(record["watch_id"], []).append(record)

        for watch_id, watch_records in by_watch.items():
            watch_ok = True
            for record in watch_records:
                try:
                    await self._dispatch_notification(db, record)
                    dispatched += 1
                except Exception as e:
                    watch_ok = False
                    failed += 1
                    logger.warning(
                        "Failed to dispatch watchlist alert watch=%s kind=%s: %s",
                        watch_id,
                        record.get("kind"),
                        e,
                    )
            if watch_ok:
                watch = await db.get(ProjectWatchlist, watch_id)
                if watch is not None:
                    watch.updated_at = datetime.now(UTC)

        await db.commit()
        return {"found": found, "upserted": dispatched, "failed": failed}

    async def _dispatch_notification(self, db: AsyncSession, record: dict) -> None:
        """Send one watchlist alert. An error result raises so the caller counts it failed."""
        result = await dispatch_notification_to_user(
            db,
            user_db_id=record["user_id"],
            type_key=record["type_key"],
            title=record["title"],
            body=record["body"],
            data=record["data"],
            deep_link=record["deep_link"],
        )
        if result.get("error"):
            raise RuntimeError(f"notification dispatch failed: {result['error']}")
