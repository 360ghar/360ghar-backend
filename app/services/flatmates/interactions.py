"""Flatmates interaction tracking and data-only feedback helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.enums import PG_FLATMATE_TYPES, PropertyPurpose
from app.models.properties import Property
from app.models.social import FlatmateProfileViewEvent
from app.models.users import User
from app.schemas.flatmates import ProfileViewEventCreate, SocietyTagVoteCreate

SOCIETY_TAG_DISPUTE_DOWNVOTES = 3


async def record_profile_view_event(
    db: AsyncSession,
    viewer_user_id: int,
    payload: ProfileViewEventCreate,
) -> FlatmateProfileViewEvent:
    """Persist one profile-view duration sample for recommendation training."""

    if payload.target_user_id == viewer_user_id:
        raise BadRequestException(detail="Cannot track a self profile view")

    viewed_user = await db.get(User, payload.target_user_id)
    if viewed_user is None:
        raise BadRequestException(detail="Profile not found")

    if payload.context_property_id is not None:
        context_property = await db.get(Property, payload.context_property_id)
        if context_property is None:
            raise BadRequestException(detail="Context listing not found")
        if context_property.owner_id != payload.target_user_id:
            raise BadRequestException(detail="Context listing does not belong to viewed profile")

    event = FlatmateProfileViewEvent(
        viewer_user_id=viewer_user_id,
        viewed_user_id=payload.target_user_id,
        context_property_id=payload.context_property_id,
        source=payload.source,
        duration_seconds=payload.duration_seconds,
        scroll_depth_percent=payload.scroll_depth_percent,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


def _tag_key(raw_tag: str) -> str:
    return raw_tag.strip().lower().replace("-", "_").replace(" ", "_")


def _count(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and value >= 0 else 0


async def record_society_tag_vote(
    db: AsyncSession,
    user_id: int,
    listing_id: int,
    payload: SocietyTagVoteCreate,
) -> dict[str, Any]:
    """Store aggregate society-tag vote counts in listing preferences."""

    listing = await db.get(Property, listing_id)
    if listing is None:
        raise BadRequestException(detail="Listing not found")
    if listing.property_type not in PG_FLATMATE_TYPES or listing.purpose != PropertyPurpose.rent:
        raise BadRequestException(
            detail="Society tag votes are only available for flatmate listings"
        )

    tag = _tag_key(payload.tag)
    preferences = (
        dict(listing.listing_preferences) if isinstance(listing.listing_preferences, dict) else {}
    )
    vote_counts = (
        dict(preferences.get("society_tag_vote_counts"))  # type: ignore[arg-type]
        if isinstance(preferences.get("society_tag_vote_counts"), dict)
        else {}
    )
    user_votes = (
        dict(preferences.get("society_tag_user_votes"))  # type: ignore[arg-type]
        if isinstance(preferences.get("society_tag_user_votes"), dict)
        else {}
    )

    current_counts = dict(vote_counts.get(tag)) if isinstance(vote_counts.get(tag), dict) else {}  # type: ignore[arg-type]
    upvotes = _count(current_counts.get("up"))
    downvotes = _count(current_counts.get("down"))

    user_key = str(user_id)
    previous_votes = (
        dict(user_votes.get(user_key))  # type: ignore[arg-type]
        if isinstance(user_votes.get(user_key), dict)
        else {}
    )
    previous_vote = previous_votes.get(tag)
    if previous_vote != payload.vote:
        if previous_vote == "up":
            upvotes = max(0, upvotes - 1)
        elif previous_vote == "down":
            downvotes = max(0, downvotes - 1)

        if payload.vote == "up":
            upvotes += 1
        else:
            downvotes += 1

        previous_votes[tag] = payload.vote
        user_votes[user_key] = previous_votes

    vote_counts[tag] = {"up": upvotes, "down": downvotes}
    preferences["society_tag_vote_counts"] = vote_counts
    preferences["society_tag_user_votes"] = user_votes

    disputes = (
        dict(preferences.get("society_tag_disputes"))  # type: ignore[arg-type]
        if isinstance(preferences.get("society_tag_disputes"), dict)
        else {}
    )
    disputed = downvotes >= SOCIETY_TAG_DISPUTE_DOWNVOTES
    if disputed:
        disputes[tag] = {
            "status": "community_disputed",
            "downvotes": downvotes,
        }
    else:
        disputes.pop(tag, None)
    preferences["society_tag_disputes"] = disputes

    listing.listing_preferences = preferences
    await db.flush()

    return {
        "property_id": listing.id,
        "tag": tag,
        "current_vote": payload.vote,
        "upvotes": upvotes,
        "downvotes": downvotes,
        "disputed": disputed,
    }
