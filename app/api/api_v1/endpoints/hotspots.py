"""
Hotspot API Endpoints.

This module provides REST API endpoints for managing hotspots within scenes,
including CRUD operations and position updates.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.tour import (
    Hotspot,
    HotspotPositionUpdate,
    HotspotUpdate,
)
from app.schemas.user import User as UserSchema
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/{hotspot_id}", response_model=Hotspot)
async def get_hotspot(
    hotspot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get a hotspot by ID.
    """
    hotspot = await tour_service.get_hotspot(db=db, hotspot_id=hotspot_id)
    if not hotspot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotspot not found"
        )

    # Verify ownership through scene -> tour chain
    scene = await tour_service.get_scene(db=db, scene_id=hotspot.scene_id, user_id=current_user.id)
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    tour = await tour_service.get_tour(db=db, tour_id=scene.tour_id, user_id=current_user.id)
    if not tour or tour.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this hotspot"
        )

    return hotspot


@router.put("/{hotspot_id}", response_model=Hotspot)
@router.patch("/{hotspot_id}", response_model=Hotspot)
async def update_hotspot(
    hotspot_id: str,
    hotspot_data: HotspotUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Update a hotspot's properties (partial update).

    Can update type, position, target scene, title, description, icon, and custom data.
    Only the fields provided in the request body will be updated.

    Note: Both PUT and PATCH are supported for backward compatibility.
    PATCH is the recommended method for partial updates.
    """
    hotspot = await tour_service.update_hotspot(
        db=db,
        hotspot_id=hotspot_id,
        user_id=current_user.id,
        data=hotspot_data,
    )
    if not hotspot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotspot not found or not authorized"
        )
    return hotspot


@router.delete("/{hotspot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hotspot(
    hotspot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Delete a hotspot from a scene.
    """
    success = await tour_service.delete_hotspot(
        db=db,
        hotspot_id=hotspot_id,
        user_id=current_user.id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotspot not found or not authorized"
        )
    return None


@router.put("/{hotspot_id}/position", response_model=Hotspot)
async def update_hotspot_position(
    hotspot_id: str,
    position_data: HotspotPositionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Update only the position of a hotspot.

    This is a convenience endpoint for drag-and-drop positioning in the editor.
    """
    hotspot = await tour_service.update_hotspot_position(
        db=db,
        hotspot_id=hotspot_id,
        user_id=current_user.id,
        position=position_data,
    )
    if not hotspot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotspot not found or not authorized"
        )
    return hotspot
