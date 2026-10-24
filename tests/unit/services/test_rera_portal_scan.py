"""Tests for the HRERA portal-id scanner.

The live behaviour these encode was verified against the portal by hand:
- ``project_preview_open/2779`` returns the DLF Privana West filing (224 KB, carries
  the "Temp Project Id" marker),
- ``project_preview_open/99999999`` returns the portal's small landing page with no
  marker (a gap),
- ``project_preview_open/2778`` returns HTTP 500 (a fetch error, retried next run).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.data_hub.rera_portal_scan import (
    _DEFAULT_DISTRICT,
    _FILING_MARKER,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_MAX_IDS,
    ReraPortalIdScanner,
    _filed_district,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "hrera"
    / "rep_i_privana_west.html"
)
def test_the_captured_filing_carries_the_marker() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    assert _FILING_MARKER in html


def test_a_gap_page_does_not_carry_the_marker() -> None:
    # Shaped like the portal's landing page, which is what an unused id returns.
    gap = "<html><body><h1>Haryana Real Estate Regulatory Authority</h1></body></html>"
    assert _FILING_MARKER not in gap


@pytest.mark.asyncio
async def test_run_is_disabled_when_hrera_is_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", False)
    result = await ReraPortalIdScanner(start_id=1, end_id=10).run()
    assert result == {
        "status": "disabled",
        "run_id": None,
        "reason": "hrera_disabled_by_configuration",
    }


@pytest.mark.asyncio
async def test_run_refuses_an_open_ended_range() -> None:
    """No end id means no walk. It must not default to an unbounded crawl."""
    result = await ReraPortalIdScanner(start_id=1).run()
    assert result["status"] == "failed"
    assert "end_id is required" in result["error"]


def test_the_id_range_excludes_ids_already_stored() -> None:
    scanner = ReraPortalIdScanner(start_id=1, end_id=10)
    assert scanner._id_range({2, 4}) == [1, 3, 5, 6, 7, 8, 9, 10]
    assert scanner._id_range(set()) == list(range(1, 11))


@pytest.mark.asyncio
async def test_a_range_wider_than_the_cap_is_refused() -> None:
    """The cap bounds the span. Truncating would re-walk the same prefix every run."""
    result = await ReraPortalIdScanner(start_id=1, end_id=DEFAULT_MAX_IDS + 1).run()
    assert result["status"] == "failed"
    assert "Split it into smaller runs" in result["error"]


def _fake_browser(pages: dict[int, tuple[int, str]]):
    """A Playwright stand-in: each portal id answers with (HTTP status, HTML)."""
    state: dict[str, str] = {}

    class Page:
        def set_default_timeout(self, _ms):
            return None

        async def goto(self, url, timeout=None):
            status, html = pages[int(url.rstrip("/").rsplit("/", 1)[-1])]
            state["html"] = html
            return SimpleNamespace(status=status, ok=200 <= status < 300)

        async def content(self):
            return state["html"]

        async def close(self):
            return None

    class Browser:
        async def new_page(self):
            return Page()

    @asynccontextmanager
    async def browser():
        yield Browser()

    return browser


@pytest.mark.asyncio
async def test_the_scan_classifies_filing_gap_and_http_error_pages(monkeypatch) -> None:
    filing_html = FIXTURE.read_text(encoding="utf-8")
    gap_html = "<html><body><h1>Haryana Real Estate Regulatory Authority</h1></body></html>"
    scanner = ReraPortalIdScanner(start_id=1, end_id=3, delay_seconds=0)

    async def no_known_ids():
        return set()

    monkeypatch.setattr(scanner, "_known_portal_ids", no_known_ids)
    monkeypatch.setattr(
        scanner,
        "_playwright_browser",
        _fake_browser({1: (200, filing_html), 2: (200, gap_html), 3: (500, gap_html)}),
    )

    result = await scanner._scrape()
    coverage = result.source_coverage[0]

    assert coverage["pages_parsed"] == 1
    assert coverage["ids_skipped_gap"] == 1
    # The HTTP 500 is a fetch error, not a gap.
    assert [error["error_type"] for error in result.errors] == ["HTTPStatus"]
    assert coverage["next_start_id"] == 4


def test_the_start_id_is_honoured() -> None:
    scanner = ReraPortalIdScanner(start_id=2779, end_id=2781)
    assert scanner._id_range(set()) == [2779, 2780, 2781]


def test_pacing_defaults_to_a_courteous_delay() -> None:
    # A bulk walk of a government portal must not hammer it.
    assert DEFAULT_DELAY_SECONDS >= 1.0
    assert ReraPortalIdScanner().delay_seconds == DEFAULT_DELAY_SECONDS
    assert ReraPortalIdScanner(delay_seconds=0).delay_seconds == 0


class TestFiledDistrict:
    """The district a filing is stored under.

    HRERA registers the whole of Haryana, not just Gurugram, so a filing whose
    District label is missing must not be filed as a Gurugram project. The
    district is the city in ``micro_market`` and ``market_pulse``, so a
    fabricated one inflates the wrong city and hides the project from its own.
    """

    def test_the_district_the_filing_names_is_used(self) -> None:
        assert _filed_district({"district": "FARIDABAD"}) == "Faridabad"
        assert _filed_district({"district": "GURUGRAM"}) == "Gurugram"

    def test_a_filing_that_names_no_district_gets_the_state(self) -> None:
        for empty in ({}, {"district": None}, {"district": ""}):
            assert _filed_district(empty) == "Haryana"

    def test_a_missing_district_is_never_fabricated_as_gurugram(self) -> None:
        """The regression: the fallback was ``or "Gurugram"``, which invented a district."""
        assert _filed_district({}) != "Gurugram"
        assert _filed_district({}) == _DEFAULT_DISTRICT

    def test_the_fallback_is_a_state_and_not_a_district(self) -> None:
        """A state in the district column is visibly wrong; a wrong district looks right."""
        assert _DEFAULT_DISTRICT == "Haryana"
        assert _DEFAULT_DISTRICT != "Gurugram"
