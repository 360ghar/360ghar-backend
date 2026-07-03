from types import SimpleNamespace

import pytest

from app.models.enums import PropertyPurpose, PropertyType
from app.models.properties import Property
from app.models.social import FlatmateProfileViewEvent
from app.models.users import User
from app.schemas.flatmates import ProfileViewEventCreate, SocietyTagVoteCreate
from app.services.flatmates.interactions import (
    record_profile_view_event,
    record_society_tag_vote,
)


class FakeDb:
    def __init__(self, *, users=None, properties=None):
        self.users = users or {}
        self.properties = properties or {}
        self.added = []
        self.flushed = False
        self.committed = False

    async def get(self, model, key):
        if model is User:
            return self.users.get(key)
        if model is Property:
            return self.properties.get(key)
        return None

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = len(self.added)

    async def flush(self):
        self.flushed = True

    async def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            from datetime import datetime, timezone

            obj.created_at = datetime.now(timezone.utc)

    async def commit(self):
        self.committed = True


def _listing(**overrides):
    defaults = {
        "id": 99,
        "owner_id": 2,
        "property_type": PropertyType.flatmate,
        "purpose": PropertyPurpose.rent,
        "listing_preferences": {},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_record_profile_view_event_persists_duration_sample():
    db = FakeDb(users={2: SimpleNamespace(id=2)})

    event = await record_profile_view_event(
        db,
        1,
        ProfileViewEventCreate(
            target_user_id=2,
            duration_seconds=14,
            scroll_depth_percent=100,
            source="swipe_deck",
        ),
    )

    assert isinstance(event, FlatmateProfileViewEvent)
    assert event.viewer_user_id == 1
    assert event.viewed_user_id == 2
    assert event.duration_seconds == 14
    assert event.scroll_depth_percent == 100
    assert db.flushed is True
    assert db.committed is True


@pytest.mark.asyncio
async def test_society_tag_vote_counts_flip_previous_vote():
    listing = _listing(
        listing_preferences={
            "society_tag_vote_counts": {"quiet": {"up": 1, "down": 0}},
            "society_tag_user_votes": {"1": {"quiet": "up"}},
        }
    )
    db = FakeDb(properties={99: listing})

    result = await record_society_tag_vote(
        db,
        1,
        99,
        SocietyTagVoteCreate(tag="Quiet", vote="down"),
    )

    assert result == {
        "property_id": 99,
        "tag": "quiet",
        "current_vote": "down",
        "upvotes": 0,
        "downvotes": 1,
        "disputed": False,
    }
    assert listing.listing_preferences["society_tag_vote_counts"]["quiet"] == {
        "up": 0,
        "down": 1,
    }
    assert listing.listing_preferences["society_tag_user_votes"]["1"]["quiet"] == "down"


@pytest.mark.asyncio
async def test_society_tag_vote_marks_disputed_after_three_downvotes():
    listing = _listing()
    db = FakeDb(properties={99: listing})

    for user_id in (1, 2, 3):
        result = await record_society_tag_vote(
            db,
            user_id,
            99,
            SocietyTagVoteCreate(tag="Visitor Friendly", vote="down"),
        )

    assert result["disputed"] is True
    assert result["downvotes"] == 3
    assert (
        listing.listing_preferences["society_tag_disputes"]["visitor_friendly"]["status"]
        == "community_disputed"
    )
