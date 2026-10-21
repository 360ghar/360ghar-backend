"""Contract pass A (BE-content): flatmates privacy, visibility, moderation and match rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import ConflictException, NotFoundException
from app.models.enums import (
    ConversationStatus,
    FlatmatesProfileStatus,
    ListingModerationStatus,
    MessageType,
    UserMatchStatus,
)
from app.schemas.flatmates import (
    BlockedUserOut,
    ConversationCreate,
    FlatmatesNotificationBulkUpdate,
    FlatmatesNotificationUpdate,
    FlatmatesPeer,
    FlatmatesProfileUpdate,
    MatchContactOut,
    MessageCreate,
    QnAAnswers,
)
from app.services.flatmates import conversations as conv_mod
from app.services.flatmates import helpers as helpers_mod
from app.services.flatmates import matching as matching_mod
from app.services.flatmates import profiles as profiles_mod


def _user(**overrides) -> SimpleNamespace:
    base = {
        "id": 1,
        "full_name": "Asha Rao",
        "phone": "+911234567890",
        "email": "asha@example.com",
        "profile_image_url": None,
        "flatmates_mode": None,
        "flatmates_city": "Delhi",
        "flatmates_locality": None,
        "flatmates_bio": None,
        "flatmates_budget_min": None,
        "flatmates_budget_max": None,
        "flatmates_move_in_timeline": None,
        "flatmates_sleep_schedule": None,
        "flatmates_cleanliness": None,
        "flatmates_food_habits": None,
        "flatmates_smoking": None,
        "flatmates_drinking": None,
        "native_place": None,
        "linkedin_url": None,
        "flatmates_guests_policy": None,
        "flatmates_work_style": None,
        "flatmates_age": None,
        "date_of_birth": None,
        "preferences": {},
        "privacy_settings": {},
        "is_active": True,
        "flatmates_onboarding_completed": True,
        "flatmates_profile_status": FlatmatesProfileStatus.active,
        "supabase_user_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _listing(**overrides) -> SimpleNamespace:
    base = {
        "id": 9,
        "title": "Sunny room",
        "main_image_url": "https://img.example.com/1.jpg",
        "images": [
            SimpleNamespace(image_url="https://img.example.com/1.jpg"),
            SimpleNamespace(image_url="https://img.example.com/2.jpg"),
        ],
        "property_amenities": [],
        "listing_preferences": {"sharing_type": "private_room"},
        "monthly_rent": Decimal("12000.50"),
        "security_deposit": None,
        "maintenance_charges": None,
        "available_from": datetime(2026, 11, 1, tzinfo=UTC),
        "bedrooms": 2,
        "bathrooms": 1,
        "balconies": None,
        "area_sqft": None,
        "floor_number": None,
        "total_floors": None,
        "city": "Delhi",
        "locality": "Saket",
        "sub_locality": None,
        "landmark": None,
        "latitude": None,
        "longitude": None,
        "features": ["wifi"],
        "video_tour_url": None,
        "virtual_tour_url": None,
        "owner_id": 2,
        "is_available": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _db_returning(**by_model) -> MagicMock:
    """Fake session whose get() returns one object per model class."""

    async def _get(model, ident):
        return by_model.get(model.__name__)

    db = MagicMock()
    db.get = AsyncMock(side_effect=_get)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestPeerPayload:
    def test_peer_payload_never_carries_phone_or_email(self):
        payload = helpers_mod._build_peer_payload(_user())

        assert "phone_number" not in payload
        assert "phone" not in payload
        assert "email" not in payload
        assert not {"phone_number", "phone", "email"} & set(FlatmatesPeer.model_fields)

    def test_hide_last_name_shows_first_name_only(self):
        hidden = helpers_mod._build_peer_payload(_user(privacy_settings={"hide_last_name": True}))
        shown = helpers_mod._build_peer_payload(_user(privacy_settings={"hide_last_name": False}))

        assert hidden["full_name"] == "Asha"
        assert shown["full_name"] == "Asha Rao"

    def test_listing_context_is_a_typed_object_with_image_urls(self):
        payload = helpers_mod._build_peer_payload(_user(), property_obj=_listing())
        peer = FlatmatesPeer.model_validate(payload)

        assert peer.listing is not None
        assert peer.listing.property_id == 9
        assert peer.listing.image_urls == [
            "https://img.example.com/1.jpg",
            "https://img.example.com/2.jpg",
        ]
        assert peer.listing.monthly_rent == 12000.5
        assert peer.listing.room_type == "private_room"
        assert "property_title" not in payload


class TestPeerLookupVisibility:
    @pytest.mark.asyncio
    async def test_paused_profile_is_not_found(self):
        peer = _user(id=2, flatmates_profile_status=FlatmatesProfileStatus.paused)
        db = _db_returning(User=peer)

        with pytest.raises(NotFoundException) as exc:
            await profiles_mod.load_visible_peer(db, 1, 2)

        assert exc.value.error_code == "PROFILE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_suspended_account_is_not_found(self):
        peer = _user(id=2, is_active=False)
        db = _db_returning(User=peer)

        with pytest.raises(NotFoundException):
            await profiles_mod.load_visible_peer(db, 1, 2)

    @pytest.mark.asyncio
    async def test_incomplete_onboarding_is_not_found(self):
        peer = _user(id=2, flatmates_onboarding_completed=False)
        db = _db_returning(User=peer)

        with pytest.raises(NotFoundException):
            await profiles_mod.load_visible_peer(db, 1, 2)

    @pytest.mark.asyncio
    async def test_blocked_pair_is_not_found(self):
        peer = _user(id=2)
        db = _db_returning(User=peer)

        with patch.object(profiles_mod, "_is_blocked", AsyncMock(return_value=True)):
            with pytest.raises(NotFoundException):
                await profiles_mod.load_visible_peer(db, 1, 2)

    @pytest.mark.asyncio
    async def test_own_profile_is_visible_in_any_status(self):
        me = _user(id=1, flatmates_profile_status=FlatmatesProfileStatus.paused)
        db = _db_returning(User=me)

        loaded = await profiles_mod.load_visible_peer(db, 1, 1)

        assert loaded is me


class TestProfileUpdateRules:
    def test_phone_and_email_are_not_writable(self):
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate.model_validate({"phone": "+919999999999"})
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate.model_validate({"email": "x@example.com"})

    def test_owner_may_set_only_draft_or_active(self):
        assert (
            FlatmatesProfileUpdate(profile_status="active").profile_status
            == FlatmatesProfileStatus.active
        )
        assert (
            FlatmatesProfileUpdate(profile_status="draft").profile_status
            == FlatmatesProfileStatus.draft
        )
        for value in ("paused", "pending_review"):
            with pytest.raises(ValidationError):
                FlatmatesProfileUpdate.model_validate({"profile_status": value})

    def test_null_profile_status_is_rejected(self):
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate.model_validate({"profile_status": None})

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "locked_status",
        [
            FlatmatesProfileStatus.paused,
            FlatmatesProfileStatus.pending_review,
            FlatmatesProfileStatus.rejected,
        ],
    )
    async def test_owner_cannot_reactivate_a_moderation_pause(self, locked_status):
        user = _user(flatmates_profile_status=locked_status)
        db = _db_returning(User=user)

        with pytest.raises(ConflictException) as exc:
            await profiles_mod.update_flatmates_profile(
                db, 1, FlatmatesProfileUpdate(profile_status=FlatmatesProfileStatus.active)
            )

        assert exc.value.error_code == "PROFILE_STATUS_LOCKED"
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("stored", "requested"),
        [
            (FlatmatesProfileStatus.paused, FlatmatesProfileStatus.draft),
            (FlatmatesProfileStatus.pending_review, FlatmatesProfileStatus.draft),
            (FlatmatesProfileStatus.rejected, FlatmatesProfileStatus.draft),
            (FlatmatesProfileStatus.rejected, FlatmatesProfileStatus.active),
        ],
    )
    async def test_owner_status_write_is_refused_under_moderation(self, stored, requested):
        user = _user(flatmates_profile_status=stored)
        db = _db_returning(User=user)

        with pytest.raises(ConflictException) as exc:
            await profiles_mod.update_flatmates_profile(
                db, 1, FlatmatesProfileUpdate(profile_status=requested)
            )

        assert exc.value.error_code == "PROFILE_STATUS_LOCKED"
        assert user.flatmates_profile_status == stored
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pending_review_cannot_reach_active_through_draft(self):
        user = _user(flatmates_profile_status=FlatmatesProfileStatus.pending_review)
        db = _db_returning(User=user)

        for requested in (FlatmatesProfileStatus.draft, FlatmatesProfileStatus.active):
            with pytest.raises(ConflictException) as exc:
                await profiles_mod.update_flatmates_profile(
                    db, 1, FlatmatesProfileUpdate(profile_status=requested)
                )
            assert exc.value.error_code == "PROFILE_STATUS_LOCKED"

        assert user.flatmates_profile_status == FlatmatesProfileStatus.pending_review
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("stored", "requested"),
        [
            (FlatmatesProfileStatus.draft, FlatmatesProfileStatus.active),
            (FlatmatesProfileStatus.active, FlatmatesProfileStatus.draft),
            (FlatmatesProfileStatus.draft, FlatmatesProfileStatus.draft),
            (FlatmatesProfileStatus.active, FlatmatesProfileStatus.active),
        ],
    )
    async def test_owner_moves_freely_between_draft_and_active(self, stored, requested):
        user = _user(flatmates_profile_status=stored)
        db = _db_returning(User=user)

        await profiles_mod.update_flatmates_profile(
            db, 1, FlatmatesProfileUpdate(profile_status=requested)
        )

        assert user.flatmates_profile_status == requested
        db.commit.assert_awaited()


class TestQnALengths:
    def test_q2_answer_is_limited_to_32_characters(self):
        with pytest.raises(ValidationError, match="Answer 1"):
            QnAAnswers(answers={"1": "x" * 33})
        assert QnAAnswers(answers={"1": "x" * 32}).answers["1"] == "x" * 32

    def test_q1_and_q3_are_not_length_limited(self):
        long_text = "x" * 5000
        assert QnAAnswers(answers={"0": long_text, "2": long_text}).answers["0"] == long_text


class TestMatchContact:
    @pytest.mark.asyncio
    async def test_contact_is_returned_for_an_active_mutual_match(self):
        match = SimpleNamespace(id=5, user_one_id=1, user_two_id=2, status=UserMatchStatus.active)
        peer = _user(id=2, phone="+919812345678")
        db = _db_returning(UserMatch=match, User=peer)

        with patch.object(matching_mod, "_is_blocked", AsyncMock(return_value=False)):
            result = await matching_mod.get_match_contact(db, 1, 5)

        assert MatchContactOut(**result).phone == "+919812345678"
        assert result["peer_user_id"] == 2

    @pytest.mark.asyncio
    async def test_contact_is_hidden_when_the_match_is_not_active(self):
        match = SimpleNamespace(
            id=5, user_one_id=1, user_two_id=2, status=UserMatchStatus.unmatched
        )
        db = _db_returning(UserMatch=match, User=_user(id=2))

        with pytest.raises(NotFoundException):
            await matching_mod.get_match_contact(db, 1, 5)

    @pytest.mark.asyncio
    async def test_contact_is_hidden_from_a_non_participant(self):
        match = SimpleNamespace(id=5, user_one_id=3, user_two_id=4, status=UserMatchStatus.active)
        db = _db_returning(UserMatch=match, User=_user(id=4))

        with pytest.raises(NotFoundException):
            await matching_mod.get_match_contact(db, 1, 5)

    @pytest.mark.asyncio
    async def test_contact_is_hidden_when_blocked(self):
        match = SimpleNamespace(id=5, user_one_id=1, user_two_id=2, status=UserMatchStatus.active)
        db = _db_returning(UserMatch=match, User=_user(id=2))

        with patch.object(matching_mod, "_is_blocked", AsyncMock(return_value=True)):
            with pytest.raises(NotFoundException):
                await matching_mod.get_match_contact(db, 1, 5)


class TestConversationGuards:
    def test_create_accepts_match_and_listing_context(self):
        body = ConversationCreate(peer_user_id=2, match_id=3, context_property_id=4)
        assert (body.match_id, body.context_property_id) == (3, 4)

    def test_create_rejects_unknown_keys(self):
        with pytest.raises(ValidationError):
            ConversationCreate.model_validate({"peer_user_id": 2, "unexpected": True})

    @pytest.mark.asyncio
    async def test_match_must_be_active_and_link_both_users(self):
        other = SimpleNamespace(id=8, user_one_id=1, user_two_id=8, status=UserMatchStatus.active)
        db = _db_returning(UserMatch=other)

        with pytest.raises(NotFoundException):
            await conv_mod._require_active_match(db, 8, 1, 2)

    @pytest.mark.asyncio
    async def test_paused_listing_is_not_visible_to_other_users(self):
        prop = _listing(
            listing_preferences={"moderation_status": ListingModerationStatus.paused.value}
        )
        db = _db_returning(Property=prop)

        with pytest.raises(NotFoundException):
            await conv_mod._require_visible_listing(db, 9, 1)

    @pytest.mark.asyncio
    async def test_live_listing_is_visible_and_owner_always_sees_own(self):
        live = _listing(
            listing_preferences={"moderation_status": ListingModerationStatus.live.value}
        )
        assert await conv_mod._require_visible_listing(_db_returning(Property=live), 9, 1) is live

        paused = _listing(listing_preferences={"moderation_status": "paused"}, owner_id=1)
        assert (
            await conv_mod._require_visible_listing(_db_returning(Property=paused), 9, 1) is paused
        )

    def test_conversation_status_enum_is_unchanged(self):
        assert ConversationStatus.active.value == "active"


class TestMessagesAndBlocks:
    def test_clients_send_only_text_or_image_messages(self):
        assert MessageCreate(body="hi").message_type == MessageType.text
        with pytest.raises(ValidationError):
            MessageCreate(body="hi", message_type=MessageType.system)

    def test_blocked_user_is_a_typed_public_reference(self):
        row = BlockedUserOut.model_validate(
            {
                "id": 1,
                "blocked_user_id": 2,
                "blocked_user": {"id": 2, "display_name": "Asha", "avatar_url": None},
                "created_at": datetime(2026, 10, 1, tzinfo=UTC),
            }
        )
        assert row.blocked_user_id == 2
        assert row.blocked_user.display_name == "Asha"
        assert "phone" not in row.blocked_user.model_dump()


class TestNotifications:
    def test_bulk_update_only_marks_all_read(self):
        assert FlatmatesNotificationBulkUpdate().mark_all_read is True
        with pytest.raises(ValidationError):
            FlatmatesNotificationBulkUpdate(mark_all_read=False)

    def test_single_update_carries_the_requested_state(self):
        assert FlatmatesNotificationUpdate(is_read=False).is_read is False
        assert FlatmatesNotificationUpdate().is_read is True


class _FakeSupabaseQuery:
    """Chainable stand-in for supabase-py table queries."""

    def __init__(self, rows: list[dict], log: list[tuple]) -> None:
        self._rows = rows
        self._log = log
        self._update: dict | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._rows = self._rows[start : end + 1]
        return self

    def update(self, payload):
        self._update = payload
        self._log.append(("update", payload))
        return self

    def execute(self):
        return SimpleNamespace(data=list(self._rows))


class _FakeSupabase:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.log: list[tuple] = []

    def table(self, _name: str) -> _FakeSupabaseQuery:
        return _FakeSupabaseQuery(self.rows, self.log)


class TestNotificationService:
    @pytest.mark.asyncio
    async def test_mark_unread_clears_read_state(self):
        notification_id = str(uuid.uuid4())
        supabase_user_id = str(uuid.uuid4())
        row = {
            "id": notification_id,
            "title": "New match",
            "body": "You matched",
            "data": {"is_read": True, "read_at": "2026-10-01T00:00:00+00:00"},
            "created_at": "2026-10-01T00:00:00+00:00",
            "target_user_id": supabase_user_id,
        }
        fake = _FakeSupabase([row])
        db = _db_returning(User=_user(supabase_user_id=supabase_user_id))

        with patch.object(profiles_mod, "_supa", return_value=fake):
            result = await profiles_mod.mark_flatmates_notification_read(
                db, 1, notification_id, is_read=False
            )

        assert result["is_read"] is False
        update_payload = [payload for kind, payload in fake.log if kind == "update"][0]["data"]
        assert update_payload["is_read"] is False
        assert update_payload["read_at"] is None

    @pytest.mark.asyncio
    async def test_unread_count_counts_rows_without_read_state(self):
        supabase_user_id = str(uuid.uuid4())
        rows = [
            {"id": "a", "data": {}},
            {"id": "b", "data": {"is_read": True}},
            {"id": "c", "data": {"read_at": "2026-10-01T00:00:00+00:00"}},
            {"id": "d", "data": None},
        ]
        db = _db_returning(User=_user(supabase_user_id=supabase_user_id))

        with patch.object(profiles_mod, "_supa", return_value=_FakeSupabase(rows)):
            count = await profiles_mod.count_unread_flatmates_notifications(db, 1)

        assert count == 2
