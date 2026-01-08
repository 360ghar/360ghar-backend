"""
Scene API Endpoints.

This module provides REST API endpoints for managing scenes within virtual tours,
including CRUD operations and hotspot management.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.tour import (
    Hotspot,
    HotspotCreate,
    Scene,
    SceneUpdate,
)
from app.schemas.user import User as UserSchema
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/{scene_id}", response_model=Scene)
async def get_scene(
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get a scene by ID with all its hotspots.
    """
    scene = await tour_service.get_scene(db=db, scene_id=scene_id, user_id=current_user.id)
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    # Verify ownership through tour
    tour = await tour_service.get_tour(db=db, tour_id=scene.tour_id)
    if not tour or tour.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this scene"
        )

    return scene


@router.put("/{scene_id}", response_model=Scene)
async def update_scene(
    scene_id: str,
    scene_data: SceneUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Update a scene's details.

    Can update title, description, image URLs, and metadata.
    """
    scene = await tour_service.update_scene(
        db=db,
        scene_id=scene_id,
        user_id=current_user.id,
        data=scene_data,
    )
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found or not authorized"
        )
    return scene


@router.delete("/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scene(
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Delete a scene from a tour.

    This will also delete all hotspots associated with the scene.
    """
    success = await tour_service.delete_scene(
        db=db,
        scene_id=scene_id,
        user_id=current_user.id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found or not authorized"
        )
    return None


# Hotspot endpoints nested under scenes
@router.get("/{scene_id}/hotspots", response_model=List[Hotspot])
async def list_hotspots(
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    List all hotspots for a scene.

    Returns hotspots ordered by their order_index.
    """
    # Verify scene ownership
    scene = await tour_service.get_scene(db=db, scene_id=scene_id, user_id=current_user.id)
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    tour = await tour_service.get_tour(db=db, tour_id=scene.tour_id)
    if not tour or tour.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this scene"
        )

    hotspots = await tour_service.get_hotspots(db=db, scene_id=scene_id)
    return hotspots


@router.post("/{scene_id}/hotspots", response_model=Hotspot, status_code=status.HTTP_201_CREATED)
async def create_hotspot(
    scene_id: str,
    hotspot_data: HotspotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Add a new hotspot to a scene.

    Hotspots can be navigation links, info popups, or media elements.
    """
    hotspot = await tour_service.create_hotspot(
        db=db,
        scene_id=scene_id,
        user_id=current_user.id,
        data=hotspot_data,
    )
    if not hotspot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found or not authorized"
        )
    return hotspot
