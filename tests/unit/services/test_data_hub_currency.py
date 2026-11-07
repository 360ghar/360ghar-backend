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
