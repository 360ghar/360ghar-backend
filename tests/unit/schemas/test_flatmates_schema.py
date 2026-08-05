"""
Tests for app.schemas.flatmates module — FlatmatesProfileUpdate, SwipeRequest, MessageCreate, QnAAnswers.
"""

import pytest
from pydantic import ValidationError

from app.models.enums import (
    FlatmatesDrinkingType,
    FlatmatesMode,
    FlatmatesSmokingType,
    FoodHabits,
    MessageType,
    SwipeAction,
    SwipeTargetType,
)
from app.schemas.flatmates import (
    FlatmatesPeer,
    FlatmatesProfileUpdate,
    IncomingLikeSummary,
    MessageCreate,
    MessageOut,
    QnAAnswers,
    SwipeRequest,
)


class TestFlatmatesProfileUpdate:
    """Tests for FlatmatesProfileUpdate schema validation."""

    def test_valid_update(self):
        data = FlatmatesProfileUpdate(
            bio="Looking for a flatmate",
            city="Mumbai",
            budget_min=10000,
            budget_max=25000,
        )
        assert data.bio == "Looking for a flatmate"

    def test_budget_range_valid(self):
        data = FlatmatesProfileUpdate(budget_min=10000, budget_max=25000)
        assert data.budget_min == 10000

    def test_budget_range_inverted_rejected(self):
        with pytest.raises(ValidationError, match="budget_max"):
            FlatmatesProfileUpdate(budget_min=30000, budget_max=10000)

    def test_budget_min_negative_rejected(self):
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate(budget_min=-1000)

    def test_age_below_18_rejected(self):
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate(age=15)

    def test_age_above_100_rejected(self):
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate(age=150)

    @pytest.mark.parametrize("age", [18, 25, 50, 99, 100])
    def test_valid_ages(self, age):
        data = FlatmatesProfileUpdate(age=age)
        assert data.age == age

    def test_limit_bounds(self):
        from app.schemas.flatmates import DiscoverProfilesQuery

        with pytest.raises(ValidationError):
            DiscoverProfilesQuery(limit=0)
        with pytest.raises(ValidationError):
            DiscoverProfilesQuery(limit=101)

    def test_food_habits_legacy_value_rejected(self):
        # "veg" is a legacy alias, not a canonical FoodHabits member.
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate(food_habits="veg")

    def test_food_habits_canonical_value_accepted(self):
        data = FlatmatesProfileUpdate(food_habits="vegetarian")
        assert data.food_habits == FoodHabits.vegetarian

    def test_cleanliness_legacy_value_rejected(self):
        # "balanced" is a legacy alias, not a canonical Cleanliness member.
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate(cleanliness="balanced")

    def test_smoking_drinking_enums_accepted(self):
        data = FlatmatesProfileUpdate(smoking="never", drinking="regularly")
        assert data.smoking == FlatmatesSmokingType.never
        assert data.drinking == FlatmatesDrinkingType.regularly

    def test_smoking_drinking_all_canonical_values_accepted(self):
        for value in ("never", "occasionally", "regularly"):
            assert FlatmatesProfileUpdate(smoking=value).smoking.value == value
            assert FlatmatesProfileUpdate(drinking=value).drinking.value == value

    def test_smoking_legacy_value_rejected(self):
        # "neither" was the combined legacy column value, not a split enum member.
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate(smoking="neither")
        with pytest.raises(ValidationError):
            FlatmatesProfileUpdate(drinking="both_fine")

    def test_native_place_whitespace_normalized_to_none(self):
        assert FlatmatesProfileUpdate(native_place="   ").native_place is None
        assert FlatmatesProfileUpdate(native_place="").native_place is None
        assert FlatmatesProfileUpdate(native_place="  Pune  ").native_place == "Pune"

    def test_linkedin_url_invalid_rejected(self):
        with pytest.raises(ValidationError, match="linkedin_url"):
            FlatmatesProfileUpdate(linkedin_url="not-a-url")

    def test_linkedin_url_empty_string_normalized_to_none(self):
        assert FlatmatesProfileUpdate(linkedin_url="").linkedin_url is None
        assert FlatmatesProfileUpdate(linkedin_url="   ").linkedin_url is None

    def test_linkedin_url_too_long_rejected(self):
        with pytest.raises(ValidationError, match="linkedin_url"):
            FlatmatesProfileUpdate(linkedin_url="https://linkedin.com/in/" + "a" * 250)

    def test_linkedin_url_valid_accepted(self):
        url = "https://www.linkedin.com/in/someone"
        assert FlatmatesProfileUpdate(linkedin_url=url).linkedin_url == url


class TestFlatmatesPeer:
    """Tests for the peer response used by the Flutter swipe deck."""

    def test_swipe_deck_fields_are_preserved(self):
        peer = FlatmatesPeer(
            id=2,
            full_name="Peer User",
            mode=FlatmatesMode.co_hunter,
            budget_min=12000,
            budget_max=25000,
            move_in_timeline="this_month",
            sleep_schedule="night_owl",
            cleanliness="tidy",
            food_habits="vegetarian",
            smoking="never",
            drinking="never",
            guests_policy="occasional_ok",
            work_style="hybrid",
            gender="female",
            non_negotiables=["no_smoking"],
            has_pets=True,
            party_habit="never",
        )

        data = peer.model_dump()

        assert data["budget_min"] == 12000
        assert data["sleep_schedule"] == "night_owl"
        assert data["non_negotiables"] == ["no_smoking"]
        assert data["has_pets"] is True

    def test_peer_carries_age_bucket_and_new_profile_fields(self):
        peer = FlatmatesPeer(
            id=2,
            full_name="Peer User",
            age_bucket="25-30",
            smoking="never",
            drinking="occasionally",
            native_place="Pune",
            linkedin_url="https://linkedin.com/in/peer",
        )

        data = peer.model_dump()
        assert data["age_bucket"] == "25-30"
        assert data["smoking"] == "never"
        assert data["drinking"] == "occasionally"
        assert data["native_place"] == "Pune"
        assert data["linkedin_url"] == "https://linkedin.com/in/peer"

    def test_peer_validates_from_builder_payload_without_age_key(self):
        # _build_peer_payload never emits an "age" key; the model must accept
        # the payload as-is (age stays None for backward compatibility).
        payload = {
            "id": 3,
            "full_name": "Peer",
            "profile_image_url": None,
            "mode": "seeker",
            "city": "Mumbai",
            "locality": "Bandra",
            "age_bucket": "31-35",
            "smoking": "never",
            "drinking": "never",
            "native_place": "Delhi",
            "linkedin_url": None,
        }
        peer = FlatmatesPeer.model_validate(payload)
        assert peer.age_bucket == "31-35"
        assert peer.age is None


class TestIncomingLikeSummary:
    """Tests for incoming-like payloads consumed by the mobile Likes tab."""

    def test_incoming_like_payload_preserves_peer_and_context(self):
        like = IncomingLikeSummary(
            id=5,
            peer={
                "id": 2,
                "full_name": "Peer User",
                "mode": FlatmatesMode.seeker,
                "match_percentage": 84,
            },
            context_property={
                "id": 10,
                "title": "Sunny room",
                "monthly_rent": 18000,
            },
            created_at="2026-05-07T08:30:00+00:00",
        )

        assert like.peer.id == 2
        assert like.peer.mode == FlatmatesMode.seeker
        assert like.peer.match_percentage == 84
        assert like.context_property is not None
        assert like.context_property.id == 10


class TestSwipeRequest:
    """Tests for SwipeRequest schema validation."""

    def test_property_swipe_requires_property_id(self):
        data = SwipeRequest(
            target_type=SwipeTargetType.property,
            action=SwipeAction.like,
            property_id=42,
        )
        assert data.property_id == 42

    def test_property_swipe_without_property_id_rejected(self):
        with pytest.raises(ValidationError, match="property_id"):
            SwipeRequest(
                target_type=SwipeTargetType.property,
                action=SwipeAction.like,
            )

    def test_user_swipe_requires_target_user_id(self):
        data = SwipeRequest(
            target_type=SwipeTargetType.user,
            action=SwipeAction.super_like,
            target_user_id=99,
        )
        assert data.target_user_id == 99

    def test_user_swipe_without_target_user_id_rejected(self):
        with pytest.raises(ValidationError, match="target_user_id"):
            SwipeRequest(
                target_type=SwipeTargetType.user,
                action=SwipeAction.like,
            )


class TestMessageCreate:
    """Tests for MessageCreate schema validation."""

    def test_text_message(self):
        data = MessageCreate(body="Hello there!")
        assert data.body == "Hello there!"

    def test_image_message(self):
        data = MessageCreate(attachment_url="https://example.com/img.jpg")
        assert data.attachment_url is not None

    def test_empty_body_and_no_attachment_rejected(self):
        with pytest.raises(ValidationError, match="body or attachment_url"):
            MessageCreate(body="   ")

    def test_default_message_type_is_text(self):
        data = MessageCreate(body="Hi")
        assert data.message_type == MessageType.text

    def test_visit_request_metadata(self):
        data = MessageCreate(
            body="Visit requested for afternoon",
            message_type=MessageType.visit_request,
            metadata={"visit_id": 42, "status": "scheduled"},
        )

        assert data.message_type == MessageType.visit_request
        assert data.metadata == {"visit_id": 42, "status": "scheduled"}

    def test_message_out_serializes_message_metadata_as_metadata(self):
        data = MessageOut.model_validate(
            {
                "id": 1,
                "conversation_id": 2,
                "sender_id": 3,
                "body": "Visit requested",
                "message_type": "visit_request",
                "message_metadata": {"visit_id": 42},
                "created_at": "2026-05-07T08:30:00+00:00",
            }
        )

        assert data.model_dump(mode="json", by_alias=True)["metadata"] == {"visit_id": 42}


class TestQnAAnswers:
    """Tests for QnAAnswers schema validation."""

    def test_valid_answers(self):
        data = QnAAnswers(answers={"1": "Yes", "2": "No"})
        assert data.answers["1"] == "Yes"

    def test_non_integer_key_rejected(self):
        with pytest.raises(ValidationError, match="integer"):
            QnAAnswers(answers={"abc": "Yes"})

    def test_empty_answers_valid(self):
        data = QnAAnswers()
        assert data.answers == {}
