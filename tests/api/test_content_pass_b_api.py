"""Contract pass B (BE-content): HTTP behaviour of data hub, flatmates and blog routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models.data_hub import BankAuction, CourtAuction, ReraComplaint, ReraProject
from app.models.enums import AuctionSource


@pytest.fixture
async def court_row(db_session):
    row = CourtAuction(
        source=AuctionSource.sarfaesi,
        case_number="PASSB-CASE-1",
        borrower_name="Asha Borrower",
        city="Gurugram",
        locality="Sector 43",
        property_type="residential",
        reserve_price=Decimal("4500000.00"),
        auction_date=date(2026, 11, 1),
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    return row


class TestDataHubAuctionShapes:
    @pytest.mark.asyncio
    async def test_court_rows_use_the_court_shape(self, client, court_row):
        response = await client.get("/api/v1/data-hub/auctions?type=court")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["kind"] == "court"
        assert item["case_number"] == "PASSB-CASE-1"
        assert item["borrower_name"] == "Asha Borrower"
        assert "bank_name" not in item
        assert "contact_info" not in item

    @pytest.mark.asyncio
    async def test_bank_rows_use_the_bank_shape_in_the_list(self, client, db_session):
        db_session.add(
            BankAuction(
                source=AuctionSource.sarfaesi,
                bank_name="Passb Bank",
                property_description="Plot in sector 85",
                city="Gurugram",
                is_active=True,
            )
        )
        await db_session.commit()

        response = await client.get("/api/v1/data-hub/auctions")

        assert response.status_code == 200
        item = next(i for i in response.json()["items"] if i["bank_name"] == "Passb Bank")
        assert item["kind"] == "bank"
        assert "case_number" not in item

    @pytest.mark.asyncio
    async def test_bank_detail_exposes_the_contact_columns(self, client, db_session):
        row = BankAuction(
            source=AuctionSource.sarfaesi,
            bank_name="Passb Bank",
            property_description="Flat on the third floor",
            city="Gurugram",
            contact_person="Ravi",
            contact_phone="+911234567890",
            contact_email="ravi@example.com",
            is_active=True,
        )
        db_session.add(row)
        await db_session.commit()

        response = await client.get(f"/api/v1/data-hub/auctions/{row.id}?kind=bank")

        assert response.status_code == 200
        body = response.json()
        assert body["contact_person"] == "Ravi"
        assert body["contact_phone"] == "+911234567890"
        assert body["contact_email"] == "ravi@example.com"
        assert "contact_info" not in body


class TestDataHubBuilders:
    @pytest.mark.asyncio
    async def test_builder_list_items_carry_projects_and_complaints(self, client, db_session):
        db_session.add(
            ReraProject(
                rera_number="PASSB-RERA-1",
                project_name="Passb Tower",
                developer_name="Passb Builders",
                developer_slug="passb-builders",
                district="Gurugram",
            )
        )
        db_session.add(
            ReraComplaint(
                order_number="PASSB-ORD-1",
                builder_slug="passb-builders",
                respondent_builder="Passb Builders",
            )
        )
        await db_session.commit()

        response = await client.get("/api/v1/data-hub/builders")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["slug"] == "passb-builders"
        assert [p["rera_number"] for p in item["rera_projects"]] == ["PASSB-RERA-1"]
        assert len(item["recent_complaints"]) == 1

    @pytest.mark.asyncio
    async def test_one_developer_with_two_name_spellings_is_one_row(self, client, db_session):
        """A slug is the builder's identity. The register spells one developer's name more
        than one way, and the list must still show that developer once, with all of its
        projects, under the name the detail page shows (the lowest-id project's)."""
        db_session.add_all(
            [
                ReraProject(
                    rera_number="PASSB-RERA-2",
                    project_name="Spelling One",
                    developer_name="Passb Spelling Ltd",
                    developer_slug="passb-spelling",
                    district="Gurugram",
                ),
                ReraProject(
                    rera_number="PASSB-RERA-3",
                    project_name="Spelling Two",
                    developer_name="PASSB SPELLING LTD",
                    developer_slug="passb-spelling",
                    district="Gurugram",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/v1/data-hub/builders?limit=100")

        assert response.status_code == 200
        rows = [i for i in response.json()["items"] if i["slug"] == "passb-spelling"]
        assert len(rows) == 1
        assert rows[0]["builder_name"] == "Passb Spelling Ltd"
        assert rows[0]["total_projects"] == 2
        assert [p["rera_number"] for p in rows[0]["rera_projects"]] == [
            "PASSB-RERA-2",
            "PASSB-RERA-3",
        ]


    @pytest.mark.asyncio
    async def test_a_search_on_one_spelling_keeps_the_full_builder(self, client, db_session):
        """Searching one spelling must not drop the other spelling's projects."""
        db_session.add_all(
            [
                ReraProject(
                    rera_number="PASSB-RERA-4",
                    project_name="Search One",
                    developer_name="Passb Search Ltd",
                    developer_slug="passb-search",
                    district="Gurugram",
                ),
                ReraProject(
                    rera_number="PASSB-RERA-5",
                    project_name="Search Two",
                    developer_name="Passb Search Limited",
                    developer_slug="passb-search",
                    district="Gurugram",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/v1/data-hub/builders?q=Limited&limit=100")

        assert response.status_code == 200
        rows = [i for i in response.json()["items"] if i["slug"] == "passb-search"]
        assert len(rows) == 1
        assert rows[0]["builder_name"] == "Passb Search Ltd"
        assert rows[0]["total_projects"] == 2


class TestDataHubRoutesRemoved:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/data-hub/rera-projects/PASSB-RERA-1",
            "/api/v1/data-hub/gazette/1",
            "/api/v1/data-hub/bank-rates",
        ],
    )
    async def test_dead_get_routes_are_gone(self, client, path):
        response = await client.get(path)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_calculate_duty_alias_is_gone(self, client):
        response = await client.post(
            "/api/v1/data-hub/circle-rates/calculate-duty",
            json={"property_value": 1000000, "buyer_type": "male"},
        )

        assert response.status_code in (404, 405)


class TestDataHubRequestContracts:
    @pytest.mark.asyncio
    async def test_jamabandi_lookup_takes_captcha_text(self, user_client):
        response = await user_client.post(
            "/api/v1/data-hub/jamabandi/lookup",
            json={
                "tehsil": "Gurugram",
                "village": "Sohna",
                "khasra_number": "12",
                "captcha_token": "abc",
            },
        )

        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert any(item["field"] == "body.captcha_text" for item in fields)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/data-hub/auctions/banks",
            "/api/v1/data-hub/auctions/cities",
            "/api/v1/data-hub/circle-rates/sectors",
            "/api/v1/flatmates/catalogs",
        ],
    )
    async def test_facet_lists_return_one_cursor_page(self, user_client, path):
        response = await user_client.get(path)

        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) >= {"items", "next_cursor", "has_more", "limit"}
        assert isinstance(body["items"], list)
        assert body["has_more"] is False
        assert body["next_cursor"] is None
        assert body["limit"] == len(body["items"])

    @pytest.mark.asyncio
    async def test_jamabandi_lookup_rejects_unknown_body_key(self, user_client):
        response = await user_client.post(
            "/api/v1/data-hub/jamabandi/lookup",
            json={
                "tehsil": "Gurugram",
                "village": "Sohna",
                "khasra_number": "12",
                "captcha_text": "abc",
                "captcha_token": "abc",
            },
        )

        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert any(item["field"] == "body.captcha_token" for item in fields)

    @pytest.mark.asyncio
    async def test_stamp_duty_rejects_unknown_body_key(self, user_client):
        response = await user_client.post(
            "/api/v1/data-hub/calculator/stamp-duty",
            json={"property_value": 5000000, "buyer_type": "male", "unexpected": True},
        )

        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert any(item["field"] == "body.unexpected" for item in fields)

    @pytest.mark.asyncio
    async def test_alert_create_rejects_alert_channels(self, user_client):
        response = await user_client.post(
            "/api/v1/data-hub/auctions/alerts",
            json={"city": "Gurugram", "alert_channels": ["email"]},
        )

        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert any(item["field"] == "body.alert_channels" for item in fields)


class TestFlatmatesContracts:
    @pytest.mark.asyncio
    async def test_messages_list_is_a_cursor_page(self, authenticated_client):
        with patch(
            "app.api.api_v1.endpoints.flatmates.list_messages",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, 0)

            response = await authenticated_client.get(
                "/api/v1/flatmates/conversations/1/messages?include_total=true"
            )

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "next_cursor": None,
            "has_more": False,
            "limit": 20,
            "total": 0,
        }

    @pytest.mark.asyncio
    async def test_messages_reject_unknown_query_keys(self, authenticated_client):
        response = await authenticated_client.get(
            "/api/v1/flatmates/conversations/1/messages?before_id=5"
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_qa_alias_is_removed(self, authenticated_client):
        response = await authenticated_client.post(
            "/api/v1/flatmates/conversations/1/qa", json={"answers": []}
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_profile_rejects_a_value_outside_the_listing_enum(self, authenticated_client):
        response = await authenticated_client.patch(
            "/api/v1/flatmates/profile", json={"gender_preference": "no_preference"}
        )

        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert any(item["field"] == "body.gender_preference" for item in fields)


class TestBlogTaxonomySlugs:
    @pytest.mark.asyncio
    async def test_category_name_without_ascii_letters_needs_a_slug(self, admin_client):
        response = await admin_client.post("/api/v1/blog/categories", json={"name": "हिंदी"})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "SLUG_REQUIRED"
