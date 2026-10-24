"""Delhi RERA scraper: parser contract, completeness guards, and upsert gating.

Every parser assertion runs against markup captured from ``https://erera.co.in``
on 2026-10-24 and trimmed into ``tests/fixtures/delhi/``. No test touches the
network.

Two properties get more attention here than in a typical scraper test, because
both were the subject of a shipped bug on this surface:

* **The register is read whole or not at all.** A register that loses a row must
  not be written, because the write path cannot tell a partial register from a
  complete one.
* **No Delhi row may carry ``raw_data.portal_project_id``.** That key is under a
  unique partial index shared with HRERA, whose ids are in the same numeric
  namespace. The cross-portal collision itself is proven in
  ``tests/integration/services/test_delhi_rera_write.py``; here the parse-level
  half of it is pinned.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bs4 import BeautifulSoup

from app.config import settings
from app.services.data_hub import delhi_rera_projects as delhi_module
from app.services.data_hub.delhi_rera_projects import (
    DELHI_SEARCH_REQUIRES_CAPTCHA,
    DelhiReraProjectScraper,
    _apply_detail,
    _collapse_address,
    parse_project_detail_html,
    parse_registered_projects_html,
)

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "delhi"
REGISTER_FIXTURE = FIXTURE_DIR / "registered_projects.html"
DETAIL_FIXTURE = FIXTURE_DIR / "project_detail_10143.html"
INDIVIDUAL_DETAIL_FIXTURE = FIXTURE_DIR / "project_detail_10154_individual.html"

# The fixture keeps 17 of the live register's 133 rows, chosen so that every
# district, every project type, both promoter types, and the three rows with no
# certificate are represented. Every count below is a fact about the captured
# markup, not about the live register.
FIXTURE_ROWS = 17
REGISTER_URL = "https://erera.co.in/reradelhiindex/PublicView/RegisteredProjectDetail"

# The eleven districts the live register names. The register does *not* name ten:
# Shahdara is a Delhi district in its own right and three live rows file against
# it, so a parser that knows ten districts is dropping a district.
DELHI_DISTRICTS = frozenset(
    {
        "Central Delhi",
        "East Delhi",
        "New Delhi",
        "North Delhi",
        "North East Delhi",
        "North West Delhi",
        "Shahdara",
        "South Delhi",
        "South East Delhi",
        "South West Delhi",
        "West Delhi",
    }
)

# The first register row, read from the live capture by hand so the parser is
# checked against the page rather than against itself.
BHARAT_ID = "10143"
BHARAT_PROMOTER_ID = "1153"
BHARAT_PROMOTER_TYPE = "2"
BHARAT_NUMBER = "DLRERA2026P0005"
BHARAT_CERTIFICATE_RAW = (
    "https://erera.co.in/delhirera/readwritePRJCert\\10143\\/"
    "PRJcert_20261023a5920056-07c2-42fc-b0cb-34ff20f2fd62.pdf"
)


@pytest.fixture(scope="module")
def register_html() -> str:
    return REGISTER_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def records(register_html: str) -> list[dict]:
    return parse_registered_projects_html(register_html).records


@pytest.fixture(scope="module")
def bharat(records: list[dict]) -> dict:
    return next(r for r in records if r["raw_data"]["delhi_project_id"] == BHARAT_ID)


def _first_row_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="dataTableSearchProject")
    return str(table.find("tbody").find("tr", recursive=False))


def _single_row_page(row_html: str) -> str:
    """One real register row inside the smallest page that carries it.

    The shell is written here; the row is the captured markup, so a case that the
    live register does not happen to contain (a blank district cell) is still
    tested against the portal's own cell structure rather than an invented one.
    """
    return (
        "<html><body>"
        '<table id="dataTableSearchProject"><tbody>'
        f"{row_html}"
        "</tbody></table>"
        "</body></html>"
    )


def _mirror_without_its_last_row(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("table", id="dataTableSearchQUpdatesProject").find("tbody")
    body.find_all("tr", recursive=False)[-1].extract()
    return str(soup)


class TestRegisterParser:
    def test_every_register_row_becomes_a_record(self, register_html: str) -> None:
        parsed = parse_registered_projects_html(register_html)

        assert parsed.errors == []
        assert len(parsed.records) == FIXTURE_ROWS
        assert parsed.coverage == {
            "register_rows": FIXTURE_ROWS,
            "mirror_rows": FIXTURE_ROWS,
            "records_parsed": FIXTURE_ROWS,
            "rows_refused": 0,
        }

    def test_all_eleven_delhi_districts_are_read(self, records: list[dict]) -> None:
        assert {record["district"] for record in records} == DELHI_DISTRICTS

    def test_the_first_row_matches_the_captured_markup(self, bharat: dict) -> None:
        assert bharat["rera_number"] == BHARAT_NUMBER
        assert bharat["project_name"] == "Bharat Business Park"
        assert bharat["district"] == "South West Delhi"
        assert bharat["project_type"] == "Commercial"
        assert bharat["expiry_date"] == date(2031, 2, 18)
        assert bharat["status"] == "registered"
        # The register publishes no registration date, so the column is not
        # written at all rather than being inferred from the year inside the
        # number.
        assert "registration_date" not in bharat
        assert bharat["slug"] == "bharat-business-park-dlrera2026p0005"

    def test_the_identity_triple_addresses_the_filing(self, bharat: dict) -> None:
        raw = bharat["raw_data"]

        assert raw["delhi_project_id"] == BHARAT_ID
        assert raw["promoter_id"] == BHARAT_PROMOTER_ID
        assert raw["promoter_type"] == BHARAT_PROMOTER_TYPE
        assert raw["detail_url"] == (
            "https://erera.co.in/reradelhiindex/PublicView/ProjectViewDetails"
            f"?inProject_ID={BHARAT_ID}&inPromoter_ID={BHARAT_PROMOTER_ID}"
            f"&inPromoterType={BHARAT_PROMOTER_TYPE}"
        )
        assert bharat["source_url"] == raw["detail_url"]

    def test_the_registration_number_is_the_portals_own(self, records: list[dict]) -> None:
        """Unlike HRERA, the register states the assigned number, and it is real."""
        numbers = [record["rera_number"] for record in records]

        assert len(set(numbers)) == len(numbers)
        assert all(number.startswith("DLRERA") for number in numbers)
        assert BHARAT_NUMBER in numbers

    def test_valid_upto_dates_are_parsed_as_day_month_name_year(self, records: list[dict]) -> None:
        """The register writes ``18-Feb-2031``; a month-first read would fail here."""
        parsed = {record["rera_number"]: record["expiry_date"] for record in records}

        assert parsed[BHARAT_NUMBER] == date(2031, 2, 18)
        assert all(isinstance(value, date) for value in parsed.values())
        assert all(value.year >= 2020 for value in parsed.values())

    def test_project_type_is_the_portals_own_spelling(self, records: list[dict]) -> None:
        """A multi-type project keeps the register's comma list, not a first word."""
        types = {record["project_type"] for record in records}

        assert "Commercial, Industrial, Residential" in types
        assert "Commercial, Residential" in types
        assert "Group Housing" in types
        assert "Mixed Project" in types

    def test_the_certificate_href_is_normalised_and_kept_verbatim(self, bharat: dict) -> None:
        """The portal writes backslashes in the path; a client needs slashes."""
        raw = bharat["raw_data"]

        assert raw["certificate_href_raw"] == BHARAT_CERTIFICATE_RAW
        assert "\\" not in raw["certificate_url"]
        assert raw["certificate_url"] == BHARAT_CERTIFICATE_RAW.replace("\\", "/")
        # Both forms answer HTTP 200 with a PDF; only the normalised one is safe
        # to hand to a strict client.
        assert raw["certificate_url"].endswith(".pdf")

    def test_a_row_without_a_certificate_keeps_a_null_certificate(self, records: list[dict]) -> None:
        """Three live rows publish no certificate. That is a null, not a dropped row."""
        missing = [
            record["rera_number"]
            for record in records
            if record["raw_data"]["certificate_url"] is None
        ]

        assert missing == ["DLRERA2022P0041", "DLRERA2022P0033", "DLRERA2021P0004"]
        assert len(records) == FIXTURE_ROWS

    def test_no_record_carries_a_portal_project_id(self, records: list[dict]) -> None:
        """The key HRERA's unique partial index is built on stays empty on Delhi rows.

        Writing Delhi's id there would let an HRERA id-range walk reach the same
        number and overwrite the Delhi row with Haryana data. The integration test
        stores both under the same number and asserts both survive.
        """
        for record in records:
            assert "portal_project_id" not in record["raw_data"]
            assert record["raw_data"]["portal"] == "delhi_rera"

    def test_the_promoter_annotation_is_split_out_of_the_developer_name(
        self, bharat: dict
    ) -> None:
        """``NBCC (India) Limited (Other than Individual)`` is a name plus a type."""
        assert bharat["developer_name"] == "NBCC (India) Limited"
        assert bharat["developer_slug"] == "nbcc-india-limited"
        assert bharat["raw_data"]["promoter_name_raw"] == (
            "NBCC (India) Limited (Other than Individual)"
        )
        assert bharat["raw_data"]["promoter_type"] == "2"

    def test_an_individual_promoter_is_read_too(self, records: list[dict]) -> None:
        individuals = [r for r in records if r["raw_data"]["promoter_type"] == "1"]

        assert individuals
        for record in individuals:
            assert "Individual)" not in (record["developer_name"] or "")
            assert record["developer_slug"]

    def test_blank_district_falls_back_to_the_state(self, register_html: str) -> None:
        """A blank cell yields the state, never a district the row does not name.

        A fabricated district is not cosmetic: ``micro_market.py`` and
        ``market_pulse.py`` both use the district as the city, so a mislabeled
        project inflates one city's count and vanishes from its real one.
        """
        row = _first_row_html(register_html).replace("<td>South West Delhi</td>", "<td></td>")
        assert "South West Delhi" not in row

        parsed = parse_registered_projects_html(_single_row_page(row))

        assert parsed.errors == []
        assert parsed.records[0]["district"] == "Delhi"

    def test_a_page_without_the_register_table_fails_loudly(self) -> None:
        parsed = parse_registered_projects_html("<html><body><p>maintenance</p></body></html>")

        assert parsed.records == []
        assert [error["error_type"] for error in parsed.errors] == [
            "ExpectedRegisterTableNotFound"
        ]

    def test_an_empty_register_table_fails_loudly(self) -> None:
        parsed = parse_registered_projects_html(
            '<html><body><table id="dataTableSearchProject"><tbody></tbody></table></body></html>'
        )

        assert parsed.records == []
        assert [error["error_type"] for error in parsed.errors] == ["EmptyRegisterTable"]

    def test_a_truncated_document_writes_nothing(self, register_html: str) -> None:
        """A response cut off mid-stream must not be written as a shorter register.

        This is the shipped-bug shape: a 3822-row grid read as 2315 rows and
        reported as a success. The rows above the cut parse fine, which is exactly
        why the cut has to be detected from the document and not from the records.
        """
        truncated = register_html.split('id="dataTableSearchQUpdatesProject"')[0]

        parsed = parse_registered_projects_html(truncated)

        assert parsed.records == []
        assert [error["error_type"] for error in parsed.errors] == [
            "RegisterDocumentTruncated"
        ]
        assert "did not end with" in parsed.errors[0]["message"]

    def test_a_second_copy_that_disagrees_writes_nothing(self, register_html: str) -> None:
        """The document renders the register twice; disagreement means a bad read."""
        parsed = parse_registered_projects_html(_mirror_without_its_last_row(register_html))

        assert parsed.records == []
        assert [error["error_type"] for error in parsed.errors] == ["RegisterCopiesDisagree"]

    def test_a_row_that_cannot_state_its_identity_is_refused(self, register_html: str) -> None:
        row = _first_row_html(register_html)
        broken = row.replace('<td class="project-name" data-project-name="Bharat Business Park">', "<td>")
        assert "data-project-name" not in broken

        parsed = parse_registered_projects_html(_single_row_page(broken))

        assert parsed.records == []
        assert {error["error_type"] for error in parsed.errors} == {"RegisterRowNotParsed"}
        assert any("no td.project-name" in error["message"] for error in parsed.errors)
        assert all("row 1" in error["message"] for error in parsed.errors)

    def test_one_unreadable_row_does_not_ship_a_shorter_register(self, register_html: str) -> None:
        """The whole point of the guard: 16 good rows are not a 17-row register."""
        broken = register_html.replace(
            '<td class="project-name" data-project-name="Bharat Business Park">', "<td>"
        )
        assert broken != register_html

        parsed = parse_registered_projects_html(broken)

        assert parsed.records == []
        assert parsed.coverage["register_rows"] == FIXTURE_ROWS
        assert parsed.coverage["records_parsed"] == 0


class TestAddressNormalisation:
    """The portal renders each part as ``<label>:&#160;<value>`` and leaves the
    separator behind when the label is empty, so a faithful read still needs the
    artifact dropped. Both cases below are the shape the live pages serve."""

    def test_a_leading_separator_is_not_part_of_the_address(self) -> None:
        # Project DLRERA2021P0005 renders its address cell as ":&nbsp;DELHI
        # MUNICIPAL PRESS...", so the colon survives the text extraction.
        value = (
            ":\xa0DELHI MUNICIPAL PRESS C.G.H.S LTD. PLOT NO.29A, SECTOR-10, "
            ", DWARKA, NEW DELHI-110075"
        )

        assert _collapse_address(value) == (
            "DELHI MUNICIPAL PRESS C.G.H.S LTD. PLOT NO.29A, SECTOR-10, "
            "DWARKA, NEW DELHI-110075"
        )

    def test_an_empty_part_does_not_leave_a_double_comma(self) -> None:
        assert _collapse_address("SECTOR-10, , DWARKA") == "SECTOR-10, DWARKA"

    def test_a_clean_address_is_unchanged(self) -> None:
        # The comma shape is load-bearing: derive_locality splits on commas.
        assert _collapse_address(
            "Bharat Business Park , Ring Road Dwarka , South West Delhi , Delhi - 110023"
        ) == "Bharat Business Park, Ring Road Dwarka, South West Delhi, Delhi - 110023"

    def test_an_address_that_is_only_separators_is_no_address(self) -> None:
        assert _collapse_address(": , ,") is None


class TestDetailParser:
    def test_the_filing_supplies_the_address_land_and_units(self) -> None:
        detail = parse_project_detail_html(DETAIL_FIXTURE.read_text(encoding="utf-8"))

        assert detail.errors == ()
        assert detail.project_name == "Bharat Business Park"
        assert detail.address == (
            "Bharat Business Park, Ring Road Dwarka, South West Delhi, Delhi - 110023"
        )
        assert detail.land_area_sqm == Decimal("57184.17")

    def test_the_tower_inventory_is_summed_across_towers(self) -> None:
        """Eight towers, each with its own unit-type table, sum to the filed total."""
        detail = parse_project_detail_html(DETAIL_FIXTURE.read_text(encoding="utf-8"))

        assert detail.towers == 8
        assert detail.units_total == 78
        assert detail.inventory_parsed is True

    def test_the_declared_completion_date_is_read(self) -> None:
        detail = parse_project_detail_html(DETAIL_FIXTURE.read_text(encoding="utf-8"))

        assert detail.start_date == date(2025, 3, 22)
        assert detail.proposed_completion_date == date(2031, 2, 18)
        assert detail.project_status == "New Project"
        assert detail.project_cost_inr == Decimal("17212230489.00")

    def test_the_punjab_zone_label_is_kept_verbatim_and_never_used(self) -> None:
        """The Delhi instance inherited the Punjab template; its zone text is Punjab's.

        The label is recorded so a reader can see the portal's own answer, and it
        is never used to place a project: a zone naming Ludhiana says nothing about
        a Delhi filing.
        """
        detail = parse_project_detail_html(DETAIL_FIXTURE.read_text(encoding="utf-8"))

        assert detail.zone is not None
        assert "Ludhiana" in detail.zone
        record: dict = {"raw_data": {}}
        _apply_detail(record, detail)
        assert record["raw_data"]["detail"]["zone"] == detail.zone
        assert "Ludhiana" not in record.get("location", "")

    def test_the_filing_fills_only_what_the_register_does_not_state(self) -> None:
        detail = parse_project_detail_html(DETAIL_FIXTURE.read_text(encoding="utf-8"))
        record = {
            "district": "South West Delhi",
            "rera_number": BHARAT_NUMBER,
            "developer_name": "NBCC (India) Limited",
            "raw_data": {"portal": "delhi_rera"},
        }

        _apply_detail(record, detail)

        assert record["location"].startswith("Bharat Business Park")
        assert record["total_area_sqm"] == Decimal("57184.17")
        assert record["total_units"] == 78
        assert record["possession_date"] == date(2031, 2, 18)
        # The register stays the authority for the fields it states.
        assert record["district"] == "South West Delhi"
        assert record["rera_number"] == BHARAT_NUMBER
        assert record["developer_name"] == "NBCC (India) Limited"

    def test_the_filings_own_name_never_replaces_the_registers(self) -> None:
        """A filing names the same project differently; the register decides."""
        detail = parse_project_detail_html(INDIVIDUAL_DETAIL_FIXTURE.read_text(encoding="utf-8"))
        record = {"project_name": "21, RAJPUR ROAD, CIVIL LINES, DELHI", "raw_data": {}}

        _apply_detail(record, detail)

        assert record["project_name"] == "21, RAJPUR ROAD, CIVIL LINES, DELHI"
        assert record["raw_data"]["detail"]["project_name"] == detail.project_name

    def test_an_individual_filing_is_read(self) -> None:
        """An individual's filing labels its rows differently from a company's."""
        detail = parse_project_detail_html(INDIVIDUAL_DETAIL_FIXTURE.read_text(encoding="utf-8"))

        assert detail.errors == ()
        assert detail.promoter_name == "ADITYA VIKRAM BANSAL"
        assert detail.promoter_registered_address is None
        assert detail.land_area_sqm == Decimal("11747.49")
        assert detail.towers == 1
        assert detail.units_total == 13

    def test_no_contact_details_are_read(self) -> None:
        """The filing publishes phones and emails; nothing here carries them.

        They are personal data the register publishes for a different purpose, and
        no read path on this platform needs them.
        """
        detail = parse_project_detail_html(DETAIL_FIXTURE.read_text(encoding="utf-8"))
        record: dict = {"raw_data": {}}
        _apply_detail(record, detail)

        payload = repr(record["raw_data"]["detail"]).lower()
        for marker in ("email", "phone", "mobile", "e-mail", "@"):
            assert marker not in payload

    def test_a_page_without_the_about_section_reports_it(self) -> None:
        detail = parse_project_detail_html("<html><body><p>nothing</p></body></html>")

        assert [error["error_type"] for error in detail.errors] == ["DetailSectionNotFound"]
        assert detail.project_name is None
        assert detail.address is None
        assert detail.units_total is None
        assert detail.inventory_parsed is False

    def test_an_unreadable_inventory_is_not_a_project_with_no_units(self) -> None:
        """A missing column yields ``None``, not zero: those are different facts."""
        detail = parse_project_detail_html(
            "<html><body>"
            '<div class="view-detail-heading1">Project Building/ Tower/ Block Construction'
            " &amp; Inventory Details</div>"
            "<table><tbody><tr><td>1</td><td>TOWER 1</td><td>floors</td></tr></tbody></table>"
            "</body></html>"
        )

        assert detail.units_total is None
        assert detail.inventory_parsed is False
        assert detail.towers == 1

    def test_a_header_with_no_data_rows_is_not_zero_units(self) -> None:
        """Eight live Delhi filings render the unit column header and then no rows.

        A header match alone would publish ``0`` units for a project whose filing
        states nothing, and ``0`` renders as a fact on the project page while
        ``None`` renders as a dash. Project DLRERA2018P0013 is the live shape.
        """
        detail = parse_project_detail_html(
            "<html><body>"
            '<div class="view-detail-heading1">Project Building/ Tower/ Block Construction'
            " &amp; Inventory Details</div>"
            "<table><tbody>"
            "<tr><td>1</td><td>TOWER 1</td><td>floors</td></tr>"
            "<tr><td><table><tbody>"
            "<tr><td>Sr.No</td><td>Type of Apartment/ Shop/ Plot</td>"
            "<td>Total Number of Apartment/ Shop/ Plot</td></tr>"
            "</tbody></table></td></tr>"
            "</tbody></table>"
            "</body></html>"
        )

        assert detail.units_total is None
        assert detail.inventory_parsed is False
        assert detail.towers == 1

    def test_a_zero_the_filing_itself_states_is_kept(self) -> None:
        """The register's own ``0`` is its answer, not ours, so it is published."""
        detail = parse_project_detail_html(
            "<html><body>"
            '<div class="view-detail-heading1">Project Building/ Tower/ Block Construction'
            " &amp; Inventory Details</div>"
            "<table><tbody>"
            "<tr><td>1</td><td>TOWER 1</td><td>floors</td></tr>"
            "<tr><td><table><tbody>"
            "<tr><td>Sr.No</td><td>Type of Apartment/ Shop/ Plot</td>"
            "<td>Total Number of Apartment/ Shop/ Plot</td></tr>"
            "<tr><td>1</td><td>Floor 0 - 3bhk</td><td>0</td></tr>"
            "</tbody></table></td></tr>"
            "</tbody></table>"
            "</body></html>"
        )

        assert detail.units_total == 0
        assert detail.inventory_parsed is True

    def test_units_are_summed_across_a_tower_whose_table_is_empty(self) -> None:
        """An empty tower table contributes nothing but must not zero the total."""
        detail = parse_project_detail_html(
            "<html><body>"
            '<div class="view-detail-heading1">Project Building/ Tower/ Block Construction'
            " &amp; Inventory Details</div>"
            "<table><tbody>"
            "<tr><td>1</td><td>TOWER 1</td><td>floors</td></tr>"
            "<tr><td><table><tbody>"
            "<tr><td>Sr.No</td><td>Type of Apartment/ Shop/ Plot</td>"
            "<td>Total Number of Apartment/ Shop/ Plot</td></tr>"
            "</tbody></table></td></tr>"
            "<tr><td>2</td><td>TOWER 2</td><td>floors</td></tr>"
            "<tr><td><table><tbody>"
            "<tr><td>Sr.No</td><td>Type of Apartment/ Shop/ Plot</td>"
            "<td>Total Number of Apartment/ Shop/ Plot</td></tr>"
            "<tr><td>1</td><td>Floor 1 - 4bhk</td><td>12</td></tr>"
            "</tbody></table></td></tr>"
            "</tbody></table>"
            "</body></html>"
        )

        assert detail.units_total == 12
        assert detail.inventory_parsed is True
        assert detail.towers == 2


def _install_fetch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    register_html: str,
    details: dict[str, str] | None = None,
    fail_details: bool = False,
) -> list[str]:
    """Serve the captured pages instead of the network, and record what was asked for."""
    calls: list[str] = []
    payloads = details or {}

    async def fake_fetch(_self, url: str, **_kwargs) -> str:
        calls.append(url)
        if url == REGISTER_URL:
            return register_html
        if fail_details:
            raise RuntimeError("filing fetch failed")
        return payloads.get(url, DETAIL_FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(DelhiReraProjectScraper, "_fetch_url", fake_fetch)
    return calls


@pytest.fixture
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)


class TestScrape:
    async def test_the_register_is_hashed_into_its_source_key(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str, flag_on: None
    ) -> None:
        _install_fetch(monkeypatch, register_html=register_html)

        result = await DelhiReraProjectScraper()._scrape()

        register_document = result.source_documents[0]
        assert register_document["canonical_url"] == REGISTER_URL
        assert register_document["document_type"] == "registry_page"
        assert register_document["authority"] == "Real Estate Regulatory Authority, NCT of Delhi"
        assert register_document["source_key"] == (
            f"{REGISTER_URL}#{hashlib.sha256(register_html.encode('utf-8')).hexdigest()}"
        )

    async def test_each_filing_is_hashed_into_its_own_source_document(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str, flag_on: None
    ) -> None:
        _install_fetch(monkeypatch, register_html=register_html)

        result = await DelhiReraProjectScraper()._scrape()

        assert len(result.source_documents) == FIXTURE_ROWS + 1
        filings = [d for d in result.source_documents if d["document_type"] == "regulatory_filing"]
        assert len(filings) == FIXTURE_ROWS
        assert {d["canonical_url"] for d in filings} == {
            record["raw_data"]["detail_url"] for record in result.records
        }
        # Every record cites the filing document it was read from.
        assert {record["_source_key"] for record in result.records} == {
            d["source_key"] for d in filings
        }

    async def test_the_captcha_gated_search_is_never_posted_to(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str, flag_on: None
    ) -> None:
        """The register carries every registered project, so the search adds nothing."""
        calls = _install_fetch(monkeypatch, register_html=register_html)

        await DelhiReraProjectScraper()._scrape()

        assert calls[0] == REGISTER_URL
        assert not any("ProjectInfo" in url or "ProjectPVregd" in url for url in calls)
        assert delhi_module.DELHI_SEARCH_REQUIRES_CAPTCHA == DELHI_SEARCH_REQUIRES_CAPTCHA

    async def test_a_filing_that_fails_to_fetch_still_writes_the_register_row(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str, flag_on: None
    ) -> None:
        """A filing adds to a row; losing one must not lose the registration."""
        _install_fetch(monkeypatch, register_html=register_html, fail_details=True)

        result = await DelhiReraProjectScraper()._scrape()

        assert len(result.records) == FIXTURE_ROWS
        assert all(record["_source_key"].startswith(REGISTER_URL) for record in result.records)
        assert all("location" not in record for record in result.records)
        assert [error["stage"] for error in result.errors] == ["fetch"] * FIXTURE_ROWS
        assert result.source_coverage[0]["detail_pages_parsed"] == 0
        assert result.source_coverage[0]["status"] == "partial"

    async def test_a_register_that_does_not_parse_is_not_written(
        self, monkeypatch: pytest.MonkeyPatch, flag_on: None
    ) -> None:
        _install_fetch(monkeypatch, register_html="<html><body>maintenance</body></html>")

        result = await DelhiReraProjectScraper()._scrape()

        assert result.records == []
        assert result.source_coverage[0]["status"] == "failed"
        assert result.successful_sources == 0
        assert [error["error_type"] for error in result.errors] == [
            "ExpectedRegisterTableNotFound"
        ]

    async def test_a_fetch_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, flag_on: None
    ) -> None:
        async def failing_fetch(_self, _url: str, **_kwargs) -> str:
            raise TimeoutError("read timeout")

        monkeypatch.setattr(DelhiReraProjectScraper, "_fetch_url", failing_fetch)

        result = await DelhiReraProjectScraper()._scrape()

        assert result.records == []
        assert [error["stage"] for error in result.errors] == ["fetch"]
        assert result.source_coverage[0]["pages_attempted"] == 1
        assert result.source_coverage[0]["pages_checked"] == 0

    async def test_the_flag_turns_the_scrape_off(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False)
        calls = _install_fetch(monkeypatch, register_html=register_html)

        result = await DelhiReraProjectScraper()._scrape()

        assert result.records == []
        assert calls == []

    async def test_run_stops_before_creating_a_run_row_when_the_flag_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False)

        outcome = await DelhiReraProjectScraper().run()

        assert outcome["status"] == "disabled"
        assert outcome["run_id"] is None


def _db_claiming_the_row() -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = 1
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.begin_nested = MagicMock(return_value=nested)
    return db


def _capturing_db() -> MagicMock:
    """A db that records every statement, and the order it ran in.

    ``scalar_one_or_none`` returns a row id, so the register upsert reports the
    project as claimed and the provenance resolver reports a document id. The
    transaction markers go into the same list as the statements, which is what
    lets a test assert the filing was written *inside* the register's transaction
    rather than after it.
    """
    events: list[object] = []
    result = MagicMock()
    result.scalar_one_or_none.return_value = 1

    async def _execute(statement: object, *args: object, **kwargs: object) -> MagicMock:
        events.append(statement)
        return result

    nested = MagicMock()
    nested.__aenter__ = AsyncMock(side_effect=lambda: events.append("begin") or None)
    nested.__aexit__ = AsyncMock(side_effect=lambda *a: events.append("end") or False)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.begin_nested = MagicMock(return_value=nested)
    db.events = events
    return db


def _insert_into(db: MagicMock, table: str) -> object:
    """The one insert this run issued against ``table``."""
    for event in db.events:
        target = getattr(event, "table", None)
        if target is not None and target.name == table:
            return event
    raise AssertionError(f"no insert into {table} was issued")


def _insert_into_or_none(db: MagicMock, table: str) -> object | None:
    for event in db.events:
        target = getattr(event, "table", None)
        if target is not None and target.name == table:
            return event
    return None


def _stage_of(values: dict[str, object]) -> object:
    """The stage as the column stores it, whether the enum or its value binds."""
    return getattr(values["stage"], "value", values["stage"])


class TestUpsert:
    def test_scraper_declares_its_name_and_needs_no_browser(self) -> None:
        assert DelhiReraProjectScraper.name == "delhi_rera_projects"
        # Both pages are server-rendered, so no Chromium is launched for Delhi.
        assert DelhiReraProjectScraper.requires_playwright is False

    async def test_every_parsed_record_is_written(self, records: list[dict], flag_on: None) -> None:
        batch = [dict(record) for record in records]
        for record in batch:
            record["_source_checked_at"] = datetime.now(UTC)

        stats = await DelhiReraProjectScraper()._upsert(_db_claiming_the_row(), batch)

        assert stats == {"found": FIXTURE_ROWS, "upserted": FIXTURE_ROWS, "failed": 0}
        assert all(record["_upsert_succeeded"] for record in batch)

    async def test_record_without_a_source_timestamp_is_counted_failed(
        self, records: list[dict], flag_on: None
    ) -> None:
        batch = [dict(records[0])]

        stats = await DelhiReraProjectScraper()._upsert(_db_claiming_the_row(), batch)

        assert stats == {"found": 1, "upserted": 0, "failed": 1}
        assert batch[0]["_upsert_succeeded"] is False

    async def test_a_row_the_conflict_guard_rejects_is_not_counted_written(
        self, records: list[dict], flag_on: None
    ) -> None:
        """The guard returns no id when a newer read already landed, which is a skip."""
        db = _db_claiming_the_row()
        db.execute.return_value.scalar_one_or_none.return_value = None
        record = dict(records[0])
        record["_source_checked_at"] = datetime.now(UTC)

        stats = await DelhiReraProjectScraper()._upsert(db, [record])

        assert stats == {"found": 1, "upserted": 0, "failed": 0}
        assert record["_upsert_succeeded"] is False

    async def test_a_write_failure_is_counted_and_never_aborts_the_batch(
        self, records: list[dict], flag_on: None
    ) -> None:
        db = _db_claiming_the_row()
        nested = MagicMock()
        nested.__aenter__ = AsyncMock(side_effect=RuntimeError("unique violation"))
        nested.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=nested)
        batch = [dict(record) for record in records[:2]]
        for record in batch:
            record["_source_checked_at"] = datetime.now(UTC)

        stats = await DelhiReraProjectScraper()._upsert(db, batch)

        assert stats == {"found": 2, "upserted": 0, "failed": 2}

    async def test_only_model_columns_reach_the_insert(
        self, records: list[dict], flag_on: None
    ) -> None:
        """The locator keys are bookkeeping, and the portal id must stay namespaced."""
        from app.models.data_hub import ReraProject

        record = dict(records[0])
        record["_source_checked_at"] = datetime.now(UTC)
        db = _db_claiming_the_row()

        await DelhiReraProjectScraper()._upsert(db, [record])

        statement = db.execute.await_args.args[0]
        values = statement.compile().params
        assert "raw_data" in values
        assert "_source_key" not in values
        assert "_source_checked_at" not in values
        assert "portal_project_id" not in values["raw_data"]
        assert values["raw_data"]["delhi_project_id"] == BHARAT_ID
        # The staleness guard binds ``last_checked_at`` once for the WHERE clause,
        # so the compiled params carry that one extra name; it is not an insert
        # column.
        assert set(values) - {"last_checked_at_1"} <= {
            column.name for column in ReraProject.__table__.columns
        }

    async def test_the_flag_turns_the_upsert_off(self, records: list[dict]) -> None:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "HRERA_DATA_ENABLED", False)
            stats = await DelhiReraProjectScraper()._upsert(_db_claiming_the_row(), records[:1])

        assert stats == {"found": 0, "upserted": 0, "failed": 0}


@pytest.fixture
def filing_record(bharat: dict) -> dict:
    """One register row with the captured filing folded in, as ``_scrape`` builds it."""
    record = dict(bharat)
    detail = parse_project_detail_html(DETAIL_FIXTURE.read_text(encoding="utf-8"))
    _apply_detail(record, detail)
    record["_source_checked_at"] = datetime.now(UTC)
    record["_source_document"] = {
        "source_key": "detail-source-key",
        "authority": "RERA Delhi",
        "title": "Delhi RERA project filing",
        "canonical_url": (
            "https://erera.co.in/reradelhiindex/PublicView/ProjectViewDetails"
            f"?inProject_ID={BHARAT_ID}"
        ),
        "source_record_id": BHARAT_ID,
        "content_sha256": hashlib.sha256(b"filing").hexdigest(),
    }
    return record


class TestFilingIsWritten:
    """The filing's own figures must reach the tables the project pages read.

    ``GET /projects/{slug}`` joins ``rera_project_profiles``. A filing kept only
    under ``raw_data.detail`` is fetched, stored, and never shown, which is what
    these tests pin.
    """

    async def test_the_filing_fills_the_profile_row(
        self, filing_record: dict, flag_on: None
    ) -> None:
        db = _capturing_db()

        stats = await DelhiReraProjectScraper()._upsert(db, [filing_record])

        assert stats == {"found": 1, "upserted": 1, "failed": 0}
        profile = _insert_into(db, "rera_project_profiles").compile().params
        assert profile["towers"] == 8
        assert profile["total_units"] == 78
        assert profile["land_area_sqm"] == Decimal("57184.17")
        assert profile["construction_start_date"] == date(2025, 3, 22)
        assert profile["proposed_completion_date"] == date(2031, 2, 18)
        # 78 units over 57184.17 sqm, the filing's own two figures.
        assert profile["units_per_acre"] == Decimal("5.52")
        assert _stage_of(profile) == "under_construction"
        assert profile["source_document_id"] is not None

    async def test_the_project_cost_is_never_written(
        self, filing_record: dict, flag_on: None
    ) -> None:
        """Delhi's cost field is not credible as rupees, so no cost row is written.

        The fixture's own value is a real one (``17212230489.00``), and even that
        is refused: the same field carries ``1.00`` on 92 of the 120 projects that
        state a cost, and ``249885954900000.00`` on the largest, so the field's
        unit cannot be trusted per-row. The figure stays visible in
        ``raw_data.detail`` and the cost table stays empty, which is the honest
        state rather than a number wrong by orders of magnitude.
        """
        db = _capturing_db()

        await DelhiReraProjectScraper()._upsert(db, [filing_record])

        assert _insert_into_or_none(db, "rera_project_costs") is None
        # The figure is still recorded exactly as the register stated it.
        assert filing_record["raw_data"]["detail"]["project_cost_inr"] == "17212230489.00"

    async def test_a_passed_completion_date_yields_no_stage(
        self, filing_record: dict, flag_on: None
    ) -> None:
        """The register still lists the project as live, so its stage is unknown.

        This is ``derive_stage``'s documented behaviour and the reason ``stage``
        is the one key a re-parse may clear: an assumed stage would be a claim
        the filing no longer supports. 86 of Delhi's 133 projects are in this
        position, so the profile is written with the other figures intact.
        """
        filing_record["raw_data"]["detail"]["proposed_completion_date"] = "2020-01-01"
        db = _capturing_db()

        await DelhiReraProjectScraper()._upsert(db, [filing_record])

        profile = _insert_into(db, "rera_project_profiles").compile().params
        assert profile["stage"] is None
        assert profile["towers"] == 8

    async def test_a_filing_that_states_nothing_writes_no_profile_row(
        self, filing_record: dict, flag_on: None
    ) -> None:
        """A skipped write keeps the stored figures; it does not erase them."""
        filing_record["raw_data"]["detail"] = {}
        filing_record.pop("total_area_sqm", None)
        filing_record.pop("total_units", None)
        db = _capturing_db()

        await DelhiReraProjectScraper()._upsert(db, [filing_record])

        assert _insert_into_or_none(db, "rera_project_profiles") is None

    async def test_the_filing_is_written_inside_the_register_rows_transaction(
        self, filing_record: dict, flag_on: None
    ) -> None:
        """Either both rows land or neither does, so no project is half-read."""
        db = _capturing_db()

        await DelhiReraProjectScraper()._upsert(db, [filing_record])

        order = ["begin" if e == "begin" else "end" if e == "end" else getattr(getattr(e, "table", None), "name", "?") for e in db.events]
        assert order[0] == "begin"
        assert order[-1] == "end"
        assert order.count("begin") == order.count("end") == 1
        for table in ("rera_projects", "rera_project_profiles"):
            assert order.index(table) > order.index("begin"), table
            assert order.index(table) < order.index("end"), table
