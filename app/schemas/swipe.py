"""Swipe bodies and responses for /swipes. Property swipes only."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.base import WriteModel


class SwipeCreate(WriteModel):
    property_id: int
    is_liked: bool


class SwipeOut(BaseModel):
    """One property swipe. ``id`` is the swipe row, used by PUT /swipes/{id}/toggle."""

    id: int
    property_id: int
    is_liked: bool


class SwipeStats(BaseModel):
    total_swipes: int
    liked_count: int
    disliked_count: int
    like_percentage: float


class BatchRemoveRequest(WriteModel):
    property_ids: list[int] = Field(..., max_length=100)


class BatchRemoveResult(BaseModel):
    removed_count: int
    failed_property_ids: list[int] = Field(
        default_factory=list,
        description="Requested property ids that had no swipe to remove.",
    )
