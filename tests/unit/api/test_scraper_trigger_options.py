"""Tests for operator arguments on the manual scraper trigger.

Only ``rera_portal_scan`` takes arguments: it walks a range of HRERA portal ids and
fails without an ``end_id`` rather than defaulting to an unbounded crawl. Every
other scraper's ``__init__`` takes no arguments, so the body has to be filtered
before it reaches a constructor — passing it whole would raise ``TypeError`` and
turn a valid admin request into a 500.
"""
from __future__ import annotations

from importlib import import_module

import pytest

from app.api.api_v1.endpoints.data_hub.scraper import _SCRAPER_MAP, _scraper_options
from app.schemas.data_hub import ScraperTriggerRequest
from app.services.data_hub.rera_complaints import ReraComplaintScraper
from app.services.data_hub.rera_portal_scan import ReraPortalIdScanner
from app.services.data_hub.uprera_projects import UpreraProjectScraper


@pytest.mark.parametrize("name", sorted(_SCRAPER_MAP))
def test_every_triggerable_name_resolves_to_a_real_scraper(name: str) -> None:
    """A map entry that points at nothing turns an admin trigger into a 500.

    ``trigger_scraper`` imports the dotted path at request time, so a renamed
    module or class is not caught by anything else — the map is a string, and a
    string cannot be type-checked against the module it names.
    """
    module_path, class_name = _SCRAPER_MAP[name].rsplit(".", 1)

    scraper_cls = getattr(import_module(module_path), class_name)

    assert isinstance(scraper_cls.name, str) and scraper_cls.name


@pytest.mark.parametrize("name", sorted(_SCRAPER_MAP))
def test_every_triggerable_scraper_accepts_the_operator_body(name: str) -> None:
    """The body is filtered per scraper, so no entry may raise ``TypeError``.

    A scraper whose ``__init__`` takes no arguments must silently drop the range
    rather than fail, which is what ``_scraper_options`` exists to guarantee.
    """
    module_path, class_name = _SCRAPER_MAP[name].rsplit(".", 1)
    scraper_cls = getattr(import_module(module_path), class_name)

    options = _scraper_options(
        scraper_cls, ScraperTriggerRequest(start_id=1, end_id=2, delay_seconds=1.5)
    )

    assert scraper_cls(**options) is not None


def test_the_filing_refresh_is_triggerable_by_hand() -> None:
    """It is a network source scraper, so an operator must be able to run it.

    The weekly job refreshes filings for projects whose portal id is already
    stored. Without a map entry there is no way to run that refresh on demand —
    for example right after a portal-id scan, when every project it just created
    has no filing detail yet.
    """
    assert _SCRAPER_MAP["rera_project_detail"].endswith("ReraProjectDetailScraper")


def test_the_portal_scan_receives_the_range() -> None:
    body = ScraperTriggerRequest(start_id=2779, end_id=2781, delay_seconds=2.0)

    options = _scraper_options(ReraPortalIdScanner, body)

    assert options == {"start_id": 2779, "end_id": 2781, "delay_seconds": 2.0}
    scanner = ReraPortalIdScanner(**options)
    assert (scanner.start_id, scanner.end_id, scanner.delay_seconds) == (2779, 2781, 2.0)


@pytest.mark.parametrize(
    "scraper_cls", [ReraComplaintScraper, UpreraProjectScraper]
)
def test_a_scraper_with_no_arguments_gets_none(scraper_cls) -> None:
    """A body sent to any scraper must not break the ones that take nothing."""
    body = ScraperTriggerRequest(start_id=1, end_id=2, delay_seconds=1.0)

    assert _scraper_options(scraper_cls, body) == {}
    # And the constructor still works with what it was handed.
    scraper_cls(**_scraper_options(scraper_cls, body))


def test_no_body_and_an_empty_body_both_pass_nothing() -> None:
    assert _scraper_options(ReraPortalIdScanner, None) == {}
    assert _scraper_options(ReraPortalIdScanner, ScraperTriggerRequest()) == {}


def test_an_unset_option_is_not_passed_as_none() -> None:
    """``end_id`` alone must not arrive with ``start_id=None`` alongside it.

    The scanner's default for ``start_id`` is 1, and passing an explicit ``None``
    would overwrite it.
    """
    options = _scraper_options(ReraPortalIdScanner, ScraperTriggerRequest(end_id=10))

    assert options == {"end_id": 10}
    scanner = ReraPortalIdScanner(**options)
    assert scanner.start_id == 1
    assert scanner.end_id == 10
