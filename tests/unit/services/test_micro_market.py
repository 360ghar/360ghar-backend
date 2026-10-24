"""Micro-market derivation: the address shapes, the collapse, and the rights gate.

Every name and slug asserted here is pinned by hand, so a change to the parser
that renames a public page fails a test rather than silently moving a URL.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from app.config import settings
from app.models.data_hub import MicroMarket, ReraProject
from app.services.data_hub.base_scraper import ScrapeResult, final_run_status
from app.services.data_hub.micro_market import (
    REASON_AMBIGUOUS,
    REASON_MALFORMED_SECTOR,
    REASON_MULTIPLE_SECTORS,
    REASON_NO_COMPONENT,
    REASON_NO_LOCATION,
    REASON_PHASE_PREFIX,
    REASON_UNRECOGNISED,
    SHAPE_NAMED_PLACE,
    SHAPE_PHASE,
    SHAPE_SECTOR,
    MicroMarketScraper,
    build_records,
    derive_locality,
)

DISTRICT = "Gurugram"


def _parsed(location: str | None, district: str = DISTRICT):
    parse = derive_locality(location, district=district)
    assert parse.locality is not None, parse.reason
    return parse.locality


def _refused(location: str | None, district: str = DISTRICT) -> str:
    parse = derive_locality(location, district=district)
    assert parse.locality is None
    return str(parse.reason)


class TestSectorShapes:
    def test_a_slash_pair_is_one_locality(self):
        locality = _parsed("SECTOR 76/77")

        assert locality.name == "Sector 76/77"
        assert locality.slug == "sector-76-77"
        assert locality.shape == SHAPE_SECTOR

    def test_a_plain_sector(self):
        locality = _parsed("Sector 62")

        assert locality.name == "Sector 62"
        assert locality.slug == "sector-62"

    def test_a_hyphenated_sector(self):
        locality = _parsed("SECTOR-45")

        assert locality.name == "Sector 45"
        assert locality.slug == "sector-45"

    def test_an_abbreviated_sector(self):
        locality = _parsed("SEC. 62")

        assert locality.name == "Sector 62"
        assert locality.slug == "sector-62"

    def test_a_sector_with_a_letter_suffix(self):
        locality = _parsed("SECTOR 45A")

        assert locality.name == "Sector 45A"
        assert locality.slug == "sector-45a"

    def test_a_sector_inside_a_full_address(self):
        locality = _parsed("PLOT NO. 5, SECTOR 45, GURUGRAM")

        assert locality.name == "Sector 45"
        assert locality.slug == "sector-45"

    def test_an_ampersand_pair_reads_as_the_slash_pair(self):
        assert _parsed("SECTOR 76 & 77").slug == _parsed("SECTOR 76/77").slug
        # A dash joins a range too; the second number must not be dropped.
        assert _parsed("SECTOR 76-77").slug == _parsed("SECTOR 76/77").slug

    def test_two_different_sectors_are_refused_rather_than_reduced_to_one(self):
        assert _refused("SECTOR 45, SECTOR 46") == REASON_MULTIPLE_SECTORS

    def test_a_sector_without_a_number_is_refused(self):
        assert _refused("SECTOR ROAD") == REASON_MALFORMED_SECTOR


class TestPhaseShapes:
    def test_a_dlf_phase_keeps_its_initialism(self):
        locality = _parsed("DLF PHASE 1")

        assert locality.name == "DLF Phase 1"
        assert locality.slug == "dlf-phase-1"
        assert locality.shape == SHAPE_PHASE

    def test_a_named_prefix_keeps_its_words(self):
        assert _parsed("SUSHANT LOK PHASE 1").name == "Sushant Lok Phase 1"

    def test_a_phase_behind_a_plot_number_is_refused(self):
        assert _refused("PLOT NO 5 PHASE 2") == REASON_PHASE_PREFIX


class TestNamedPlaceShapes:
    def test_a_corridor_name(self):
        locality = _parsed("GOLF COURSE ROAD")

        assert locality.name == "Golf Course Road"
        assert locality.slug == "golf-course-road"
        assert locality.shape == SHAPE_NAMED_PLACE

    def test_the_district_name_is_dropped_from_the_address(self):
        locality = _parsed("GOLF COURSE ROAD, GURUGRAM")

        assert locality.name == "Golf Course Road"
        assert locality.slug == "golf-course-road"

    def test_the_state_name_is_not_a_locality(self):
        assert _refused("GURUGRAM, HARYANA") == REASON_NO_COMPONENT

    def test_an_address_that_is_only_the_district_is_refused(self):
        assert _refused("GURUGRAM") == REASON_NO_COMPONENT

    def test_two_locality_components_are_refused(self):
        assert _refused("SOHNA ROAD, GOLF COURSE ROAD") == REASON_AMBIGUOUS

    def test_marker_only_components_are_refused(self):
        assert _refused("PLOT NO 12, KHASRA NO 45/2") == REASON_NO_COMPONENT

    def test_a_landmark_relative_address_is_refused(self):
        assert _refused("NEAR BUS STAND") == REASON_NO_COMPONENT

    def test_a_number_is_not_a_place(self):
        assert _refused("12345") == REASON_UNRECOGNISED

    def test_a_postal_code_line_is_not_a_locality(self):
        # DLRERA2025P0014 files "Near Karkardooma Metro Station, Adjoining
        # Jagriti Enclave, Shahdara, Shahdara, Delhi - 110058". Once the district
        # and the landmark components are dropped, the only survivor is the
        # state name carrying the address's postal code. That is an address
        # part, not a place, so the address derives no micro-market at all.
        assert (
            _refused(
                "Near Karkardooma Metro Station, Adjoining Jagriti Enclave, "
                "Shahdara, Shahdara, Delhi - 110058",
                district="Shahdara",
            )
            == REASON_NO_COMPONENT
        )

    def test_the_state_name_with_its_postal_code_is_not_a_locality(self):
        assert _refused("NEW DELHI, DELHI - 110001", district="New Delhi") == REASON_NO_COMPONENT

    def test_the_state_name_alone_is_not_a_locality(self):
        # "DELHI" is the NCT's name on every Delhi filing, not a locality, so it
        # is dropped and the one real place in the address is what survives.
        locality = _parsed("DWARKA, DELHI", district="South West Delhi")

        assert locality.name == "Dwarka"
        assert locality.slug == "dwarka"

    def test_an_address_that_is_only_the_state_is_refused(self):
        assert _refused("DELHI", district="New Delhi") == REASON_NO_COMPONENT

    def test_a_locality_beside_its_postal_code_is_still_read(self):
        locality = _parsed("GOLF COURSE ROAD, GURUGRAM - 122002")

        assert locality.name == "Golf Course Road"
        assert locality.slug == "golf-course-road"

    def test_a_missing_location_is_refused(self):
        assert _refused(None) == REASON_NO_LOCATION
        assert _refused("   ") == REASON_NO_LOCATION

    def test_a_location_without_a_district_is_refused(self):
        parse = derive_locality("SECTOR 76/77", district=None)

        assert parse.locality is None


class TestBuildRecords:
    def test_two_filings_naming_the_same_sector_collapse_to_one_record(self):
        records, coverage = build_records(
            [
                {"district": DISTRICT, "location": "SECTOR 76/77", "project_count": 1},
                {"district": DISTRICT, "location": "Sector 76 / 77", "project_count": 1},
            ]
        )

        assert len(records) == 1
        assert records[0]["slug"] == "sector-76-77"
        assert coverage["micro_markets_derived"] == 1

    def test_the_same_sector_in_two_districts_is_two_records(self):
        records, _coverage = build_records(
            [
                {"district": "Gurugram", "location": "SECTOR 45", "project_count": 1},
                {"district": "Faridabad", "location": "SECTOR 45", "project_count": 1},
            ]
        )

        assert {(record["city"], record["slug"]) for record in records} == {
            ("gurugram", "sector-45"),
            ("faridabad", "sector-45"),
        }

    def test_city_and_district_hold_the_same_lowercased_district(self):
        """The stored identity, not the filed spelling.

        ``uq_micro_markets_city_slug`` is case-sensitive while the read side
        lowercases the ``{city}`` URL segment, so the writer must store one
        spelling per place or one place gets two rows that both match one URL.
        """
        records, _coverage = build_records(
            [{"district": DISTRICT, "location": "SECTOR 45", "project_count": 1}]
        )

        assert records[0]["city"] == "gurugram"
        assert records[0]["district"] == "gurugram"

    def test_two_spellings_of_one_district_are_one_record(self):
        """``Gurugram`` and ``gurugram`` are one place, so one row and one page."""
        records, coverage = build_records(
            [
                {"district": "Gurugram", "location": "SECTOR 45", "project_count": 1},
                {"district": "gurugram", "location": "SECTOR 45", "project_count": 2},
                {"district": " GURUGRAM ", "location": "Sector 45", "project_count": 3},
            ]
        )

        assert len(records) == 1
        assert coverage["micro_markets_derived"] == 1
        assert records[0]["city"] == "gurugram"
        assert records[0]["district"] == "gurugram"
        # The prose still names the district the way a reader expects it.
        assert records[0]["summary"] == (
            "Derived from 6 RERA filings in Gurugram that name Sector 45."
        )

    def test_an_unparseable_location_produces_no_record_and_is_counted(self):
        records, coverage = build_records(
            [
                {"district": DISTRICT, "location": "SECTOR 76/77", "project_count": 1},
                {
                    "district": DISTRICT,
                    "location": "PLOT NO 12, KHASRA NO 45/2",
                    "project_count": 3,
                },
            ]
        )

        assert [record["slug"] for record in records] == ["sector-76-77"]
        assert coverage["pairs_checked"] == 2
        assert coverage["pairs_skipped"] == 1
        assert coverage["skip_reasons"] == {REASON_NO_COMPONENT: 1}
        assert coverage["projects_skipped"] == 3

    def test_every_skip_carries_a_reason_that_sums_to_the_skip_count(self):
        _records, coverage = build_records(
            [
                {"district": DISTRICT, "location": None, "project_count": 1},
                {"district": DISTRICT, "location": "SECTOR 45, SECTOR 46", "project_count": 1},
                {"district": DISTRICT, "location": "GURUGRAM", "project_count": 1},
                {"district": DISTRICT, "location": "SECTOR 45", "project_count": 2},
            ]
        )

        assert coverage["pairs_skipped"] == 3
        assert sum(coverage["skip_reasons"].values()) == coverage["pairs_skipped"]
        assert coverage["shape_breakdown"] == {SHAPE_SECTOR: 1}
        assert coverage["projects_covered"] == 2

    def test_the_summary_counts_only_the_filings_that_named_the_locality(self):
        records, _coverage = build_records(
            [
                {"district": DISTRICT, "location": "SECTOR 76/77", "project_count": 1},
                {"district": DISTRICT, "location": "Sector 76/77", "project_count": 2},
            ]
        )

        assert records[0]["summary"] == (
            "Derived from 3 RERA filings in Gurugram that name Sector 76/77."
        )

    def test_the_summary_is_singular_for_one_filing(self):
        records, _coverage = build_records(
            [{"district": DISTRICT, "location": "SECTOR 76/77", "project_count": 1}]
        )

        assert records[0]["summary"] == (
            "Derived from 1 RERA filing in Gurugram that names Sector 76/77."
        )

    def test_coordinates_are_never_derived(self):
        records, _coverage = build_records(
            [
                {"district": DISTRICT, "location": "SECTOR 76/77", "project_count": 1},
                {"district": DISTRICT, "location": "GOLF COURSE ROAD", "project_count": 1},
            ]
        )

        assert len(records) == 2
        assert all(record["latitude"] is None for record in records)
        assert all(record["longitude"] is None for record in records)


class TestCollectReadsTheRegister:
    async def test_two_projects_in_one_sector_are_one_micro_market(self, db_session):
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-MARKET-1",
                    project_name="Market One",
                    district="Gurugram",
                    location="SECTOR 76/77",
                ),
                # The same place, written the way another filing wrote it.
                ReraProject(
                    rera_number="TEST-MARKET-2",
                    project_name="Market Two",
                    district="Gurugram",
                    location="Sector 76 / 77",
                ),
            ]
        )
        await db_session.flush()

        scraper = MicroMarketScraper()
        records, coverage = await scraper._collect(db_session)

        assert [record["slug"] for record in records] == ["sector-76-77"]
        assert coverage["pairs_checked"] == 2
        assert coverage["micro_markets_derived"] == 1
        assert await scraper._upsert(db_session, records) == {
            "found": 1,
            "upserted": 1,
            "failed": 0,
        }

        rows = (await db_session.execute(select(MicroMarket))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "Sector 76/77"
        assert rows[0].city == "gurugram"
        assert rows[0].district == "gurugram"
        assert rows[0].latitude is None
        assert rows[0].longitude is None

    async def test_the_same_sector_in_two_districts_is_two_rows(self, db_session):
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-MARKET-3",
                    project_name="Market Three",
                    district="Gurugram",
                    location="SECTOR 45",
                ),
                ReraProject(
                    rera_number="TEST-MARKET-4",
                    project_name="Market Four",
                    district="Faridabad",
                    location="SECTOR 45",
                ),
            ]
        )
        await db_session.flush()

        scraper = MicroMarketScraper()
        records, _coverage = await scraper._collect(db_session)
        await scraper._upsert(db_session, records)

        rows = (await db_session.execute(select(MicroMarket).order_by(MicroMarket.city))).scalars().all()
        assert [(row.city, row.slug) for row in rows] == [
            ("faridabad", "sector-45"),
            ("gurugram", "sector-45"),
        ]

    async def test_a_location_that_cannot_be_read_writes_no_row(self, db_session):
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-MARKET-5",
                    project_name="Market Five",
                    district="Gurugram",
                    location="SECTOR 76/77",
                ),
                ReraProject(
                    rera_number="TEST-MARKET-6",
                    project_name="Market Six",
                    district="Gurugram",
                    location="PLOT NO 12, KHASRA NO 45/2",
                ),
            ]
        )
        await db_session.flush()

        scraper = MicroMarketScraper()
        records, coverage = await scraper._collect(db_session)
        await scraper._upsert(db_session, records)

        rows = (await db_session.execute(select(MicroMarket))).scalars().all()
        assert len(rows) == 1
        assert coverage["pairs_skipped"] == 1
        assert coverage["skip_reasons"] == {REASON_NO_COMPONENT: 1}
        assert coverage["pair_limit_reached"] is False

    async def test_a_re_run_updates_rather_than_duplicating(self, db_session):
        first = ReraProject(
            rera_number="TEST-MARKET-7",
            project_name="Market Seven",
            district="Gurugram",
            location="SECTOR 76/77",
        )
        db_session.add(first)
        await db_session.flush()

        scraper = MicroMarketScraper()
        records, _coverage = await scraper._collect(db_session)
        await scraper._upsert(db_session, records)

        db_session.add(
            ReraProject(
                rera_number="TEST-MARKET-8",
                project_name="Market Eight",
                district="Gurugram",
                location="SECTOR 76/77",
            )
        )
        await db_session.flush()

        second_records, _coverage = await scraper._collect(db_session)
        assert await scraper._upsert(db_session, second_records) == {
            "found": 1,
            "upserted": 1,
            "failed": 0,
        }

        rows = (await db_session.execute(select(MicroMarket))).scalars().all()
        assert len(rows) == 1
        assert rows[0].summary == (
            "Derived from 2 RERA filings in Gurugram that name Sector 76/77."
        )


class TestProjectLinks:
    """Each project is attached to the market its own address names.

    The read side counts a market's projects by this link. Before it existed the
    count was scoped by district, so two localities in one district reported the
    same number under two different names — a false claim on a public page.
    """

    async def _run_once(self, db_session) -> dict:
        scraper = MicroMarketScraper()
        # In production _scrape runs first and leaves the run's coverage dict here;
        # the link counts land in it. Driving _collect/_upsert directly mirrors that
        # ordering without the session factory _scrape needs.
        scraper._coverage = {}
        records, _coverage = await scraper._collect(db_session)
        await scraper._upsert(db_session, records)
        return scraper._coverage

    async def test_a_project_is_linked_to_the_market_its_address_names(self, db_session):
        db_session.add(
            ReraProject(
                rera_number="TEST-LINK-1",
                project_name="Link One",
                district="Gurugram",
                location="SECTOR 76/77",
            )
        )
        await db_session.flush()

        await self._run_once(db_session)

        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-LINK-1")
            )
        ).scalar_one()
        market = (await db_session.execute(select(MicroMarket))).scalar_one()
        assert project.micro_market_id == market.id

    async def test_two_localities_in_one_district_do_not_share_projects(self, db_session):
        """The bug this link exists to prevent, pinned directly.

        Both projects are in Gurugram. Before the link, whichever market you asked
        for counted both.
        """
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-LINK-2",
                    project_name="Link Two",
                    district="Gurugram",
                    location="SECTOR 76/77",
                ),
                ReraProject(
                    rera_number="TEST-LINK-3",
                    project_name="Link Three",
                    district="Gurugram",
                    location="GOLF COURSE ROAD",
                ),
            ]
        )
        await db_session.flush()

        await self._run_once(db_session)

        by_slug = {
            market.slug: market.id
            for market in (await db_session.execute(select(MicroMarket))).scalars().all()
        }
        assert set(by_slug) == {"sector-76-77", "golf-course-road"}
        links = {
            row.rera_number: row.micro_market_id
            for row in (await db_session.execute(select(ReraProject))).scalars().all()
        }
        assert links["TEST-LINK-2"] == by_slug["sector-76-77"]
        assert links["TEST-LINK-3"] == by_slug["golf-course-road"]

    async def test_an_unreadable_address_is_linked_to_nothing(self, db_session):
        """A refusal derives to no market, so the link must be null, not a guess."""
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-LINK-4",
                    project_name="Link Four",
                    district="Gurugram",
                    location="SECTOR 76/77",
                ),
                ReraProject(
                    rera_number="TEST-LINK-5",
                    project_name="Link Five",
                    district="Gurugram",
                    location="PLOT NO 12, KHASRA NO 45/2",
                ),
            ]
        )
        await db_session.flush()

        coverage = await self._run_once(db_session)

        links = {
            row.rera_number: row.micro_market_id
            for row in (await db_session.execute(select(ReraProject))).scalars().all()
        }
        assert links["TEST-LINK-4"] is not None
        assert links["TEST-LINK-5"] is None
        assert coverage["projects_linked"] == 1
        assert coverage["projects_without_a_readable_locality"] == 1

    async def test_a_relocated_project_loses_its_old_market(self, db_session):
        """The link must equal the derivation, so a corrected address moves it."""
        project = ReraProject(
            rera_number="TEST-LINK-6",
            project_name="Link Six",
            district="Gurugram",
            location="SECTOR 76/77",
        )
        db_session.add(project)
        await db_session.flush()
        await self._run_once(db_session)

        project.location = "GOLF COURSE ROAD"
        await db_session.flush()
        await self._run_once(db_session)

        await db_session.refresh(project)
        market = (
            await db_session.execute(
                select(MicroMarket).where(MicroMarket.slug == "golf-course-road")
            )
        ).scalar_one()
        assert project.micro_market_id == market.id

    async def test_a_project_with_no_location_is_linked_to_nothing(self, db_session):
        db_session.add(
            ReraProject(
                rera_number="TEST-LINK-7",
                project_name="Link Seven",
                district="Gurugram",
                location=None,
            )
        )
        await db_session.flush()

        coverage = await self._run_once(db_session)

        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-LINK-7")
            )
        ).scalar_one()
        assert project.micro_market_id is None
        assert coverage["projects_without_a_readable_locality"] == 1

    async def test_a_run_that_derives_nothing_still_clears_stale_links(self, db_session):
        """The link is read back from the table, so it survives an empty run.

        Keying off this run's own derived records would skip the repair entirely
        when a parser change makes every address unreadable — leaving projects
        pointing at markets their addresses no longer name.
        """
        db_session.add(
            ReraProject(
                rera_number="TEST-LINK-8",
                project_name="Link Eight",
                district="Gurugram",
                location="SECTOR 76/77",
            )
        )
        await db_session.flush()
        await self._run_once(db_session)

        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-LINK-8")
            )
        ).scalar_one()
        assert project.micro_market_id is not None

        # The address becomes one the parser must refuse.
        project.location = "PLOT NO 12, KHASRA NO 45/2"
        await db_session.flush()
        coverage = await self._run_once(db_session)

        await db_session.refresh(project)
        assert project.micro_market_id is None
        assert coverage["projects_linked"] == 0
        assert coverage["projects_without_a_readable_locality"] == 1

    async def test_one_district_spelled_two_ways_is_one_market(self, db_session):
        """Two filings, one place: one row, and both projects on it.

        ``uq_micro_markets_city_slug`` is case-sensitive while the read side
        lowercases the ``{city}`` URL segment, so a writer that stored the filed
        spelling verbatim gave one place two rows — two public pages for one
        locality showing different numbers.
        """
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-CASE-1",
                    project_name="Case One",
                    district="Gurugram",
                    location="SECTOR 45",
                ),
                ReraProject(
                    rera_number="TEST-CASE-2",
                    project_name="Case Two",
                    district="gurugram",
                    location="SECTOR 45",
                ),
            ]
        )
        await db_session.flush()

        scraper = MicroMarketScraper()
        scraper._coverage = {}
        records, coverage = await scraper._collect(db_session)

        assert len(records) == 1
        assert coverage["micro_markets_derived"] == 1

        await scraper._upsert(db_session, records)

        rows = (await db_session.execute(select(MicroMarket))).scalars().all()
        assert [(row.city, row.slug) for row in rows] == [("gurugram", "sector-45")]
        assert rows[0].summary == (
            "Derived from 2 RERA filings in Gurugram that name Sector 45."
        )
        # The one row carries both projects, so neither spelling loses its numbers.
        assert scraper._coverage["projects_linked"] == 2

    async def test_the_link_lookup_is_case_insensitive_in_both_directions(self, db_session):
        """The linker agrees with the reader about identity, not about case.

        A market written before the normalisation (``Gurugram``) and a project
        filed in either spelling must still find each other, so the fix does not
        strand a table that has not been normalised yet.
        """
        db_session.add(
            MicroMarket(city="Gurugram", name="Sector 45", slug="sector-45", district="Gurugram")
        )
        db_session.add_all(
            [
                ReraProject(
                    rera_number="TEST-CASE-3",
                    project_name="Case Three",
                    district="gurugram",
                    location="SECTOR 45",
                ),
                ReraProject(
                    rera_number="TEST-CASE-4",
                    project_name="Case Four",
                    district="GURUGRAM",
                    location="SECTOR 45",
                ),
                # The refusal invariant must survive the normalisation: an address
                # that names no locality is still NULL, never a nearby guess.
                ReraProject(
                    rera_number="TEST-CASE-4B",
                    project_name="Case Four B",
                    district="gurugram",
                    location="PLOT NO 12, KHASRA NO 45/2",
                ),
            ]
        )
        await db_session.flush()

        scraper = MicroMarketScraper()
        scraper._coverage = {}
        coverage = await scraper._link_projects(db_session)

        market = (await db_session.execute(select(MicroMarket))).scalar_one()
        links = {
            row.rera_number: row.micro_market_id
            for row in (await db_session.execute(select(ReraProject))).scalars().all()
        }
        assert links == {
            "TEST-CASE-3": market.id,
            "TEST-CASE-4": market.id,
            "TEST-CASE-4B": None,
        }
        assert coverage["projects_linked"] == 2
        assert coverage["projects_without_a_readable_locality"] == 1

    async def test_a_duplicate_pair_of_rows_links_to_the_row_the_reader_serves(self, db_session):
        """When two rows do exist, the link must point at the one the page shows.

        The read side takes the lowest id for a city/slug, so the linker takes the
        same row; otherwise the page and the numbers under it disagree. The filed
        district here matches neither stored spelling exactly, which is what makes
        the identity a case question rather than a string question.
        """
        db_session.add_all(
            [
                MicroMarket(
                    city="Gurugram", name="Sector 45", slug="sector-45", district="Gurugram"
                ),
                MicroMarket(
                    city="gurugram", name="Sector 45", slug="sector-45", district="gurugram"
                ),
            ]
        )
        db_session.add(
            ReraProject(
                rera_number="TEST-CASE-5",
                project_name="Case Five",
                district="GURUGRAM",
                location="SECTOR 45",
            )
        )
        await db_session.flush()

        scraper = MicroMarketScraper()
        await scraper._link_projects(db_session)

        served = (
            await db_session.execute(
                select(MicroMarket).order_by(MicroMarket.id).limit(1)
            )
        ).scalar_one()
        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-CASE-5")
            )
        ).scalar_one()
        assert project.micro_market_id == served.id


class TestLinkFailureIsNotASuccess:
    """A link step that explodes must not leave the run recorded as ``success``.

    ``_upsert`` reports the write counts, and ``final_run_status`` turns those
    plus the scrape status into the one status ``_finish_run`` records — it is
    the only input to it (``base_scraper.run`` passes its result straight to
    ``_finish_run``). Counting the link failure in ``failed`` is what makes that
    status ``partial`` instead of the ``success`` it reported while every
    project's ``micro_market_id`` stayed ``NULL``.
    """

    async def test_a_failed_link_step_is_recorded_as_partial_not_success(self, db_session):
        db_session.add(
            ReraProject(
                rera_number="TEST-LINK-FAIL-1",
                project_name="Link Fail One",
                district="Gurugram",
                location="SECTOR 76/77",
            )
        )
        await db_session.flush()

        scraper = MicroMarketScraper()
        scraper._coverage = {}
        records, _coverage = await scraper._collect(db_session)
        scraper._link_projects = AsyncMock(side_effect=RuntimeError("link step exploded"))

        stats = await scraper._upsert(db_session, records)

        # Exactly the state the audit measured: the market row was written, the
        # link never happened, and nothing was reported as failed.
        assert stats["found"] == 1
        assert stats["upserted"] == 1
        assert stats["failed"] == 1
        assert scraper._coverage["project_link_failed"] == "RuntimeError"
        project = (
            await db_session.execute(
                select(ReraProject).where(ReraProject.rera_number == "TEST-LINK-FAIL-1")
            )
        ).scalar_one()
        assert project.micro_market_id is None

        # The register was read successfully, so the only honest status is a
        # partial one. The counterfactual is the old behaviour, pinned here so the
        # defect cannot come back silently.
        scrape_result = ScrapeResult(successful_sources=1)
        assert final_run_status(scrape_result, {**stats, "failed": 0}) == "success"
        assert final_run_status(scrape_result, stats) == "partial"


class TestRightsGate:
    async def test_run_is_disabled_before_any_read(self, monkeypatch):
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        monkeypatch.setattr(
            "app.services.data_hub.base_scraper.get_bg_session_factory",
            MagicMock(side_effect=AssertionError("no run row may be created")),
        )
        scraper = MicroMarketScraper()
        scraper._scrape = AsyncMock(side_effect=AssertionError("no register read may happen"))

        result = await scraper.run(run_type="manual")

        assert result == {
            "status": "disabled",
            "run_id": None,
            "reason": "hrera_disabled_by_configuration",
        }
        scraper._scrape.assert_not_awaited()

    async def test_scrape_and_upsert_write_nothing_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        scraper = MicroMarketScraper()

        assert (await scraper._scrape()).records == []
        assert await scraper._upsert(MagicMock(), [{"city": DISTRICT, "slug": "sector-45"}]) == {
            "found": 0,
            "upserted": 0,
            "failed": 0,
        }
