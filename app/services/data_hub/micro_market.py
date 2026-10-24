"""Micro-markets derived from the sectors and localities the RERA filings name.

``micro_markets`` had no writer anywhere in this codebase, so
``GET /api/v1/data-hub/micro-markets`` always returned an empty list and
``GET /api/v1/data-hub/micro-markets/{city}/{slug}`` always 404'd. This module is
that writer.

There is no micro-market feed to scrape. The only honest signal is the address
text a filing carries (``ReraProject.location``) plus the district it files under
(``ReraProject.district``). A sector or locality that a real filing names is a
real place, and that is the whole justification for the row. Nothing here is
guessed: a location the parser cannot read produces **no** row, and the run's
coverage records how many were skipped and under which reason, so the gap is
visible instead of silently filled with an invented name.

``city`` versus ``district``
----------------------------

Both columns hold the same district string, lowercased. ``market_pulse`` already
treats the district as the city, because that is the unit the HRERA register files
against. Holding the two columns identical makes the ``(city, slug)`` uniqueness
the model enforces exactly the ``(district, slug)`` scoping this parser uses, and
lets the public URL ``/micro-markets/gurugram/sector-76-77`` round-trip through
the list filter ``?city=Gurugram``. Any other choice would need a district-to-city
mapping that no filing publishes, which would be invented data.

**Lowercase is the stored spelling, and it is the identity.** The unique index
``uq_micro_markets_city_slug`` is case-sensitive, the reader matches the
``{city}`` segment case-insensitively, and the site 301s any path carrying an
uppercase letter to its lowercase form — so the URL's spelling is already
lowercase, and a writer that stored the filed spelling verbatim gave one place two
rows that both matched one URL: two public pages for one locality showing
different numbers. Storing the lowercase form makes the three agree by
construction, and ``_link_projects`` lowercases both sides of its lookup key for
the same reason, so the writer, the reader and the linker cannot disagree about
identity. The filed spelling survives only in the ``summary`` prose, title-cased
the way the register writers already title-case it for display.

The link to a project
---------------------

A micro-market's statistics come from ``rera_projects.micro_market_id``, which
``_link_projects`` writes in the same run that writes the market, using the same
``derive_locality`` that named it. Without that link the read side can only scope
by district, and two localities in one district then report identical numbers
under two different names. A project whose address names no readable locality
stays ``NULL`` and belongs to no micro-market, which is the honest answer.

A run whose link step fails is reported as ``partial``, never ``success``: the
market rows were written but every project's ``micro_market_id`` stayed ``NULL``,
so the run's own statistics claim cannot be stood behind. ``_upsert`` counts the
failure in ``failed``, which is what ``final_run_status`` reads.

Coordinates and prose
---------------------

``latitude`` and ``longitude`` are always ``None``: HRERA filings do not publish
coordinates, so there is nothing to derive. ``summary`` is one sentence assembled
only from numbers this run derived — how many filings in the district name this
locality — and never marketing copy.

The derivation rule
-------------------

``derive_locality`` is a pure function, so it is pinned without a database by
``tests/unit/services/test_micro_market.py``. Precedence is sector, then phase,
then a bare named place:

1. **Sector** — the first ``SECTOR``/``SEC`` token with a number, anywhere in the
   string. ``SECTOR 76/77`` keeps the slash pair as one locality because the
   filing names it as one and never says which half the project sits on;
   ``SECTOR-45``, ``SEC. 62`` and ``PLOT NO. 5, SECTOR 45, GURUGRAM`` all resolve
   to the sector. An address naming two *different* sectors is refused rather than
   silently reduced to one.
2. **Phase** — ``PHASE`` with a number, keeping a short alphabetic prefix:
   ``DLF PHASE 1`` -> ``DLF Phase 1``. A prefix carrying a plot or unit marker is
   refused.
3. **Named place** — the address is split on commas and semicolons, components
   that are a plot/khasra/unit marker, a postal line (any component carrying a
   six-digit postal code), or the district/state name are dropped, and exactly
   one component must survive: ``GOLF COURSE ROAD, GURUGRAM`` ->
   ``Golf Course Road``. Zero survivors (``PLOT NO 12, KHASRA NO 45/2``,
   ``DELHI - 110058``) or two or more (``SOHNA ROAD, GOLF COURSE ROAD``) is
   refused.

Refusing is the point. A guessed micro-market would be a fabricated place with a
fabricated slug on a public page.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import MicroMarket, ReraProject
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult
from app.services.data_hub.utils import canonical_city, generate_slug

logger = logging.getLogger(__name__)

#: Upper bound on the distinct ``(district, location)`` pairs read in one run, so
#: one run cannot walk the whole register. Reaching it is reported in the coverage.
PAIR_LIMIT = 5000

#: Upper bound on the project rows examined when attaching each project to its
#: micro-market. Comfortably above the NCR register, and reaching it is reported.
PROJECT_LINK_LIMIT = 20000

#: A named place longer than this, or with more words, is a postal address rather
#: than a locality, so it is refused.
MAX_NAME_CHARS = 60
MAX_NAME_WORDS = 6

#: Longest alphabetic prefix allowed in front of ``PHASE``.
MAX_PHASE_PREFIX_WORDS = 3

# Natural key of a micro-market. Mirrors ``uq_micro_markets_city_slug``.
MICRO_MARKET_INDEX_ELEMENTS = ["city", "slug"]

#: Columns a re-run owns. ``city`` and ``slug`` are the conflict key and
#: ``created_at`` is the row's birth time, so neither is ever in the update set.
MICRO_MARKET_UPDATE_FIELDS = ("name", "district", "summary", "latitude", "longitude")

#: Initialisms that must not be title-cased into a different word.
_ACRONYMS = frozenset(
    {"DLF", "HUDA", "HSVP", "MGF", "TDI", "SBP", "VVIP", "IMT", "NH", "GT", "EWS"}
)

#: Component words that mark an address part, never a place: a plot number is not
#: a locality, and neither is "near the bus stand".
_NON_PLACE_LEADING_TOKENS = frozenset(
    {
        "PLOT",
        "PLOTS",
        "KHASRA",
        "KHEWAT",
        "MUSTIL",
        "GATA",
        "SURVEY",
        "FLAT",
        "UNIT",
        "TOWER",
        "HOUSE",
        "SHOP",
        "BLOCK",
        "GATE",
        "NEAR",
        "OPP",
        "OPPOSITE",
        "BEHIND",
        "ADJOINING",
        "BESIDE",
        "WARD",
        "MUNICIPAL",
        "TEHSIL",
        "DISTRICT",
    }
)

#: Administrative names that are never a locality, whichever district is in play.
#: ``DELHI`` belongs here for the same reason ``GURGAON`` does: it is the state
#: (NCT of Delhi) and the city, and every Delhi filing's address ends with it.
#: The district comparison below only catches it when the row's own district is
#: literally "Delhi", so a Shahdara or New Delhi filing would otherwise publish
#: the state name as its locality.
_ADMINISTRATIVE_NAMES = frozenset({"GURGAON", "HARYANA", "DELHI", "INDIA"})

#: An Indian postal code is six digits. A component carrying one is the address's
#: postal line (``DELHI - 110058``), never a place name, and the register writes
#: one on nearly every Delhi address. Without this the only component left after
#: the district and the landmark are dropped is that postal line, and the run
#: publishes it as a micro-market: ``micro_markets`` carried a row named
#: "Delhi - 110058" in Shahdara, slug ``delhi-110058``, derived from
#: DLRERA2025P0014.
_PINCODE_RE = re.compile(r"\b\d{6}\b")

_SECTOR_RE = re.compile(
    r"\b(?:SECTOR|SEC)\b\s*[-.:]?\s*(\d{1,4}[A-Z]?(?:\s*[/&-]\s*\d{1,4}[A-Z]?)*)"
)
_SECTOR_WORD_RE = re.compile(r"\b(?:SECTOR|SEC)\b")
_PHASE_RE = re.compile(r"\bPHASE\b\s*[-.:]?\s*(\d{1,2}|[IVX]{1,4})\b")
_ROMAN_RE = re.compile(r"[IVX]{1,4}")
_COMPONENT_RE = re.compile(r"[,;]")

#: Shapes the parser recognises, reported per parsed pair in the coverage.
SHAPE_SECTOR = "sector"
SHAPE_PHASE = "phase"
SHAPE_NAMED_PLACE = "named_place"

#: Why a location produced no micro-market.
REASON_NO_LOCATION = "no_location"
REASON_NO_DISTRICT = "no_district"
REASON_MULTIPLE_SECTORS = "multiple_sectors_named"
REASON_MALFORMED_SECTOR = "sector_without_a_number"
REASON_PHASE_PREFIX = "unreadable_phase_prefix"
REASON_NO_COMPONENT = "no_locality_component"
REASON_AMBIGUOUS = "ambiguous_multiple_localities"
REASON_UNRECOGNISED = "unrecognised_locality"


@dataclass(frozen=True)
class Locality:
    """A place inside a district, derived from the filed address text."""

    name: str
    slug: str
    shape: str


@dataclass(frozen=True)
class LocalityParse:
    """The outcome of reading one filed location.

    ``locality`` is ``None`` when the address was refused, and ``reason`` then
    carries the refusal code that lands in the run coverage.
    """

    locality: Locality | None
    reason: str | None = None

    @property
    def parsed(self) -> bool:
        return self.locality is not None


def _clean(location: str) -> str:
    """Upper-case, dash-normalise and collapse the filed address text."""
    text = unicodedata.normalize("NFKC", location)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().upper()


def _title_case(text: str) -> str:
    """Readable place name, keeping initialisms and roman numerals intact."""
    words: list[str] = []
    for word in text.split():
        if word in _ACRONYMS or _ROMAN_RE.fullmatch(word):
            words.append(word)
        elif any(character.isdigit() for character in word):
            words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def micro_market_slug(name: str) -> str:
    """Stable slug for a derived name.

    The name is the only input, so the same place always lands on the same slug
    and a re-run updates the row instead of adding a second one. ``/`` and ``&``
    become separators rather than being deleted, so ``Sector 76/77`` slugs to
    ``sector-76-77`` and not to ``sector-7677``.
    """
    return generate_slug(name.replace("/", " ").replace("&", " "))


def district_display(value: str) -> str:
    """The district as prose names it, from the stored lowercase spelling.

    Display only. The register writers already title-case the district for the
    same reason (``rera_portal_scan._filed_district``), so this is the spelling a
    reader of ``summary`` already sees, and it is deterministic across filings.
    """
    return value.title()


def _canonical_sector_numbers(raw: str) -> str:
    """``76 / 77``, ``76&77`` and ``76-77`` all become ``76/77``."""
    parts = [part.strip() for part in re.split(r"[/&-]", raw)]
    return "/".join(part for part in parts if part)


def _sector_names(text: str) -> list[str]:
    """Every distinct sector the address names, in the order they appear."""
    names: list[str] = []
    for raw in _SECTOR_RE.findall(text):
        numbers = _canonical_sector_numbers(raw)
        name = f"Sector {numbers}"
        if name not in names:
            names.append(name)
    return names


def _phase_name(text: str) -> str | None:
    """``DLF PHASE 1`` -> ``DLF Phase 1``. ``None`` when the prefix is unusable.

    The prefix is what precedes ``PHASE``. It must be short, alphabetic and free
    of address markers, so ``PLOT NO 5 PHASE 2`` is refused rather than read as a
    place called "Plot No Phase 2".
    """
    match = _PHASE_RE.search(text)
    if match is None:
        return None
    number = match.group(1)
    prefix = text[: match.start()].strip().strip("-.:,;").strip()
    if not prefix:
        return f"Phase {number}"
    words = prefix.split()
    if len(words) > MAX_PHASE_PREFIX_WORDS:
        return None
    for word in words:
        letters = word.strip("&.")
        if not letters or not letters.isalpha():
            return None
        if letters in _NON_PLACE_LEADING_TOKENS:
            return None
    return f"{_title_case(prefix)} Phase {number}"


def _components(text: str) -> list[str]:
    return [part.strip() for part in _COMPONENT_RE.split(text) if part.strip()]


def _is_address_part(component: str, district: str) -> bool:
    """True for an address part that names no place: a plot, a unit, the district.

    A component carrying the address's postal code counts as an address part for
    the same reason the district does: ``DELHI - 110058`` is the last line of the
    address, not a locality inside it.
    """
    if component == district or component in _ADMINISTRATIVE_NAMES:
        return True
    if _PINCODE_RE.search(component):
        return True
    first = component.split()[0].strip(".,-:").upper()
    return first in _NON_PLACE_LEADING_TOKENS


def _is_place_name(component: str) -> bool:
    """True when a surviving component can be published as a locality name."""
    if not any(character.isalpha() for character in component):
        return False
    if len(component) > MAX_NAME_CHARS:
        return False
    if len(component.split()) > MAX_NAME_WORDS:
        return False
    return not _SECTOR_WORD_RE.search(component)


def derive_locality(location: str | None, *, district: str | None = None) -> LocalityParse:
    """Derive one locality from one filed address, or refuse it with a reason.

    Pure: no database, no network, no clock. See the module docstring for the
    three shapes and the refusal rule.
    """
    if location is None or not location.strip():
        return LocalityParse(locality=None, reason=REASON_NO_LOCATION)
    if district is None or not district.strip():
        return LocalityParse(locality=None, reason=REASON_NO_DISTRICT)

    text = _clean(location)
    district_name = _clean(district)

    sectors = _sector_names(text)
    if len(sectors) > 1:
        return LocalityParse(locality=None, reason=REASON_MULTIPLE_SECTORS)
    if sectors:
        name = sectors[0]
        return LocalityParse(
            locality=Locality(name=name, slug=micro_market_slug(name), shape=SHAPE_SECTOR)
        )
    if _SECTOR_WORD_RE.search(text):
        return LocalityParse(locality=None, reason=REASON_MALFORMED_SECTOR)

    if _PHASE_RE.search(text):
        phase_name = _phase_name(text)
        if phase_name is None:
            return LocalityParse(locality=None, reason=REASON_PHASE_PREFIX)
        return LocalityParse(
            locality=Locality(
                name=phase_name, slug=micro_market_slug(phase_name), shape=SHAPE_PHASE
            )
        )

    survivors = [
        component
        for component in _components(text)
        if not _is_address_part(component, district_name)
    ]
    if not survivors:
        return LocalityParse(locality=None, reason=REASON_NO_COMPONENT)
    if len(survivors) > 1:
        return LocalityParse(locality=None, reason=REASON_AMBIGUOUS)

    component = survivors[0]
    if not _is_place_name(component):
        return LocalityParse(locality=None, reason=REASON_UNRECOGNISED)
    name = _title_case(component)
    return LocalityParse(
        locality=Locality(name=name, slug=micro_market_slug(name), shape=SHAPE_NAMED_PLACE)
    )


def build_records(
    pairs: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn distinct ``(district, location)`` pairs into micro-market records.

    One record per ``(district, slug)``: two filings that name the same sector in
    the same district collapse into one micro-market, and the same sector in two
    districts stays two. The district is the stored identity — lowercased by
    ``canonical_city`` — so two filings that spell one district differently are
    one record, not two. ``summary`` is assembled from the number of filings that
    actually named the locality, and names the district the way a reader expects
    it rather than the way it is stored.

    Returns the records (sorted by city then slug, so a run is deterministic) and
    the coverage dict, whose ``pairs_skipped`` is always the sum of
    ``skip_reasons``.
    """
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    skip_reasons: Counter[str] = Counter()
    shapes: Counter[str] = Counter()
    pairs_checked = 0
    pairs_skipped = 0
    projects_covered = 0
    projects_skipped = 0

    for pair in pairs:
        pairs_checked += 1
        district = canonical_city(pair.get("district"))
        location = pair.get("location")
        filings = int(pair.get("project_count") or 0)
        parse = derive_locality(
            location if isinstance(location, str) else None,
            district=district,
        )
        if parse.locality is None:
            pairs_skipped += 1
            projects_skipped += filings
            skip_reasons[parse.reason or REASON_UNRECOGNISED] += 1
            continue

        locality = parse.locality
        shapes[locality.shape] += 1
        projects_covered += filings
        record = grouped.get((district, locality.slug))
        if record is None:
            grouped[(district, locality.slug)] = {
                "city": district,
                "name": locality.name,
                "slug": locality.slug,
                "district": district,
                "summary": None,
                "latitude": None,
                "longitude": None,
                "_filings": filings,
                "_locations": [location],
            }
        else:
            record["_filings"] += filings
            record["_locations"].append(location)

    for record in grouped.values():
        record["summary"] = _summary(
            name=record["name"],
            district=district_display(record["district"]),
            filings=record["_filings"],
        )

    records = sorted(grouped.values(), key=lambda item: (item["city"], item["slug"]))
    coverage: dict[str, Any] = {
        "source": "rera_projects (district, location)",
        "pairs_checked": pairs_checked,
        "pairs_skipped": pairs_skipped,
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "shape_breakdown": dict(sorted(shapes.items())),
        "micro_markets_derived": len(records),
        "projects_covered": projects_covered,
        "projects_skipped": projects_skipped,
    }
    return records, coverage


def _summary(*, name: str, district: str, filings: int) -> str:
    """One factual sentence, from the only number this run derived.

    The read side counts projects by district, so it cannot say how many filings
    named *this* locality. That is the one thing this sentence adds, and it is a
    count of rows already in the register, not a claim about the market.
    """
    filing_word = "filing" if filings == 1 else "filings"
    verb = "names" if filings == 1 else "name"
    return f"Derived from {filings} RERA {filing_word} in {district} that {verb} {name}."


class MicroMarketScraper(BaseScraper):
    """Derive ``MicroMarket`` rows from the sectors the filings actually name."""

    name = "micro_market"
    requires_playwright = False

    #: The coverage dict ``_scrape`` built for this run. ``_upsert`` runs after
    #: ``_scrape`` and is where the markets get their ids, so it is the only place
    #: the project link can be written — and the counts belong in the coverage
    #: that ``_scrape`` already handed to the run, not in a log line. A fresh
    #: scraper instance is built per run, so this is per-run state.
    _coverage: dict[str, Any] | None = None

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
            "source": "rera_projects (district, location)",
            "status": "failed",
        }
        self._coverage = coverage
        try:
            from app.core.database import get_bg_session_factory

            session_factory = get_bg_session_factory()
            async with session_factory() as db:
                records, coverage = await self._collect(db)
                self._coverage = coverage
        except Exception as exc:
            logger.warning("Could not read the filed locations: %s", exc)
            result.errors.append(
                {
                    "stage": "locations",
                    "error_type": type(exc).__name__,
                    "message": "The filed locations could not be read",
                }
            )
            result.source_coverage.append(coverage)
            return result

        result.records = records
        coverage["status"] = "partial" if result.errors else "success"
        # The register was read successfully; a register that names no locality is
        # still a successful read, not a failed scrape.
        result.successful_sources = 1
        result.source_coverage.append(coverage)
        return result

    async def _collect(
        self, db: AsyncSession
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Read the distinct filed pairs and derive the records from them.

        The caller owns the session: ``_scrape()`` opens a short-lived one, and a
        test can hand in its own.
        """
        rows = (
            await db.execute(
                select(
                    ReraProject.district,
                    ReraProject.location,
                    func.count(ReraProject.id),
                )
                .where(ReraProject.location.isnot(None))
                .group_by(ReraProject.district, ReraProject.location)
                .order_by(ReraProject.district, ReraProject.location)
                .limit(PAIR_LIMIT)
            )
        ).all()
        pairs = [
            {
                "district": row[0],
                "location": row[1],
                "project_count": int(row[2] or 0),
            }
            for row in rows
        ]
        records, coverage = build_records(pairs)
        coverage["pair_limit"] = PAIR_LIMIT
        # At the cap the read may have stopped short of the register, so the gap is
        # reported rather than presented as full coverage.
        coverage["pair_limit_reached"] = len(rows) >= PAIR_LIMIT
        return records, coverage

    async def _link_projects(self, db: AsyncSession) -> dict[str, Any]:
        """Attach every project to the micro-market its own address resolves to.

        Without this the read side can only scope a micro-market's statistics by
        district, so two localities in one district report the same project count
        and the same average rate under two different names. This writes the real
        link, using the same ``derive_locality`` that named the markets, so a
        project and its market cannot disagree about which place it is in.

        The markets are read back from the table rather than taken from this run's
        derived records. A run that derives nothing — every location unreadable
        after a parser change, or the pair read hitting its cap — must still
        repair the links it can, and must still clear the ones whose market is
        gone. Keying off this run's own output would silently skip both.

        A project whose address names no readable locality is set to ``NULL``
        rather than left pointing at a stale market, because the invariant this
        maintains is "the link equals the derivation" — and a refusal derives to
        nothing. The counts are returned for the run's coverage.

        Both sides of the lookup key go through ``canonical_city``, the same
        normalisation the writer stores under, so the linker, the writer and the
        reader agree on identity rather than on spelling. That also keeps a table
        written before the normalisation linkable instead of stranding every
        project in it. When two rows do exist for one key the lowest id wins,
        which is the row the read side serves.
        """
        markets = (
            await db.execute(
                select(MicroMarket.city, MicroMarket.slug, MicroMarket.id).order_by(
                    MicroMarket.id
                )
            )
        ).all()
        market_ids: dict[tuple[str, str], int] = {}
        for city, slug, market_id in markets:
            # First wins, and the read is ordered by id, so the market the public
            # page resolves to is the market the projects are linked to.
            market_ids.setdefault((canonical_city(city), slug), int(market_id))
        rows = (
            await db.execute(
                select(ReraProject.id, ReraProject.district, ReraProject.location)
                .order_by(ReraProject.id)
                .limit(PROJECT_LINK_LIMIT)
            )
        ).all()
        by_market: dict[int, list[int]] = {}
        to_clear: list[int] = []
        for project_id, district, location in rows:
            parse = derive_locality(location, district=district)
            market_id = (
                market_ids.get((canonical_city(district), parse.locality.slug))
                if parse.locality is not None
                else None
            )
            if market_id is None:
                to_clear.append(project_id)
            else:
                by_market.setdefault(market_id, []).append(project_id)

        # One statement per distinct market rather than per project: the register
        # is large and the number of localities in it is not.
        for market_id, project_ids in by_market.items():
            await db.execute(
                update(ReraProject)
                .where(ReraProject.id.in_(project_ids))
                .values(micro_market_id=market_id)
                .execution_options(synchronize_session=False)
            )
        if to_clear:
            await db.execute(
                update(ReraProject)
                .where(ReraProject.id.in_(to_clear))
                .values(micro_market_id=None)
                .execution_options(synchronize_session=False)
            )

        linked = sum(len(ids) for ids in by_market.values())
        return {
            "projects_examined": len(rows),
            "projects_linked": linked,
            "projects_without_a_readable_locality": len(to_clear),
            "project_link_limit": PROJECT_LINK_LIMIT,
            "project_link_limit_reached": len(rows) >= PROJECT_LINK_LIMIT,
        }

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
                    if hasattr(MicroMarket, key) and key not in ("id", "created_at")
                }
                async with db.begin_nested():
                    statement = pg_insert(MicroMarket).values(**values)
                    await db.execute(
                        statement.on_conflict_do_update(
                            index_elements=MICRO_MARKET_INDEX_ELEMENTS,
                            set_={
                                field: getattr(statement.excluded, field)
                                for field in MICRO_MARKET_UPDATE_FIELDS
                            },
                        )
                    )
                upserted += 1
                record["_upsert_succeeded"] = True
            except Exception as exc:
                logger.warning(
                    "Failed to write micro-market %s in %s: %s",
                    record.get("slug"),
                    record.get("city"),
                    exc,
                )
                failed += 1

        # Only link after the markets are written: a project cannot point at a row
        # that does not exist yet. This runs whenever the upsert ran, not only when
        # _scrape happened to run first — the link is the writer's job, and making
        # it depend on a sibling method having been called would leave it silently
        # skipped.
        try:
            # A savepoint keeps a failed link from rolling back the market rows
            # already written above, which ``upserted`` reports as written.
            async with db.begin_nested():
                link_coverage = await self._link_projects(db)
            if self._coverage is not None:
                self._coverage.update(link_coverage)
        except Exception as exc:
            logger.warning("Could not link projects to their micro-markets: %s", exc)
            if self._coverage is not None:
                self._coverage["project_link_failed"] = type(exc).__name__
            # The link is part of this run's job, not an errand after it: without
            # it every market row carries a project count the run cannot stand
            # behind. Counting it in ``failed`` is what makes ``final_run_status``
            # report ``partial`` rather than the ``success`` it reported while
            # every project's ``micro_market_id`` stayed NULL. Same mechanism
            # ``base_scraper`` already uses for a provenance failure.
            failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}
