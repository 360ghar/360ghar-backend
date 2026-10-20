"""Ownership checks for the IDs an upload attaches to.

An upload may name a property, a tour and a scene. The caller must own the
property or the tour, or be an admin. The scene must belong to the tour.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    SceneNotFoundException,
    TourNotFoundException,
)
from app.models.properties import Property
from app.models.tours import Scene, Tour
from app.services.visibility import Viewer


async def assert_upload_targets(
    db: AsyncSession,
    *,
    actor: Any,
    property_id: int | None = None,
    tour_id: str | None = None,
    scene_id: str | None = None,
) -> None:
    """Raise 404 when a target does not exist, 403 when the caller may not attach to it."""
    viewer = Viewer.from_user(actor)

    if property_id is not None:
        owner_id = (
            await db.execute(select(Property.owner_id).where(Property.id == property_id))
        ).scalar_one_or_none()
        if owner_id is None:
            raise NotFoundException(detail="Property not found", error_code="PROPERTY_NOT_FOUND")
        if owner_id != viewer.id and not viewer.is_admin:
            raise ForbiddenException(detail="You do not own this property")

    if tour_id is not None:
        tour_owner = (
            await db.execute(select(Tour.user_id).where(Tour.id == tour_id))
        ).scalar_one_or_none()
        if tour_owner is None:
            raise TourNotFoundException(detail="Tour not found")
        if tour_owner != viewer.id and not viewer.is_admin:
            raise ForbiddenException(detail="You do not own this tour")

    if scene_id is not None:
        scene_tour = (
            await db.execute(select(Scene.tour_id).where(Scene.id == scene_id))
        ).scalar_one_or_none()
        if scene_tour is None or (tour_id is not None and scene_tour != tour_id):
            raise SceneNotFoundException(detail="Scene not found in this tour")
