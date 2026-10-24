"""Developer reconciliation and the five-pillar trust score.

Two jobs, one run:

(a) **Reconcile** — every distinct non-null ``ReraProject.developer_name`` gets a
    ``Developer`` row keyed on its slug, so a promoter has one identity shared by
    every project it filed.
(b) **Score** — each developer gets a ``DeveloperScore`` row whose five pillars
    are computed only from data already in this database. No pillar is estimated
    from a web page, and no pillar falls back to a default number. When the
    filings say nothing about a pillar, the pillar is ``None`` and it drops out
    of the weighted mean; when every pillar is ``None`` no score row is written
    at all, because a zero is a claim and no data is not a claim.

Pillar formulas, inputs, weights and ``None`` conditions are documented on the
pure helpers below and pinned by ``tests/unit/services/test_developer_dossier.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import (
    Developer,
    DeveloperScore,
    ReraComplaint,
    ReraProject,
    ReraProjectCost,
    ReraProjectProfile,
    ReraQuarterlyExpenditure,
    ReraStatutoryApproval,
)
from app.models.enums import ProjectStage
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

#: Upper bound on the developers examined in one run. Developers with no score
#: row are visited first, so repeated runs converge on full coverage.
DEFAULT_BATCH = 500

SCORE_QUANTUM = Decimal("0.01")
PILLAR_FLOOR = Decimal("0")
PILLAR_CEILING = Decimal("100")

#: Pillar weights. They sum to 1.00, and a pillar that is ``None`` drops out of
#: both the numerator and the denominator of the weighted mean.
DEVELOPER_PILLAR_WEIGHTS: dict[str, Decimal] = {
    "delivery": Decimal("0.30"),
    "regulatory": Decimal("0.25"),
    "complaints": Decimal("0.20"),
    "financials": Decimal("0.15"),
    "market_reception": Decimal("0.10"),
}

#: Regulatory: a project whose filed completion date has passed without the
#: register showing it completed costs this many points off the pillar.
EXPIRED_PROJECT_PENALTY = Decimal("15")

#: Market reception: a flat launch-to-filing price scores the midpoint, and each
#: percentage point of movement is worth this much. +20% -> 100, -20% -> 0.
PRICE_MOVE_MIDPOINT = Decimal("50")
PRICE_MOVE_SCORE_PER_PCT = Decimal("2.5")

_COMPLETED_STAGE = ProjectStage.completed.value


def clamp_pillar(value: Decimal) -> Decimal:
    """Hold a pillar inside 0-100, two decimal places."""
    bounded = min(max(value, PILLAR_FLOOR), PILLAR_CEILING)
    return bounded.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def developer_slug(developer_name: str) -> str:
    """Stable identity for a promoter name, shared by every project it filed."""
    return generate_slug(developer_name)


def compute_delivery(stage_counts: Mapping[str, int]) -> Decimal | None:
    """Delivery pillar — share of the developer's staged projects that completed.

    Inputs: ``stage_counts`` maps a ``ProjectStage`` value to how many of the
    developer's projects carry it. Score is ``100 * completed / staged``.

    ``None`` when no project of this developer carries a stage, because then
    there is no filed lifecycle to divide by. A developer whose filings do place
    their projects scores 0 when none has completed — the register did state the
    stages, and every one of them is unfinished.
    """
    staged = sum(count for count in stage_counts.values() if count and count > 0)
    if staged <= 0:
        return None
    completed = stage_counts.get(_COMPLETED_STAGE, 0) or 0
    return clamp_pillar(Decimal(completed) / Decimal(staged) * PILLAR_CEILING)


def count_stages(stage_counts: Mapping[str, int]) -> tuple[int, int]:
    """``(delivered, under_construction)`` from the same stage counts.

    ``under_construction`` here means every staged project that is not completed,
    which covers ``pre_launch``, ``under_construction`` and ``near_possession``.
    Projects with no stage are counted in neither column.
    """
    delivered = stage_counts.get(_COMPLETED_STAGE, 0) or 0
    staged = sum(count for count in stage_counts.values() if count and count > 0)
    return delivered, staged - delivered


def compute_regulatory(projects: Sequence[Mapping[str, Any]]) -> Decimal | None:
    """Regulatory pillar — statutory-approval completeness, less expiry penalties.

    Each project mapping carries ``has_statutory_row``, ``plan_approvals_obtained``,
    ``plan_approvals_declared``, ``has_loi``, ``has_licence`` and
    ``expired_without_completion``.

    Per project with a statutory row, the score is the mean of the components the
    form actually declares: the share of plan approvals obtained, 1/0 for a
    recorded letter of intent, and 1/0 for a recorded licence. Blank LOI and
    licence fields score 0 — the form was read and it states nothing there. Then
    ``EXPIRED_PROJECT_PENALTY`` is subtracted for every project whose filed
    completion date has passed while the register still shows it live.

    ``None`` when no project of this developer has a statutory row, because there
    is no form to grade. A project without a row is excluded from the mean rather
    than counted as a failure.
    """
    scored = [project for project in projects if project.get("has_statutory_row")]
    if not scored:
        return None

    per_project: list[Decimal] = []
    for project in scored:
        components: list[Decimal] = []
        declared = int(project.get("plan_approvals_declared") or 0)
        if declared > 0:
            obtained = int(project.get("plan_approvals_obtained") or 0)
            components.append(
                Decimal(min(max(obtained, 0), declared)) / Decimal(declared)
            )
        components.append(Decimal(1) if project.get("has_loi") else Decimal(0))
        components.append(Decimal(1) if project.get("has_licence") else Decimal(0))
        per_project.append(sum(components) / Decimal(len(components)))

    base = sum(per_project) / Decimal(len(per_project)) * PILLAR_CEILING
    expired = sum(1 for project in projects if project.get("expired_without_completion"))
    return clamp_pillar(base - EXPIRED_PROJECT_PENALTY * Decimal(expired))


def compute_complaints(*, complaint_count: int, project_count: int) -> Decimal | None:
    """Complaints pillar — complaints filed against the developer, per project.

    Score is ``100 / (1 + complaints / projects)``: a smooth decay, so more
    complaints per project always lowers the score and the score is never
    truncated at an arbitrary floor. No complaints scores 100.

    The denominator is the developer's filed project count, or 1 when the
    developer has complaints but no project in the register — otherwise the
    complaints would vanish from the average. ``None`` only when the developer
    has neither projects nor complaints, so there is nothing to normalise.
    """
    if project_count <= 0 and complaint_count <= 0:
        return None
    denominator = Decimal(max(project_count, 1))
    ratio = Decimal(max(complaint_count, 0)) / denominator
    return clamp_pillar(PILLAR_CEILING / (Decimal(1) + ratio))


def compute_financials(projects: Sequence[Mapping[str, Any]]) -> Decimal | None:
    """Financials pillar — expenditure incurred against filed project cost.

    Each project mapping carries ``total_cost`` and ``expenditure_incurred`` (the
    sum of that project's REP-I quarterly expenditure rows). The score is the
    mean of ``100 * incurred / total`` over the projects where the filing supports
    both numbers. A ratio above 1 is read as a filing anomaly and held at 1.

    ``None`` when no project has both a positive filed cost and a filed
    expenditure figure — a cost with no spending figure is not progress.
    """
    ratios: list[Decimal] = []
    for project in projects:
        total = project.get("total_cost")
        incurred = project.get("expenditure_incurred")
        if total is None or incurred is None or Decimal(total) <= 0:
            continue
        ratio = Decimal(incurred) / Decimal(total)
        ratios.append(min(max(ratio, PILLAR_FLOOR), Decimal(1)))
    if not ratios:
        return None
    return clamp_pillar(sum(ratios) / Decimal(len(ratios)) * PILLAR_CEILING)


def compute_market_reception(projects: Sequence[Mapping[str, Any]]) -> Decimal | None:
    """Market reception pillar — price movement and filed bookings.

    Each project mapping carries ``launch_price_per_sqft``,
    ``current_price_per_sqft``, ``units_booked`` and ``total_units``.

    Two components, both 0-100, averaged over every component the filings support:

    * price movement: ``50 + 2.5 * percent_change`` between the filed launch and
      filing prices, clamped to 0-100;
    * bookings: ``100 * units_booked / total_units`` where both are filed.

    ``None`` when neither component exists for any of the developer's projects.
    """
    components: list[Decimal] = []
    for project in projects:
        launch = project.get("launch_price_per_sqft")
        current = project.get("current_price_per_sqft")
        if launch is not None and current is not None and Decimal(launch) > 0:
            change_pct = (Decimal(current) - Decimal(launch)) / Decimal(launch) * PILLAR_CEILING
            components.append(
                clamp_pillar(PRICE_MOVE_MIDPOINT + change_pct * PRICE_MOVE_SCORE_PER_PCT)
            )
        booked = project.get("units_booked")
        total = project.get("total_units")
        if booked is not None and total is not None and Decimal(total) > 0:
            share = Decimal(max(booked, 0)) / Decimal(total) * PILLAR_CEILING
            components.append(clamp_pillar(share))
    if not components:
        return None
    return clamp_pillar(sum(components) / Decimal(len(components)))


def compute_pillars(
    *,
    stage_counts: Mapping[str, int],
    regulatory_projects: Sequence[Mapping[str, Any]],
    complaint_count: int,
    project_count: int,
    financial_projects: Sequence[Mapping[str, Any]],
    market_projects: Sequence[Mapping[str, Any]],
) -> dict[str, Decimal | None]:
    """All five pillars for one developer, each ``None`` when its data is absent."""
    return {
        "delivery": compute_delivery(stage_counts),
        "regulatory": compute_regulatory(regulatory_projects),
        "complaints": compute_complaints(
            complaint_count=complaint_count, project_count=project_count
        ),
        "financials": compute_financials(financial_projects),
        "market_reception": compute_market_reception(market_projects),
    }


def compute_total_score(pillars: Mapping[str, Decimal | None]) -> Decimal | None:
    """Weighted mean of the non-null pillars, renormalised over the weights used.

    ``None`` when every pillar is ``None``. Renormalising means a developer is
    never marked down for a pillar the register simply does not carry.
    """
    available = {
        name: value
        for name, value in pillars.items()
        if value is not None and name in DEVELOPER_PILLAR_WEIGHTS
    }
    if not available:
        return None
    total_weight = sum(DEVELOPER_PILLAR_WEIGHTS[name] for name in available)
    if total_weight <= 0:
        return None
    # ``Decimal(0)`` as the sum's start keeps the accumulator decimal. Starting
    # from int 0 would make the sum ``int | Decimal``, and the division below would
    # then widen to float and lose precision on a published score.
    weighted = sum(
        (Decimal(value) * DEVELOPER_PILLAR_WEIGHTS[name] for name, value in available.items()),
        Decimal(0),
    )
    return clamp_pillar(weighted / total_weight)


def should_write_score(pillars: Mapping[str, Decimal | None]) -> bool:
    """False when every pillar is ``None``: no data is not a score of zero."""
    return any(value is not None for value in pillars.values())


class DeveloperDossierScraper(BaseScraper):
    """Reconcile ``Developer`` rows and recompute the five-pillar score."""

    name = "developer_dossier"
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
            "source": "rera_projects, rera_project_profiles, rera_statutory_approvals",
            "developers_checked": 0,
            "developers_scored": 0,
            "developers_without_score_data": 0,
            "status": "failed",
        }
        try:
            from app.core.database import get_bg_session_factory

            session_factory = get_bg_session_factory()
            async with session_factory() as db:
                records = await self._collect(db)
                # Reported alongside the scores, because an unmatched complaint is
                # invisible in the number it distorts.
                coverage.update(await self._complaint_coverage(db))
        except Exception as exc:
            logger.warning("Could not read the developer work list: %s", exc)
            result.errors.append(
                {
                    "stage": "work_list",
                    "error_type": type(exc).__name__,
                    "message": "The developer work list could not be read",
                }
            )
            result.source_coverage.append(coverage)
            return result

        coverage["developers_checked"] = len(records)
        for record in records:
            if should_write_score(record["pillars"]):
                coverage["developers_scored"] += 1
            else:
                coverage["developers_without_score_data"] += 1
        result.records = records
        coverage["status"] = "partial" if result.errors else "success"
        # The register was read successfully; a run that scores nobody is still a
        # successful read, not a failed scrape.
        result.successful_sources = 1
        result.source_coverage.append(coverage)
        return result

    async def _collect(self, db: AsyncSession) -> list[dict[str, Any]]:
        """Build one scored record per developer from the register's own rows.

        The caller owns the session: ``_scrape()`` opens a short-lived one, and a
        test can hand in its own.
        """
        names = await self._distinct_developer_names(db)
        if not names:
            return []
        score_rows = (
            await db.execute(
                select(Developer.slug, DeveloperScore.computed_at).join(
                    DeveloperScore, DeveloperScore.developer_id == Developer.id
                )
            )
        ).all()
        computed_at: dict[str, datetime] = {row[0]: row[1] for row in score_rows}
        # Unscored developers first, then the stalest scores, so a bounded run
        # still reaches every developer and keeps rescoring all of them in turn.
        oldest = datetime.min.replace(tzinfo=UTC)
        names.sort(
            key=lambda item: (
                item["slug"] in computed_at,
                computed_at.get(item["slug"]) or oldest,
                item["first_project_id"],
            )
        )
        selected = names[:DEFAULT_BATCH]
        selected_names = [spelling for item in selected for spelling in item["spellings"]]

        projects = await self._project_rows(db, selected_names)
        project_ids = [row[0] for row in projects]
        statutory = await self._statutory_rows(db, project_ids)
        costs = await self._cost_rows(db, project_ids)
        expenditure = await self._expenditure_rows(db, project_ids)
        complaints = await self._complaint_counts(db, selected_names)

        today = datetime.now(UTC).date()
        by_name: dict[str, list[Any]] = {}
        for row in projects:
            by_name.setdefault(row[1], []).append(row)

        records: list[dict[str, Any]] = []
        for item in selected:
            rows = [row for spelling in item["spellings"] for row in by_name.get(spelling, [])]
            stage_counts: dict[str, int] = {}
            regulatory_projects: list[dict[str, Any]] = []
            financial_projects: list[dict[str, Any]] = []
            market_projects: list[dict[str, Any]] = []
            for row in rows:
                (
                    project_id,
                    _developer_name,
                    status,
                    expiry_date,
                    units_booked,
                    total_units,
                    stage,
                    launch_price,
                    current_price,
                ) = row
                stage_value = stage.value if isinstance(stage, ProjectStage) else stage
                if stage_value is not None:
                    stage_counts[stage_value] = stage_counts.get(stage_value, 0) + 1
                statutory_row = statutory.get(project_id)
                plan_approvals = (statutory_row or {}).get("plan_approvals") or {}
                regulatory_projects.append(
                    {
                        "has_statutory_row": statutory_row is not None,
                        "plan_approvals_declared": len(plan_approvals),
                        "plan_approvals_obtained": sum(
                            1 for value in plan_approvals.values() if value
                        ),
                        "has_loi": bool(
                            (statutory_row or {}).get("loi_number")
                            or (statutory_row or {}).get("loi_date")
                        ),
                        "has_licence": bool(
                            (statutory_row or {}).get("licence_number")
                            or (statutory_row or {}).get("licence_date")
                        ),
                        "expired_without_completion": _expired_without_completion(
                            expiry_date=expiry_date,
                            status=status,
                            stage=stage_value,
                            today=today,
                        ),
                    }
                )
                financial_projects.append(
                    {
                        "total_cost": costs.get(project_id),
                        "expenditure_incurred": expenditure.get(project_id),
                    }
                )
                market_projects.append(
                    {
                        "launch_price_per_sqft": launch_price,
                        "current_price_per_sqft": current_price,
                        "units_booked": units_booked,
                        "total_units": total_units,
                    }
                )

            complaint_count = sum(
                complaints.get(folded, 0)
                for folded in {spelling.casefold() for spelling in item["spellings"]}
            )
            project_count = item["project_count"]
            pillars = compute_pillars(
                stage_counts=stage_counts,
                regulatory_projects=regulatory_projects,
                complaint_count=complaint_count,
                project_count=project_count,
                financial_projects=financial_projects,
                market_projects=market_projects,
            )
            delivered, under_construction = count_stages(stage_counts)
            records.append(
                {
                    "developer_slug": item["slug"],
                    "developer_name": item["name"],
                    "pillars": pillars,
                    "total_score": compute_total_score(pillars),
                    "project_count": project_count,
                    "delivered_count": delivered,
                    "under_construction_count": under_construction,
                    "complaint_count": complaint_count,
                    "computed_at": datetime.now(UTC),
                }
            )
        return records

    async def _distinct_developer_names(self, db: AsyncSession) -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(
                    ReraProject.developer_name,
                    func.count(ReraProject.id),
                    func.min(ReraProject.id),
                )
                .where(ReraProject.developer_name.isnot(None))
                .group_by(ReraProject.developer_name)
            )
        ).all()
        # Spellings that normalize to one slug are one developer. Group them so a
        # single score covers every spelling, instead of one per spelling where the
        # last upsert wins. The display name is the spelling with the most projects.
        by_slug: dict[str, dict[str, Any]] = {}
        for name, project_count, first_project_id in rows:
            slug = developer_slug(name) if name else None
            if not slug:
                continue
            count = int(project_count or 0)
            first = int(first_project_id or 0)
            entry = by_slug.get(slug)
            if entry is None:
                by_slug[slug] = {
                    "name": name,
                    "slug": slug,
                    "spellings": [name],
                    "project_count": count,
                    "first_project_id": first,
                    "_top_count": count,
                }
                continue
            entry["spellings"].append(name)
            entry["project_count"] += count
            entry["first_project_id"] = min(entry["first_project_id"], first)
            if (count, name) > (entry["_top_count"], entry["name"]):
                entry["name"], entry["_top_count"] = name, count
        for entry in by_slug.values():
            entry.pop("_top_count")
            entry["spellings"].sort()
        return list(by_slug.values())

    async def _project_rows(
        self, db: AsyncSession, names: Sequence[str]
    ) -> list[tuple[Any, ...]]:
        rows = (
            await db.execute(
                select(
                    ReraProject.id,
                    ReraProject.developer_name,
                    ReraProject.status,
                    ReraProject.expiry_date,
                    ReraProject.units_booked,
                    ReraProject.total_units,
                    ReraProjectProfile.stage,
                    ReraProjectProfile.launch_price_per_sqft,
                    ReraProjectProfile.current_price_per_sqft,
                )
                .outerjoin(
                    ReraProjectProfile, ReraProjectProfile.rera_project_id == ReraProject.id
                )
                .where(ReraProject.developer_name.in_(names))
            )
        ).all()
        return [tuple(row) for row in rows]

    async def _statutory_rows(
        self, db: AsyncSession, project_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        if not project_ids:
            return {}
        rows = (
            await db.execute(
                select(
                    ReraStatutoryApproval.rera_project_id,
                    ReraStatutoryApproval.loi_number,
                    ReraStatutoryApproval.loi_date,
                    ReraStatutoryApproval.licence_number,
                    ReraStatutoryApproval.licence_date,
                    ReraStatutoryApproval.plan_approvals,
                ).where(ReraStatutoryApproval.rera_project_id.in_(project_ids))
            )
        ).all()
        return {
            int(row[0]): {
                "loi_number": row[1],
                "loi_date": row[2],
                "licence_number": row[3],
                "licence_date": row[4],
                "plan_approvals": row[5],
            }
            for row in rows
        }

    async def _cost_rows(
        self, db: AsyncSession, project_ids: Sequence[int]
    ) -> dict[int, Decimal | None]:
        if not project_ids:
            return {}
        rows = (
            await db.execute(
                select(ReraProjectCost.rera_project_id, ReraProjectCost.total_cost).where(
                    ReraProjectCost.rera_project_id.in_(project_ids)
                )
            )
        ).all()
        return {int(row[0]): row[1] for row in rows}

    async def _expenditure_rows(
        self, db: AsyncSession, project_ids: Sequence[int]
    ) -> dict[int, Decimal | None]:
        if not project_ids:
            return {}
        rows = (
            await db.execute(
                select(
                    ReraQuarterlyExpenditure.rera_project_id,
                    func.sum(ReraQuarterlyExpenditure.amount),
                )
                .where(ReraQuarterlyExpenditure.rera_project_id.in_(project_ids))
                .group_by(ReraQuarterlyExpenditure.rera_project_id)
            )
        ).all()
        return {int(row[0]): row[1] for row in rows}

    async def _complaint_counts(
        self, db: AsyncSession, names: Sequence[str]
    ) -> dict[str, int]:
        """Complaints per developer, matched on ``respondent_builder``.

        The register writes the promoter name into ``respondent_builder``, so the
        match is the developer name compared case-insensitively.

        This match is exact, and that is a real limitation: the two names come
        from different HRERA pages, so "M/s DLF Ltd" and "DLF LIMITED" do not
        match. A developer whose name is written differently in the two places
        gets no complaints attributed, and the complaints pillar then reads a
        perfect 100. Do not soften this into fuzzy matching — attributing a
        complaint to the wrong developer is worse than leaving it unattributed.
        ``_complaint_coverage`` reports how many complaints matched nothing so the
        gap is visible in the run output rather than hidden in a score.
        """
        if not names:
            return {}
        keys = [name.casefold() for name in names]
        rows = (
            await db.execute(
                select(
                    func.lower(ReraComplaint.respondent_builder),
                    func.count(ReraComplaint.id),
                )
                .where(func.lower(ReraComplaint.respondent_builder).in_(keys))
                .group_by(func.lower(ReraComplaint.respondent_builder))
            )
        ).all()
        return {str(row[0]): int(row[1] or 0) for row in rows}

    async def _complaint_coverage(self, db: AsyncSession) -> dict[str, int]:
        """How many filed complaints name a builder the register does not list.

        Complaints are filed against the name on the complaint itself, which need
        not match any ``rera_projects.developer_name``. A high unmatched count
        means the complaints pillar is reading low for everyone, so it belongs in
        the run output next to the counts it explains.
        """
        total = (
            await db.execute(select(func.count(ReraComplaint.id)))
        ).scalar_one()
        named = (
            await db.execute(
                select(func.count(ReraComplaint.id)).where(
                    ReraComplaint.respondent_builder.isnot(None)
                )
            )
        ).scalar_one()
        matched = (
            await db.execute(
                select(func.count(ReraComplaint.id)).where(
                    func.lower(ReraComplaint.respondent_builder).in_(
                        select(func.lower(ReraProject.developer_name)).where(
                            ReraProject.developer_name.isnot(None)
                        )
                    )
                )
            )
        ).scalar_one()
        return {
            "complaints_on_file": int(total or 0),
            "complaints_with_a_named_builder": int(named or 0),
            "complaints_matched_to_a_register_developer": int(matched or 0),
            "complaints_unmatched": int(named or 0) - int(matched or 0),
        }

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {"found": 0, "upserted": 0, "failed": 0}
        # Repair project rows that predate the column before scoring, so a
        # developer's project list and its score agree from the same pass.
        repaired = await self._backfill_developer_slugs(db)
        if repaired:
            logger.info("Backfilled developer_slug on %s project rows", repaired)
        found = len(records)
        upserted = 0
        failed = 0
        for record in records:
            record["_upsert_succeeded"] = False
            try:
                async with db.begin_nested():
                    developer_id = await self._upsert_developer(db, record)
                    if should_write_score(record["pillars"]):
                        await self._upsert_score(db, developer_id, record)
                    else:
                        logger.info(
                            "No pillar data for developer %s — no score row written",
                            record.get("developer_slug"),
                        )
                upserted += 1
                record["_upsert_succeeded"] = True
            except Exception as exc:
                logger.warning(
                    "Failed to write dossier for developer %s: %s",
                    record.get("developer_slug"),
                    exc,
                )
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}

    async def _backfill_developer_slugs(self, db: AsyncSession) -> int:
        """Fill ``rera_projects.developer_slug`` from the name it already holds.

        The builder pages group a developer's projects by this slug, while the
        score matches on the name. A project with a name but no slug therefore
        shows up in its developer's score and not in its project list — and
        ``GET /data-hub/builders`` returns nothing at all, so every builder page
        is a 404. Rows written before the column existed all look like that.

        Only null slugs are touched, and the value comes from the row's own
        ``developer_name``, so this cannot re-group a project that already has
        one. The slug is computed in Python by ``developer_slug``, the same
        function the upsert uses, rather than re-derived in SQL: two
        implementations of one rule would drift, and a drifted slug silently
        splits one developer into two groups.
        """
        rows = (
            await db.execute(
                select(ReraProject.developer_name)
                .where(
                    ReraProject.developer_slug.is_(None),
                    ReraProject.developer_name.isnot(None),
                )
                .group_by(ReraProject.developer_name)
            )
        ).scalars().all()
        repaired = 0
        for name in rows:
            if name is None:
                continue
            slug = developer_slug(name)
            if not slug:
                continue
            result = await db.execute(
                update(ReraProject)
                .where(
                    ReraProject.developer_name == name,
                    ReraProject.developer_slug.is_(None),
                )
                .values(developer_slug=slug)
                .execution_options(synchronize_session=False)
            )
            repaired += int(getattr(result, "rowcount", 0) or 0)
        return repaired

    async def _upsert_developer(self, db: AsyncSession, record: dict[str, Any]) -> int:
        """Upsert on slug, touching only the columns this job owns.

        ``summary``, ``dossier``, ``logo_url`` and ``website_url`` are never in
        the update set, so a value written by another source survives.
        """
        statement = pg_insert(Developer).values(
            slug=record["developer_slug"],
            name=record["developer_name"],
            legal_name=record["developer_name"],
            last_checked_at=record["computed_at"],
        )
        result = await db.execute(
            statement.on_conflict_do_update(
                index_elements=["slug"],
                set_={
                    "name": statement.excluded.name,
                    "legal_name": statement.excluded.legal_name,
                    "last_checked_at": statement.excluded.last_checked_at,
                },
            ).returning(Developer.id)
        )
        return int(result.scalar_one())

    async def _upsert_score(
        self, db: AsyncSession, developer_id: int, record: dict[str, Any]
    ) -> None:
        pillars = record["pillars"]
        statement = pg_insert(DeveloperScore).values(
            developer_id=developer_id,
            delivery=pillars["delivery"],
            regulatory=pillars["regulatory"],
            complaints=pillars["complaints"],
            financials=pillars["financials"],
            market_reception=pillars["market_reception"],
            total_score=record["total_score"],
            project_count=record["project_count"],
            delivered_count=record["delivered_count"],
            under_construction_count=record["under_construction_count"],
            complaint_count=record["complaint_count"],
            computed_at=record["computed_at"],
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["developer_id"],
                set_={
                    "delivery": statement.excluded.delivery,
                    "regulatory": statement.excluded.regulatory,
                    "complaints": statement.excluded.complaints,
                    "financials": statement.excluded.financials,
                    "market_reception": statement.excluded.market_reception,
                    "total_score": statement.excluded.total_score,
                    "project_count": statement.excluded.project_count,
                    "delivered_count": statement.excluded.delivered_count,
                    "under_construction_count": statement.excluded.under_construction_count,
                    "complaint_count": statement.excluded.complaint_count,
                    "computed_at": statement.excluded.computed_at,
                },
            )
        )


def _expired_without_completion(
    *,
    expiry_date: date | None,
    status: str | None,
    stage: str | None,
    today: date,
) -> bool:
    """A filed completion date that has passed while the project is not completed."""
    if expiry_date is None or expiry_date >= today:
        return False
    if stage == _COMPLETED_STAGE:
        return False
    return (status or "").casefold() != _COMPLETED_STAGE
