"""Pins the shared auction price parser used by the bank, MDA and aggregator scrapers."""

from __future__ import annotations

import pytest

from app.services.data_hub import aggregator_eauctions, mda_auctions
from app.services.data_hub import utils as data_hub_utils


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("₹12,50,000", 1_250_000.0),
        ("1250000", 1_250_000.0),
        ("Rs. 12 Lakh", 1_200_000.0),
        ("12 Lac", 1_200_000.0),
        ("₹1.25 Crore", 12_500_000.0),
        ("1.5 Cr", 15_000_000.0),
        (".5 Crore", 5_000_000.0),
        ("Rs. 12.50/- Lakh", 1_250_000.0),
        ("INR 12 Lakh", 1_200_000.0),
        # A plain number followed by words must not be multiplied by a unit.
        ("500000 (Five Lakh)", 500_000.0),
        ("", None),
        ("price on request", None),
    ],
)
def test_parse_currency_values(raw: str, expected: float | None) -> None:
    assert data_hub_utils._parse_currency(raw) == expected


def test_scrapers_share_the_utils_parser() -> None:
    assert mda_auctions._parse_currency is data_hub_utils._parse_currency
    assert aggregator_eauctions._parse_currency is data_hub_utils._parse_currency
    assert not hasattr(mda_auctions, "_parse_price")
    assert not hasattr(aggregator_eauctions, "_parse_price")


def test_aggregator_card_keeps_lakh_and_crore_units() -> None:
    scraper = aggregator_eauctions.AggregatorEauctionsScraper.__new__(
        aggregator_eauctions.AggregatorEauctionsScraper
    )
    html = (
        '<div class="auction-card">Flat in Noida Reserve Price: 1.5 Crore Sale notice issued</div>'
    )
    source_cfg = {"source": "aggregator", "bank": "Test", "url": "https://example.test"}
    records = scraper._parse_auction_html(html, source_cfg)
    assert [r["reserve_price"] for r in records if "reserve_price" in r] == [15_000_000.0]


def test_mda_emd_column_does_not_overwrite_reserve_price() -> None:
    scraper = mda_auctions.MdaAuctionScraper.__new__(mda_auctions.MdaAuctionScraper)
    html = (
        "<table><tr><th>Property</th><th>EMD Amount</th><th>Reserve Price</th></tr>"
        "<tr><td>Flat 1</td><td>1,00,000</td><td>10 Lakh</td></tr></table>"
    )
    source_cfg = {"source": "mda", "url": "https://example.test"}
    records = scraper._parse_auction_html(html, source_cfg)
    assert len(records) == 1
    assert records[0]["emd_amount"] == 100_000.0
    assert records[0]["reserve_price"] == 1_000_000.0
