"""UPRERA register scraper: parser contract, source coverage, and upsert gating.

Every parser assertion runs against markup captured from ``up-rera.in`` on
2026-10-23 and trimmed into ``tests/fixtures/uprera/``. No test touches the
network.
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bs4 import BeautifulSoup

from app.config import settings
from app.services.data_hub import uprera_projects as uprera_module
from app.services.data_hub.uprera_projects import UpreraProjectScraper

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "uprera"
REGISTER_FIXTURE = FIXTURE_DIR / "registered_projects.html"
NO_TABLE_FIXTURE = FIXTURE_DIR / "registered_projects_no_table.html"

# The fixture keeps the register's first 25 data rows, so every count below is
# a fact about the captured markup rather than about the live register.
FIXTURE_ROWS = 25
REGISTER_URL = "https://up-rera.in/projects"


@pytest.fixture(scope="module")
def register_html() -> str:
    return REGISTER_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def records(register_html: str) -> list[dict]:
    return UpreraProjectScraper()._parse_registered_projects_html(register_html)


def _row(*, number: str, name: str, district: str = "Lucknow") -> str:
    """One grid row shaped like the captured markup's data rows.

    The captured register carries no row with a blank RERA number or project
    name, so the partial-row cases are built here from the same cell structure
    the portal emits: a ``<span id="grdPojDetail_ctlNN_lblX">`` per column.
    """
    cells = [
        ("lblSNo", "9"),
        ("lblPromoter", "<ul><li>EXAMPLE PROMOTERS</li></ul>"),
        ("lblProjectName", name),
        ("lblRegistrationNo", number),
        ("lblProjectType", "Residential"),
        ("lblDistrict", district),
        ("lblStartDate", "01-06-2013"),
        ("lblEndDate", "30-08-2016"),
        ("lblRegDate", "29-09-2017"),
    ]
    body = "".join(
        f'<td><span id="grdPojDetail_ctl99_{suffix}">{value}</span></td>'
        for suffix, value in cells
    )
    return f'<tr class="odd" role="row">{body}</tr>'


def _register_page(*rows: str) -> str:
    header = (
        "<tr>"
        + "".join(
            f'<th><div class="tablesorter-header-inner">{title}</div></th>'
            for title in (
                "S.No",
                "Promoter Name",
                "Project Name",
                "RERA Reg.No.",
                "ProjectType",
                "District",
                "StartDate",
                "EndDate",
                "Registration Date",
                "Details",
            )
        )
        + "</tr>"
    )
    return (
        '<html><body><table id="grdPojDetail">'
        f"<thead>{header}</thead><tbody>{''.join(rows)}</tbody>"
        "</table></body></html>"
    )


class _FakeLocator:
    def __init__(self, html: str, *, count: int | None = None) -> None:
        self._html = html
        self._count = count

    async def count(self) -> int:
        if self._count is not None:
            return self._count
        return len(BeautifulSoup(self._html, "html.parser").find_all("tr"))


class _FakeNavigation:
    """Stands in for Playwright's ``page.expect_navigation()`` context manager."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakePage:
    def __init__(self, html: str) -> None:
        self.html = html
        self.visited: list[str] = []
        self.evaluated: list[str] = []
        self.closed = False
        # Successive ``locator().count()`` readings. When empty, the count is read
        # from ``html``; a list lets a test simulate a grid that is still arriving.
        self.row_counts: list[int] = []
        self._read = 0

    def set_default_timeout(self, _timeout: int) -> None:
        return None

    async def goto(self, url: str, **_kwargs) -> None:
        self.visited.append(url)

    async def evaluate(self, script: str) -> None:
        self.evaluated.append(script)

    def expect_navigation(self, **_kwargs) -> _FakeNavigation:
        return _FakeNavigation()

    def locator(self, _selector: str) -> _FakeLocator:
        if self.row_counts:
            index = min(self._read, len(self.row_counts) - 1)
            self._read += 1
            return _FakeLocator(self.html, count=self.row_counts[index])
        return _FakeLocator(self.html)

    async def content(self) -> str:
        return self.html

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def new_page(self) -> _FakePage:
        return self._page


def _install_fake_browser(monkeypatch: pytest.MonkeyPatch, html: str) -> _FakePage:
    page = _FakePage(html)

    @asynccontextmanager
    async def fake_browser():
        yield _FakeBrowser(page)

    monkeypatch.setattr(uprera_module, "_GRID_WAIT_ATTEMPTS", 1)
    monkeypatch.setattr(uprera_module, "_GRID_WAIT_SECONDS", 0.0)
    # One stable reading is enough when the count never changes.
    monkeypatch.setattr(uprera_module, "_GRID_STABLE_READS", 1)
    monkeypatch.setattr(UpreraProjectScraper, "_playwright_browser", lambda _self: fake_browser())
    return page


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


class TestRegisterParser:
    def test_every_register_row_becomes_a_record(self, records: list[dict]) -> None:
        assert len(records) == FIXTURE_ROWS
        assert all(record["rera_number"] for record in records)
        assert all(record["project_name"] for record in records)

    def test_first_row_matches_the_captured_markup(self, records: list[dict]) -> None:
        first = records[0]
        assert first["rera_number"] == "UPRERAPRJ13276"
        assert first["project_name"] == "PARK ROYAL APARTMENT"
        assert first["developer_name"] == "G R CONSTRUCTIONS"
        assert first["developer_slug"] == "g-r-constructions"
        assert first["project_type"] == "Residential"
        assert first["district"] == "Lucknow"
        assert first["registration_date"] == date(2017, 9, 29)
        assert first["possession_date"] == date(2016, 8, 30)
        assert first["slug"] == "park-royal-apartment-upreraprj13276"
        assert first["source_url"] == REGISTER_URL
        assert first["status"] == "registered"
        assert first["raw_data"]["headers"][3] == "rera reg.no."
        assert first["raw_data"]["cells"][3] == "UPRERAPRJ13276"
        assert first["_locator_table"] == 1
        # Row 1 is the header, row 2 the tablesorter filter row, row 3 the first project.
        assert first["_locator_row"] == 3

    def test_project_name_keeps_the_portals_own_annotation(self, records: list[dict]) -> None:
        # The portal renders "(Default on QPR)" in a second span of the same cell.
        assert records[1]["project_name"] == "MAHAGUN MANTRA II (Default on QPR)"
        assert records[1]["rera_number"] == "UPRERAPRJ1870"
        assert records[1]["district"] == "Gautam Buddha Nagar"

    def test_registration_number_keeps_its_revision_suffix(self, records: list[dict]) -> None:
        row = next(record for record in records if record["rera_number"].startswith("UPRERAPRJ643949"))
        assert row["rera_number"] == "UPRERAPRJ643949/09/2026"
        assert row["project_name"] == "KAILASHAM ENCLAVE"
        assert row["slug"] == "kailasham-enclave-upreraprj643949092026"

    def test_mixed_project_type_is_stored_as_the_portal_spells_it(self, records: list[dict]) -> None:
        assert {record["project_type"] for record in records} == {
            "Residential",
            "Commercial",
            "Mixed",
        }

    def test_no_record_carries_a_portal_project_id(self, records: list[dict]) -> None:
        """The detail link holds only per-session tokens, so nothing is stored.

        ``raw_data ->> 'portal_project_id'`` is under a unique partial index; a
        token that changes on every load would collide with the row the run
        before it wrote.
        """
        assert all("portal_project_id" not in record["raw_data"] for record in records)

    def test_page_without_the_grid_yields_nothing(self) -> None:
        html = NO_TABLE_FIXTURE.read_text(encoding="utf-8")
        assert BeautifulSoup(html, "html.parser").find("table") is None
        assert UpreraProjectScraper()._parse_registered_projects_html(html) == []

    def test_row_missing_the_registration_number_is_skipped(self) -> None:
        html = _register_page(
            _row(number="UPRERAPRJ999999", name="COMPLETE PROJECT"),
            _row(number="", name="NO REGISTRATION NUMBER"),
            _row(number="UPRERAPRJ888888", name=""),
        )

        records = UpreraProjectScraper()._parse_registered_projects_html(html)

        assert [record["rera_number"] for record in records] == ["UPRERAPRJ999999"]
        assert records[0]["project_name"] == "COMPLETE PROJECT"

    def test_duplicate_registration_numbers_are_kept_once(self) -> None:
        html = _register_page(
            _row(number="UPRERAPRJ777777", name="FIRST NAME"),
            _row(number="UPRERAPRJ777777", name="SECOND NAME"),
        )

        records = UpreraProjectScraper()._parse_registered_projects_html(html)

        assert [record["project_name"] for record in records] == ["FIRST NAME"]

    def test_district_defaults_to_the_state_when_the_cell_is_blank(self) -> None:
        html = _register_page(_row(number="UPRERAPRJ666666", name="NO DISTRICT", district=""))

        records = UpreraProjectScraper()._parse_registered_projects_html(html)

        assert records[0]["district"] == "Uttar Pradesh"

    def test_a_page_without_the_register_columns_is_not_parsed(self) -> None:
        html = (
            "<html><body><table id='chk_district'>"
            "<tr><th>District</th></tr><tr><td>Lucknow</td></tr>"
            "</table></body></html>"
        )

        assert UpreraProjectScraper()._parse_registered_projects_html(html) == []


class TestGridIsReadOnlyWhenItHasFinishedArriving:
    """A partial grid must never be reported as a complete register.

    The postback response is a ~15 MB streamed document, so the grid grows while
    the browser parses it. A live run that read as soon as any row existed captured
    2315 of 3823 rows and reported success — silent data loss with no error. The
    wait therefore requires the row count to repeat before it reads.
    """

    @pytest.mark.asyncio
    async def test_a_growing_grid_is_not_accepted_until_the_count_settles(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str
    ) -> None:
        page = _install_fake_browser(monkeypatch, register_html)
        # 3 rows, then 9, then 25 twice: the register has stopped growing.
        page.row_counts = [3, 9, 25, 25, 25]
        monkeypatch.setattr(uprera_module, "_GRID_WAIT_ATTEMPTS", 10)
        monkeypatch.setattr(uprera_module, "_GRID_STABLE_READS", 2)

        scraper = UpreraProjectScraper()
        result = await scraper._scrape()

        # The settled count is 25, and every one of the 25 rows was parsed.
        assert result.source_coverage[0]["grid_rows"] == 25
        assert len(result.records) == FIXTURE_ROWS
        assert result.source_coverage[0]["records_parsed"] == FIXTURE_ROWS
        assert result.source_coverage[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_a_grid_that_never_settles_reports_the_last_count(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str
    ) -> None:
        """Running out of attempts is not an error, but the count is recorded.

        ``grid_rows`` sits next to ``records_parsed`` in the run coverage, so a
        truncated read is visible in the run history instead of passing silently.
        """
        page = _install_fake_browser(monkeypatch, register_html)
        page.row_counts = [1, 2, 3, 4, 5]
        monkeypatch.setattr(uprera_module, "_GRID_WAIT_ATTEMPTS", 5)
        monkeypatch.setattr(uprera_module, "_GRID_STABLE_READS", 2)

        result = await UpreraProjectScraper()._scrape()

        assert result.source_coverage[0]["grid_rows"] == 5


class TestSourceCoverage:
    @pytest.mark.asyncio
    async def test_register_page_is_hashed_into_its_source_key(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str
    ) -> None:
        page = _install_fake_browser(monkeypatch, register_html)

        result = await UpreraProjectScraper()._scrape()

        assert result.errors == []
        assert len(result.records) == FIXTURE_ROWS
        assert len(result.source_documents) == 1
        document = result.source_documents[0]
        expected_hash = hashlib.sha256(register_html.encode("utf-8")).hexdigest()
        assert document["source_key"] == f"{REGISTER_URL}#{expected_hash}"
        assert document["content_sha256"] == expected_hash
        assert document["authority"] == "Uttar Pradesh Real Estate Regulatory Authority"
        assert document["canonical_url"] == REGISTER_URL
        assert document["jurisdiction"] == "Uttar Pradesh, India"
        assert all(record["_source_key"] == document["source_key"] for record in result.records)
        assert all(record["_locator_page"] == 1 for record in result.records)
        coverage = result.source_coverage[0]
        assert coverage["pages_checked"] == 1
        assert coverage["pages_parsed"] == 1
        assert coverage["records_parsed"] == FIXTURE_ROWS
        assert coverage["status"] == "success"
        assert result.successful_sources == 1
        assert page.visited == ["https://up-rera.in/"]
        assert page.evaluated and "lnkRegisteredProjects" in page.evaluated[0]
        assert page.closed

    @pytest.mark.asyncio
    async def test_page_without_a_table_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        html = NO_TABLE_FIXTURE.read_text(encoding="utf-8")
        _install_fake_browser(monkeypatch, html)

        result = await UpreraProjectScraper()._scrape()

        assert result.records == []
        assert len(result.errors) == 1
        assert result.errors[0]["stage"] == "parse"
        assert result.errors[0]["error_type"] == "ExpectedTableNotFound"
        assert result.successful_sources == 0
        assert result.source_coverage[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_page_whose_grid_does_not_parse_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        html = "<html><body><table id='chk_district'><tr><td>Lucknow</td></tr></table></body></html>"
        _install_fake_browser(monkeypatch, html)

        result = await UpreraProjectScraper()._scrape()

        assert result.records == []
        assert result.errors[0]["error_type"] == "NoReraRecordsParsed"
        assert result.source_coverage[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_a_browser_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        @asynccontextmanager
        async def failing_browser():
            raise RuntimeError("browser refused to start")
            yield  # pragma: no cover

        monkeypatch.setattr(
            UpreraProjectScraper, "_playwright_browser", lambda _self: failing_browser()
        )

        result = await UpreraProjectScraper()._scrape()

        assert result.records == []
        assert result.errors[0]["stage"] == "fetch"
        assert result.errors[0]["error_type"] == "RuntimeError"
        assert "browser refused to start" not in result.errors[0]["message"]


class TestConfigurationGate:
    @pytest.mark.asyncio
    async def test_upsert_is_a_no_op_when_the_flag_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=AssertionError("no write may reach the database"))

        stats = await UpreraProjectScraper()._upsert(db, [{"rera_number": "UPRERAPRJ13276"}])

        assert stats == {"found": 0, "upserted": 0, "failed": 0}
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_stops_before_creating_a_run_row_when_the_flag_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False, raising=False)
        monkeypatch.setattr(
            "app.services.data_hub.base_scraper.get_bg_session_factory",
            MagicMock(side_effect=AssertionError("run creation must not happen")),
        )
        scraper = UpreraProjectScraper()
        scraper._scrape = AsyncMock(side_effect=AssertionError("source fetch must not happen"))

        result = await scraper.run(run_type="manual")

        assert result == {
            "status": "disabled",
            "run_id": None,
            "reason": "hrera_disabled_by_configuration",
        }
        scraper._scrape.assert_not_awaited()

    def test_scraper_declares_its_name_and_browser_requirement(self) -> None:
        scraper = UpreraProjectScraper()
        assert scraper.name == "uprera_projects"
        assert scraper.requires_playwright is True


class TestUpsert:
    @pytest.mark.asyncio
    async def test_every_parsed_record_is_written(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True, raising=False)
        records = UpreraProjectScraper()._parse_registered_projects_html(register_html)
        checked_at = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
        for record in records:
            record["_source_checked_at"] = checked_at
        db = _db_claiming_the_row()

        stats = await UpreraProjectScraper()._upsert(db, records)

        assert stats == {"found": FIXTURE_ROWS, "upserted": FIXTURE_ROWS, "failed": 0}
        assert all(record["_upsert_succeeded"] is True for record in records)
        assert db.execute.await_count == FIXTURE_ROWS

    @pytest.mark.asyncio
    async def test_record_without_a_source_timestamp_is_counted_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True, raising=False)
        db = _db_claiming_the_row()
        record = {
            "rera_number": "UPRERAPRJ13276",
            "project_name": "PARK ROYAL APARTMENT",
            "slug": "park-royal-apartment-upreraprj13276",
            "_source_checked_at": None,
        }

        stats = await UpreraProjectScraper()._upsert(db, [record])

        assert stats == {"found": 1, "upserted": 0, "failed": 1}
        assert record["_upsert_succeeded"] is False
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_row_the_conflict_guard_rejects_is_not_counted_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ON CONFLICT ... WHERE`` returns no id when the stored row is newer."""
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True, raising=False)
        db = _db_claiming_the_row()
        db.execute.return_value.scalar_one_or_none.return_value = None
        record = {
            "rera_number": "UPRERAPRJ13276",
            "project_name": "PARK ROYAL APARTMENT",
            "slug": "park-royal-apartment-upreraprj13276",
            "_source_checked_at": datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
        }

        stats = await UpreraProjectScraper()._upsert(db, [record])

        assert stats == {"found": 1, "upserted": 0, "failed": 0}
        assert record["_upsert_succeeded"] is False

    @pytest.mark.asyncio
    async def test_a_write_failure_is_counted_and_never_aborts_the_batch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True, raising=False)
        db = _db_claiming_the_row()
        db.execute = AsyncMock(side_effect=RuntimeError("unique violation on slug"))
        records = [
            {
                "rera_number": number,
                "project_name": name,
                "slug": f"{name.lower()}-{number.lower()}",
                "_source_checked_at": datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
            }
            for number, name in (("UPRERAPRJ1", "ONE"), ("UPRERAPRJ2", "TWO"))
        ]

        stats = await UpreraProjectScraper()._upsert(db, records)

        assert stats == {"found": 2, "upserted": 0, "failed": 2}
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_only_model_columns_reach_the_insert(
        self, monkeypatch: pytest.MonkeyPatch, register_html: str
    ) -> None:
        monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True, raising=False)
        record = UpreraProjectScraper()._parse_registered_projects_html(register_html)[0]
        record["_source_checked_at"] = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
        db = _db_claiming_the_row()

        await UpreraProjectScraper()._upsert(db, [record])

        statement = db.execute.await_args.args[0]
        assert "_locator_row" not in statement.compile().params
        assert "_source_key" not in statement.compile().params
        assert set(statement.compile().params) >= {
            "rera_number",
            "project_name",
            "district",
            "slug",
            "raw_data",
        }
