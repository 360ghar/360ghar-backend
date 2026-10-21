"""Content engine test helpers: a fake provider, a valid-output composer and sample data."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest_asyncio

from app.models.content import Locality
from app.models.data_hub import CircleRate, ReraProject
from app.models.enums import PropertyPurpose
from app.services.content.facts import FactSheet
from tests.fixtures.factories import PropertyFactory


class FakeProvider:
    """Stands in for AgnesProvider. ``respond(sheet_text)`` returns the JSON to send back."""

    class config:  # noqa: N801
        model = "fake-model"

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[Any] = []

    async def close(self) -> None:
        return None

    async def complete_json(self, messages, vision_input=None, json_schema=None):
        self.calls.append(messages)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if callable(item):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        return item


def compose(sheet: FactSheet, **overrides: Any) -> dict[str, Any]:
    """A valid locality output built only from the sheet's own display strings."""
    shown = {f.key: f.display for f in sheet.facts}
    median = shown["median_sale"]
    low_high = shown["price_sale"]
    out = {
        "summary": (
            f"{sheet.name} in {sheet.city} has homes for sale with a median listed price of {median}. "
            f"Listings range from {low_high}, so buyers can compare budgets across ready homes. "
            "The area suits families who want a settled neighbourhood with steady listing activity and "
            "clear price data. Check each listing before you plan a visit."
        ),
        "highlights": [f"Median listed price is {median}", f"Listed range is {low_high}", "Ready homes are available"],
        "faqs": [
            {"question": "What is the median price?", "answer": f"The median listed price is {median}."},
            {"question": "What is the price range?", "answer": f"Listings range from {low_high}."},
            {"question": "Is the area residential?", "answer": f"{sheet.name} is a sector in {sheet.city}."},
            {"question": "Can I see listings?", "answer": "Yes, active listings appear on 360 Ghar."},
        ],
        "meta_description": f"{sheet.name}, {sheet.city}: listed prices and homes for sale.",
    }
    out.update(overrides)
    return out


@pytest_asyncio.fixture
async def sector_data(db_session, test_user):
    db_session.add(
        Locality(slug="sector-56", name="Sector 56", city="Gurugram", place_type="sector", aliases=[],
                 landmarks=[{"name": "Sector 55-56 Metro Station", "type": "metro", "distance": "0.5 km"}])
    )
    db_session.add(CircleRate(district="Gurugram", sector="Sector 56", property_type="residential",
                              rate_per_sqyd=Decimal("45000"), revision_year=2024, slug="cr-sector-56"))
    db_session.add(ReraProject(rera_number="RC/REP/HARERA/GGM/1", project_name="Skyline Heights",
                               developer_name="Acme Builders", location="Sector 56, Gurugram",
                               district="Gurugram", total_units=300))
    for price in (10_000_000, 12_500_000, 15_000_000):
        await PropertyFactory.create(
            db_session, owner=test_user, purpose=PropertyPurpose.buy, base_price=Decimal(price),
            city="Gurugram", locality="Sector 56", bedrooms=3, area_sqft=Decimal("1500"),
        )
    await db_session.flush()
