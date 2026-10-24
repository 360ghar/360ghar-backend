"""The HRERA complaints read: an empty read is a failure, not a quiet success.

Mock-only: no portal access and no database.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.config import settings
from app.services.data_hub import rera_complaints as complaints_module
from app.services.data_hub.rera_complaints import ReraComplaintScraper


def _fake_browser(html: str):
    class Locator:
        async def count(self):
            return 0

    class Page:
        def set_default_timeout(self, _ms):
            return None

        async def goto(self, url, timeout=None):
            return None

        def locator(self, _selector):
            return Locator()

        async def content(self):
            return html

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
async def test_a_page_with_no_complaint_rows_fails_the_read(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(complaints_module.asyncio, "sleep", no_sleep)
    scraper = ReraComplaintScraper()
    monkeypatch.setattr(
        scraper, "_playwright_browser", _fake_browser("<html><body>Search</body></html>")
    )

    result = await scraper._scrape()

    assert result.records == []
    assert result.status == "failed"
    assert [error["error_type"] for error in result.errors] == ["NoComplaintRecordsParsed"]


@pytest.mark.asyncio
async def test_a_parsed_complaint_row_is_a_successful_read(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(complaints_module.asyncio, "sleep", no_sleep)
    html = (
        "<table><tr><th>Order No</th><th>Respondent</th></tr>"
        "<tr><td>ORD-1</td><td>Sample Builders</td></tr></table>"
    )
    scraper = ReraComplaintScraper()
    monkeypatch.setattr(scraper, "_playwright_browser", _fake_browser(html))

    result = await scraper._scrape()

    assert [record["order_number"] for record in result.records] == ["ORD-1"]
    assert result.status == "success"
