"""Contract pass B (BE-content): model and migration alignment, and service helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import BigInteger, CheckConstraint

from app.core.exceptions import ValidationException
from app.models.blogs import BlogPost
from app.models.data_hub import (
    AuctionAlert,
    BankAuction,
    BankRate,
    CircleRate,
    ColonyApproval,
    CourtAuction,
    GazetteNotification,
    NeighbourhoodScore,
    ReraComplaint,
    ReraProject,
    ZoningData,
)
from app.schemas.data_hub import (
    BankAuctionResponse,
    CourtAuctionResponse,
    JamabandiLookupRequest,
    ReraProjectResponse,
)
from app.schemas.flatmates_admin import serialize_flatmate_listing
from app.services.blog import _resolve_taxonomy_slug, create_category
from app.services.flatmates.conversations import list_messages
from app.services.flatmates.helpers import _profile_gender_preference


def _index(table, name: str):
    return next((i for i in table.indexes if i.name == name), None)


class TestBlogModelAlignment:
    def test_status_is_not_null_and_checked(self):
        table = BlogPost.__table__
        assert table.c.status.nullable is False
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        assert any(c.name == "blog_posts_status_check" for c in checks)

    def test_active_is_not_null(self):
        assert BlogPost.__table__.c.active.nullable is False

    def test_author_fk_clears_on_user_delete(self):
        fk = next(iter(BlogPost.__table__.c.author_id.foreign_keys))
        assert fk.ondelete == "SET NULL"

    def test_ids_are_bigint_like_the_migration(self):
        assert isinstance(BlogPost.__table__.c.id.type, BigInteger)

    def test_preview_token_index_is_partial(self):
        index = _index(BlogPost.__table__, "idx_blog_posts_preview_token")
        assert index is not None
        assert index.dialect_options["postgresql"]["where"] is not None


class TestBlogTaxonomySlugHelper:
    def test_generated_slug_comes_from_the_name(self):
        assert _resolve_taxonomy_slug("Real Estate", None) == "real-estate"

    def test_client_slug_is_normalized(self):
        assert _resolve_taxonomy_slug("Real Estate", "Property Tips!") == "property-tips"

    def test_empty_slug_is_rejected(self):
        with pytest.raises(ValidationException) as info:
            _resolve_taxonomy_slug("हिंदी", None)
        assert info.value.error_code == "SLUG_REQUIRED"

    @pytest.mark.asyncio
    async def test_create_category_rejects_before_touching_the_db(self):
        with pytest.raises(ValidationException):
            await create_category(None, "हिंदी")


class TestDataHubModelAlignment:
    def test_circle_rate_slug_is_a_unique_index(self):
        index = _index(CircleRate.__table__, "idx_circle_rates_slug")
        assert index is not None and index.unique

    def test_zoning_slug_is_a_unique_index(self):
        index = _index(ZoningData.__table__, "idx_zoning_data_slug")
        assert index is not None and index.unique

    def test_colony_and_gazette_partial_unique_indexes_exist(self):
        assert _index(ColonyApproval.__table__, "idx_colony_approvals_unique_with_licence").unique
        assert _index(ColonyApproval.__table__, "idx_colony_approvals_unique_no_licence").unique
        assert _index(GazetteNotification.__table__, "idx_gazette_unique_with_number").unique
        assert _index(GazetteNotification.__table__, "idx_gazette_unique_no_number").unique

    @pytest.mark.parametrize(
        "model",
        [
            CircleRate,
            ReraProject,
            BankAuction,
            AuctionAlert,
            BankRate,
            ZoningData,
            ColonyApproval,
            GazetteNotification,
            ReraComplaint,
            CourtAuction,
            NeighbourhoodScore,
        ],
    )
    def test_updated_at_is_not_null(self, model):
        assert model.__table__.c.updated_at.nullable is False

    def test_alert_channels_column_is_gone(self):
        assert "alert_channels" not in AuctionAlert.__table__.c


class TestDataHubSchemaFields:
    def test_bank_auction_exposes_split_contact_fields(self):
        fields = BankAuctionResponse.model_fields
        assert {"contact_person", "contact_phone", "contact_email"} <= set(fields)
        assert "contact_info" not in fields
        assert "slug" not in fields and "last_scraped_at" not in fields

    def test_court_auction_has_no_dead_location_or_slug_fields(self):
        fields = CourtAuctionResponse.model_fields
        assert not {"lat", "lng", "slug", "last_scraped_at"} & set(fields)

    def test_rera_project_has_no_dead_sector_field(self):
        """`sector` stays absent; `slug` is no longer dead and is asserted present below."""
        fields = ReraProjectResponse.model_fields
        assert "sector" not in fields

    def test_rera_project_carries_the_slug_its_list_links_with(self):
        """The list renders `/project/{slug}`, so the field is populated and read.

        It was a dead field when the list could not link anywhere. It is now the
        public URL key: `rera_projects.slug` holds it, the route 404s without it,
        and the web-ui renders the row title as a link only when it is present.
        """
        fields = ReraProjectResponse.model_fields
        assert "slug" in fields

    def test_jamabandi_request_names_the_typed_captcha(self):
        fields = JamabandiLookupRequest.model_fields
        assert "captcha_text" in fields and "captcha_token" not in fields


class TestDataHubListOrdering:
    @pytest.mark.asyncio
    async def test_list_helper_appends_the_primary_key_as_tiebreak(self):
        from sqlalchemy import select

        from app.api.api_v1.endpoints.data_hub.helpers import _safe_list_query

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        await _safe_list_query(
            db,
            BankAuction,
            select(BankAuction.id),
            select(BankAuction).order_by(BankAuction.auction_date.desc()),
            0,
            20,
        )

        sql = str(db.execute.await_args_list[1].args[0])
        assert "ORDER BY bank_auctions.auction_date DESC, bank_auctions.id" in sql


class TestFlatmatesGenderPreference:
    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            ("no_preference", "any"),
            ("male_only", "male"),
            ("female_only", "female"),
            ("female", "female"),
            ("other", None),
            (None, None),
        ],
    )
    def test_stored_values_map_onto_the_listing_enum(self, stored, expected):
        assert _profile_gender_preference({"gender_preference": stored}) == expected


class TestFlatmatesMessagesKeyset:
    @pytest.mark.asyncio
    async def test_page_is_oldest_first_and_the_cursor_points_at_its_last_id(self):
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5
        rows = [SimpleNamespace(id=i, sender_id=2, read_at=None) for i in (9, 8, 7)]
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = rows
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        with patch(
            "app.services.flatmates.conversations.get_conversation",
            new_callable=AsyncMock,
        ):
            messages, next_payload, total = await list_messages(
                db, 1, 1, limit=2, with_total=True, mark_read=False
            )

        assert [m.id for m in messages] == [8, 9]
        assert next_payload == {"v": 1, "k": [8, 8]}
        assert total == 5

    @pytest.mark.asyncio
    async def test_last_page_has_no_cursor_and_no_total_when_not_asked(self):
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [
            SimpleNamespace(id=3, sender_id=2, read_at=None)
        ]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[rows_result])

        with patch(
            "app.services.flatmates.conversations.get_conversation",
            new_callable=AsyncMock,
        ):
            messages, next_payload, total = await list_messages(db, 1, 1, limit=2, mark_read=False)

        assert [m.id for m in messages] == [3]
        assert next_payload is None
        assert total is None


class TestAdminListingFields:
    def test_moderation_payload_carries_the_four_fields_the_type_declares(self):
        listing = SimpleNamespace(
            id=1,
            title="Room",
            description=None,
            property_type="flatmate",
            purpose="rent",
            status="available",
            listing_preferences={
                "gender_preference": "female",
                "sharing_type": "private_room",
                "moderation_status": "pending_review",
            },
            monthly_rent=10000.0,
            security_deposit=None,
            maintenance_charges=None,
            area_sqft=None,
            bedrooms=1,
            bathrooms=1,
            features=[],
            city="Gurugram",
            locality=None,
            sub_locality=None,
            main_image_url=None,
            owner_id=2,
            is_available=True,
            tags=["quiet"],
            available_from=datetime(2026, 12, 1, tzinfo=UTC),
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            updated_at=None,
        )

        payload = serialize_flatmate_listing(listing)

        assert payload["tags"] == ["quiet"]
        assert payload["gender_preference"] == "female"
        assert payload["sharing_type"] == "private_room"
        assert payload["available_from"] == datetime(2026, 12, 1, tzinfo=UTC)
