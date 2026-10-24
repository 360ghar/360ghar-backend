"""Watchlist change alerts.

On each run this scraper reads every ``ProjectWatchlist`` row and asks whether the
project moved since the user was last told about it. A change is dispatched as a
typed notification; a run that finds no change sends nothing. That is the whole
point of the service, so every check is written to be silent unless the value
actually differs.

What "since the user was last told" means here
----------------------------------------------
Each watch stores ``alert_baseline``: the values the user was last told (or saw
when they started watching). Only this service writes it, so editing a watch's
notes or switches never moves it. A run compares the current values with it:

* price — the newest ``ProjectPriceHistory`` point (source ``filing`` or
  ``launch``). A same-quarter overwrite is still a change, because the stored
  value is compared, not a recorded-at cutoff.
* stage — ``ReraProjectProfile.stage``.
* possession — ``ReraProject.possession_date``, or failing that
  ``ReraProjectProfile.proposed_completion_date``.
* new filing — a document key (upload date plus description) that the baseline
  has not seen. Same-day filings are separate keys, so none is hidden.

A watch with no baseline gets one from the current values and sends nothing.
After a run, each field moves to the value that was read, except a field whose
alert failed to dispatch: it keeps the old value so the alert is retried. The
values stored are the values read, not the values at commit time, so a write that
lands between the read and the commit is reported on the next run.

Alert switches
--------------
``ProjectWatchlist.alert_prefs`` is opt-in: an absent key means the user wants the
alert, and only a key explicitly set to ``False`` turns that kind off. The keys are
the notification type keys (``watchlist_price_change``, ``watchlist_stage_change``,
``watchlist_possession_change``, ``watchlist_new_filing``).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import (
    ProjectPriceHistory,
    ProjectWatchlist,
    ReraProject,
    ReraProjectDocument,
    ReraProjectProfile,
)
from app.models.enums import ProjectPriceSource
from app.services.data_hub.base_scraper import BaseScraper
from app.services.notification_dispatcher import dispatch_failure, dispatch_notification_to_user

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
    new_filing: bool = False,
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
    if new_filing or filing_is_new(previous_filing_uploaded_on, latest_filing_uploaded_on):
        kinds.append("filing")
    return [kind for kind in kinds if alert_pref_enabled(alert_prefs, CHANGE_TYPE_KEYS[kind])]


# Record kind that carries a watch's freshly read values, not an alert.
BASELINE_KIND = "baseline"

# Baseline field each change kind owns.
_BASELINE_FIELDS: dict[str, tuple[str, ...]] = {
    "price": ("price_per_sqft",),
    "stage": ("stage",),
    "possession": ("possession_date",),
    "filing": ("documents",),
}


def _json_value(value: Any) -> Any:
    """A JSON-safe form of a snapshot value (dates and decimals as strings)."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def document_key(uploaded_on: date | None, description: str) -> str:
    """A stable key for one filed document. Rows are replaced on refresh, so ids are not stable."""
    return f"{uploaded_on.isoformat() if uploaded_on else ''}|{description.strip()}"


def merge_baseline(previous: dict | None, snapshot: dict, failed_kinds: set[str]) -> dict:
    """The new baseline: ``snapshot``, with two exceptions that keep ``previous``.

    * A field whose alert failed keeps its old value, so the alert is retried.
    * A field the snapshot has no value for (``None``, or no documents) keeps its
      old value. A missing reading is not a new value: replacing the last known
      value with ``None`` would hide the next real change, because a comparison
      with a missing side never fires.
    """
    merged = dict(snapshot)
    if previous is None:
        return merged
    for field, value in snapshot.items():
        if (value is None or value == []) and previous.get(field) not in (None, []):
            merged[field] = previous[field]
    for kind in failed_kinds:
        for field in _BASELINE_FIELDS[kind]:
            if field in previous:
                merged[field] = previous[field]
            else:
                merged.pop(field, None)
    return merged


async def current_alert_snapshot(db: AsyncSession, project: ReraProject) -> dict:
    """The values a watch alert compares, as stored in ``ProjectWatchlist.alert_baseline``."""
    price = (
        await db.execute(
            select(ProjectPriceHistory.price_per_sqft)
            .where(
                ProjectPriceHistory.rera_project_id == project.id,
                ProjectPriceHistory.source.in_(_PRICE_SOURCES),
            )
            .order_by(ProjectPriceHistory.recorded_at.desc(), ProjectPriceHistory.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    profile = (
        await db.execute(
            select(ReraProjectProfile).where(ReraProjectProfile.rera_project_id == project.id)
        )
    ).scalar_one_or_none()
    possession = project.possession_date
    if possession is None and profile is not None:
        possession = profile.proposed_completion_date
    documents = (
        await db.execute(
            select(ReraProjectDocument.uploaded_on, ReraProjectDocument.description).where(
                ReraProjectDocument.rera_project_id == project.id
            )
        )
    ).all()
    return {
        "price_per_sqft": _json_value(price),
        "stage": _json_value(profile.stage if profile is not None else None),
        "possession_date": _json_value(possession),
        "documents": sorted({document_key(on, desc) for on, desc in documents}),
    }


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
        """One record per change to dispatch, plus one ``baseline`` record per watch.

        The ``baseline`` record carries the values read on this run. ``_upsert``
        writes it back after the watch's alerts dispatch.
        """
        result = await db.execute(select(ProjectWatchlist))
        records: list[dict] = []
        for watch in result.scalars().all():
            records.extend(await self._changes_for_watch(db, watch))
        return records

    async def _changes_for_watch(self, db: AsyncSession, watch: ProjectWatchlist) -> list[dict]:
        project = await db.get(ReraProject, watch.rera_project_id)
        if project is None:
            return []
        current = await current_alert_snapshot(db, project)
        baseline_record = {"watch_id": watch.id, "kind": BASELINE_KIND, "snapshot": current}
        previous = watch.alert_baseline
        if previous is None:
            # First sight of this watch: record what the user sees now, send nothing.
            return [baseline_record]

        seen = set(previous.get("documents") or [])
        kinds = detect_change_kinds(
            previous_price_per_sqft=previous.get("price_per_sqft"),
            current_price_per_sqft=current["price_per_sqft"],
            previous_stage=previous.get("stage"),
            current_stage=current["stage"],
            previous_possession_date=previous.get("possession_date"),
            current_possession_date=current["possession_date"],
            # An empty baseline list is a real baseline ("no documents yet").
            new_filing="documents" in previous and bool(set(current["documents"]) - seen),
            alert_prefs=watch.alert_prefs,
        )
        return [self._build_record(watch, project, kind) for kind in kinds] + [baseline_record]

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
        """Dispatch one notification per change and move each watch's baseline.

        Each baseline field moves to the value read on this run, except the field
        of an alert that failed: it keeps the old value so that alert is retried
        and the alerts that did send are not sent again. Each watch commits on its
        own, so a later failure cannot undo an earlier watch's progress. One
        user's failure never aborts the batch.
        """
        if not settings.HRERA_DATA_ENABLED:
            return {"found": 0, "upserted": 0, "failed": 0}

        by_watch: dict[int, list[dict]] = {}
        for record in records:
            by_watch.setdefault(record["watch_id"], []).append(record)

        found = dispatched = failed = 0
        for watch_id, watch_records in by_watch.items():
            snapshot: dict | None = None
            failed_kinds: set[str] = set()
            for record in watch_records:
                if record["kind"] == BASELINE_KIND:
                    snapshot = record["snapshot"]
                    continue
                found += 1
                try:
                    await self._dispatch_notification(db, record)
                    dispatched += 1
                except Exception as e:
                    failed_kinds.add(record["kind"])
                    failed += 1
                    logger.warning(
                        "Failed to dispatch watchlist alert watch=%s kind=%s: %s",
                        watch_id,
                        record.get("kind"),
                        e,
                    )
            if snapshot is None:
                continue
            watch = await db.get(ProjectWatchlist, watch_id)
            if watch is None:
                continue
            watch.alert_baseline = merge_baseline(watch.alert_baseline, snapshot, failed_kinds)
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
        failure = dispatch_failure(result)
        if failure:
            raise RuntimeError(f"notification dispatch failed: {failure}")
