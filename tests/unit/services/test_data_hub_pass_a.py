"""Contract pass A (BE-content): data hub enums, ids, normalization and alert shapes."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import ProgrammingError

from app.api.api_v1.endpoints.data_hub.helpers import _safe_list_query
from app.api.api_v1.endpoints.data_hub.neighbourhood import _place_list
from app.core.exceptions import ServiceUnavailableException
from app.models.data_hub import BankAuction
from app.models.enums import AuctionKind, AuctionPropertyType
from app.schemas.data_hub import (
    AuctionAlertCreate,
    BankAuctionResponse,
    CourtAuctionResponse,
    JamabandiLookupResponse,
    NeighbourhoodScoreResponse,
)
from app.services.data_hub.utils import normalize_auction_property_type


class TestPropertyTypeNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Residential Flat", "residential"),
            ("residential", "residential"),
            ("Shop No 4, Ground Floor", "commercial"),
            ("Office Space", "commercial"),
            ("Industrial Plot", "industrial"),
            ("Warehouse", "industrial"),
            ("Plot / Land", "plot"),
            ("Agricultural land", None),
            ("", None),
            (None, None),
        ],
    )
    def test_scraper_text_maps_to_one_enum_value(self, raw, expected):
        assert normalize_auction_property_type(raw) == expected

    def test_every_output_is_a_member_of_the_enum(self):
        members = {member.value for member in AuctionPropertyType}
        for raw in ("Flat", "Shop", "Factory", "Land", "Villa", "unknown text"):
            value = normalize_auction_property_type(raw)
            assert value is None or value in members


class TestAuctionWireShapes:
    def test_bank_row_defaults_to_bank_kind_and_end_date_name(self):
        assert BankAuctionResponse.model_fields["kind"].default == AuctionKind.bank
        assert "auction_end_date" in BankAuctionResponse.model_fields
        assert "emd_deadline" not in BankAuctionResponse.model_fields

    def test_court_row_exposes_locality_not_address(self):
        assert CourtAuctionResponse.model_fields["kind"].default == AuctionKind.court
        assert "locality" in CourtAuctionResponse.model_fields
        assert "address" not in CourtAuctionResponse.model_fields

    def test_bank_property_type_is_the_normalized_enum(self):
        with pytest.raises(ValidationError):
            BankAuctionResponse(
                id=1,
                bank_name="SBI",
                property_description="x",
                source="sarfaesi",
                property_type="Residential Flat",
                created_at=datetime(2026, 10, 1, tzinfo=UTC),
            )


class TestAlertBodies:
    def test_create_accepts_city_keyword_and_typed_property_type(self):
        body = AuctionAlertCreate(city="Gurugram", keyword="flat", property_type="residential")
        assert body.city == "Gurugram"
        assert body.property_type == AuctionPropertyType.residential

    def test_create_rejects_unknown_keys(self):
        with pytest.raises(ValidationError):
            AuctionAlertCreate.model_validate({"bank_name": "SBI", "frequency": "daily"})

    def test_create_rejects_a_raw_scraper_property_type(self):
        with pytest.raises(ValidationError):
            AuctionAlertCreate(property_type="Residential Flat")


class TestJamabandiUnits:
    def test_response_reports_kanal_and_marla_not_acres(self):
        fields = JamabandiLookupResponse.model_fields
        assert {"area_kanal", "area_marla"} <= set(fields)
        assert "area_acres" not in fields


class TestNeighbourhoodPlaces:
    def test_place_lists_keep_only_objects(self):
        assert _place_list([{"name": "Metro"}, "bad", 3]) == [{"name": "Metro"}]

    def test_non_list_values_become_an_empty_list(self):
        assert _place_list({"name": "not a list"}) == []
        assert _place_list(None) == []

    def test_response_carries_every_stored_place_list(self):
        fields = NeighbourhoodScoreResponse.model_fields
        assert {"nearby_places", "metro_stations", "schools", "hospitals"} <= set(fields)
        assert "places_data" not in fields


class TestDatabaseFailures:
    @pytest.mark.asyncio
    async def test_database_error_is_503_not_empty_data(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=ProgrammingError("select 1", {}, Exception("no table")))

        with pytest.raises(ServiceUnavailableException) as exc:
            await _safe_list_query(db, BankAuction, MagicMock(), MagicMock(), 0, 10)

        assert exc.value.error_code == "DATA_UNAVAILABLE"
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_facet_query_error_is_503(self):
        from app.api.api_v1.endpoints.data_hub.helpers import facet_execute

        db = MagicMock()
        db.execute = AsyncMock(side_effect=ProgrammingError("select 1", {}, Exception("no table")))

        with pytest.raises(ServiceUnavailableException) as exc:
            await facet_execute(db, MagicMock())

        assert exc.value.error_code == "DATA_UNAVAILABLE"
        assert exc.value.status_code == 503

    def test_auction_kind_values_are_bank_and_court(self):
        assert {member.value for member in AuctionKind} == {"bank", "court"}

    def test_date_fields_are_still_plain_dates(self):
        row = BankAuctionResponse(
            id=2,
            kind=AuctionKind.bank,
            bank_name="PNB",
            property_description="flat",
            source="sarfaesi",
            auction_date=date(2026, 11, 2),
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
        assert row.auction_date == date(2026, 11, 2)
