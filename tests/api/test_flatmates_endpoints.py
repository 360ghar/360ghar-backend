from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def create_bootstrap_response() -> dict:
    return {
        "profile": {
            "id": 1,
            "full_name": "Test User",
            "email": "test@example.com",
            "phone": "+919876543210",
            "profile_image_url": None,
            "mode": "room_poster",
            "profile_status": "active",
            "onboarding_completed": True,
            "bio": "Looking for a clean flatmate",
            "budget_min": 12000,
            "budget_max": 18000,
            "move_in_timeline": "within_1_month",
            "city": "Gurugram",
            "locality": "Sector 43",
            "sleep_schedule": "night_owl",
            "cleanliness": "tidy",
            "food_habits": "non_vegetarian",
            "smoking_drinking": "drink_occasionally",
            "guests_policy": "open_house",
            "work_style": "hybrid",
            "preferences": {"vibe_tags": ["Quiet"]},
            "last_active_at": datetime.now(timezone.utc).isoformat(),
        },
        "catalogs": [
            {
                "key": "flatmates_modes",
                "version": 1,
                "payload": {"items": [{"id": "room_poster", "label": "Room Poster"}]},
            }
        ],
        "active_listing_count": 1,
        "conversation_count": 2,
        "unread_message_count": 3,
    }


class TestFlatmatesBootstrapEndpoint:
    @pytest.mark.asyncio
    async def test_get_bootstrap_success(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.flatmates.get_bootstrap",
            new_callable=AsyncMock,
        ) as mock_bootstrap:
            mock_bootstrap.return_value = create_bootstrap_response()

            response = await authenticated_client.get("/api/v1/flatmates/bootstrap")

            assert response.status_code == 200
            data = response.json()
            assert data["profile"]["mode"] == "room_poster"
            assert data["active_listing_count"] == 1


class TestFlatmatesProfileEndpoint:
    @pytest.mark.asyncio
    async def test_update_profile_success(self, authenticated_client: AsyncClient):
        response_payload = create_bootstrap_response()["profile"]

        with patch(
            "app.api.api_v1.endpoints.flatmates.update_flatmates_profile",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = response_payload

            response = await authenticated_client.put(
                "/api/v1/flatmates/profile",
                json={
                    "mode": "room_poster",
                    "city": "Gurugram",
                    "locality": "Sector 43",
                    "budget_min": 12000,
                    "budget_max": 18000,
                    "work_style": "hybrid",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["city"] == "Gurugram"
            assert data["budget_max"] == 18000


class TestFlatmatesSwipeEndpoint:
    @pytest.mark.asyncio
    async def test_property_swipe_creates_conversation(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.flatmates.record_swipe",
            new_callable=AsyncMock,
        ) as mock_swipe:
            mock_swipe.return_value = {
                "stored": True,
                "action": "like",
                "target_type": "property",
                "conversation_id": 12,
                "match_id": None,
                "did_match": False,
            }

            response = await authenticated_client.post(
                "/api/v1/flatmates/swipes",
                json={
                    "target_type": "property",
                    "action": "like",
                    "property_id": 99,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["conversation_id"] == 12
            assert data["did_match"] is False

    @pytest.mark.asyncio
    async def test_user_swipe_creates_match(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.flatmates.record_swipe",
            new_callable=AsyncMock,
        ) as mock_swipe:
            mock_swipe.return_value = {
                "stored": True,
                "action": "super_like",
                "target_type": "user",
                "conversation_id": 22,
                "match_id": 7,
                "did_match": True,
            }

            response = await authenticated_client.post(
                "/api/v1/flatmates/swipes",
                json={
                    "target_type": "user",
                    "action": "super_like",
                    "target_user_id": 44,
                    "context_property_id": 99,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["match_id"] == 7
            assert data["did_match"] is True


class TestFlatmatesLikesEndpoint:
    @pytest.mark.asyncio
    async def test_get_incoming_likes_success(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.flatmates.list_incoming_likes",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = (
                [
                    {
                        "id": 31,
                        "peer": {
                            "id": 44,
                            "full_name": "Incoming User",
                            "profile_image_url": None,
                            "mode": "seeker",
                            "match_percentage": 82,
                        },
                        "context_property": {
                            "id": 99,
                            "title": "Sunny room",
                            "monthly_rent": 18000,
                        },
                        "created_at": datetime.now(timezone.utc),
                    }
                ],
                None,
                None,
            )

            response = await authenticated_client.get("/api/v1/flatmates/likes")

            assert response.status_code == 200
            data = response.json()
            assert data["items"][0]["id"] == 31
            assert data["items"][0]["peer"]["id"] == 44
            assert data["items"][0]["context_property"]["id"] == 99
            mock_list.assert_awaited_once()


class TestFlatmatesConversationsEndpoint:
    @pytest.mark.asyncio
    async def test_get_conversations_success(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.flatmates.list_conversations",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = (
                [
                    {
                        "id": 1,
                        "source": "listing_interest",
                        "status": "active",
                        "peer": {
                            "id": 2,
                            "full_name": "Owner User",
                            "profile_image_url": None,
                            "mode": "room_poster",
                            "city": "Gurugram",
                            "locality": "DLF Phase 1",
                        },
                        "context_property": {
                            "id": 99,
                            "title": "Furnished room in DLF Phase 1",
                            "locality": "DLF Phase 1",
                            "city": "Gurugram",
                            "monthly_rent": 18000,
                            "main_image_url": None,
                        },
                        "last_message_preview": "Hey, is the room still available?",
                        "last_message_at": datetime.now(timezone.utc).isoformat(),
                        "unread_count": 1,
                        "qna": {
                            "current_user": {
                                "user_id": 1,
                                "q1": "A quiet home",
                                "q2": "Balanced",
                                "q3": "Clean kitchen",
                            },
                            "peer": {
                                "user_id": 2,
                                "q1": "Respectful flatmates",
                                "q2": "Mostly private",
                                "q3": "No smoking indoors",
                            },
                            "both_answered": True,
                        },
                    }
                ],
                None,
                None,
            )

            response = await authenticated_client.get("/api/v1/flatmates/conversations")

            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["peer"]["full_name"] == "Owner User"
            assert data["items"][0]["qna"]["both_answered"] is True
            assert data["items"][0]["qna"]["peer"]["q3"] == "No smoking indoors"

    @pytest.mark.asyncio
    async def test_post_message_success(self, authenticated_client: AsyncClient):
        with patch(
            "app.api.api_v1.endpoints.flatmates.send_message",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = {
                "id": 10,
                "conversation_id": 1,
                "sender_id": 1,
                "body": "Can we schedule a visit this weekend?",
                "attachment_url": None,
                "message_type": "text",
                "read_at": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            response = await authenticated_client.post(
                "/api/v1/flatmates/conversations/1/messages",
                json={"body": "Can we schedule a visit this weekend?"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["body"] == "Can we schedule a visit this weekend?"
