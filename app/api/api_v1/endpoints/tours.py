"""
360 Virtual Tour API Endpoints.

This module provides REST API endpoints for managing virtual tours,
including CRUD operations, publishing, duplication, and analytics.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.enums import TourStatus
from app.schemas.tour import (
    PaginatedTourResponse,
    Scene,
    SceneCreate,
    SceneReorder,
    Tour,
    TourCreate,
    TourAnalytics,
    TourUpdate,
    TourWithScenes,
)
from app.schemas.user import User as UserSchema
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/", response_model=PaginatedTourResponse)
async def list_tours(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[TourStatus] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search in title/description"),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    List all tours for the current user.

    Returns paginated list of tours with optional filtering by status and search.
    """
    result = await tour_service.get_tours(
        db=db,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        status_filter=status,
        search=search,
    )
    return result


@router.post("/", response_model=Tour, status_code=status.HTTP_201_CREATED)
async def create_tour(
    tour_data: TourCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Create a new virtual tour.

    Creates a tour in draft status. Add scenes and hotspots before publishing.
    """
    tour = await tour_service.create_tour(
        db=db,
        user_id=current_user.id,
        data=tour_data,
    )
    return tour


@router.get("/{tour_id}", response_model=TourWithScenes)
async def get_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get a tour by ID with all scenes and hotspots.

    Returns the complete tour structure including nested scenes and their hotspots.
    """
    tour = await tour_service.get_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    # Check ownership
    if tour.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this tour"
        )

    return tour


@router.put("/{tour_id}", response_model=Tour)
async def update_tour(
    tour_id: str,
    tour_data: TourUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Update a tour's details.

    Can update title, description, settings, and other tour properties.
    """
    tour = await tour_service.update_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        data=tour_data,
    )
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )
    return tour


@router.delete("/{tour_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Delete a tour (soft delete).

    The tour is marked as deleted but not permanently removed from the database.
    """
    success = await tour_service.delete_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )
    return None


@router.post("/{tour_id}/publish", response_model=Tour)
async def publish_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Publish a tour to make it publicly accessible.

    Sets the tour status to 'published' and records the publish timestamp.
    """
    tour = await tour_service.publish_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )
    return tour


@router.post("/{tour_id}/unpublish", response_model=Tour)
async def unpublish_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Unpublish a tour to make it private again.

    Sets the tour status back to 'draft'.
    """
    tour = await tour_service.unpublish_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )
    return tour


@router.post("/{tour_id}/duplicate", response_model=Tour, status_code=status.HTTP_201_CREATED)
async def duplicate_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Duplicate an existing tour.

    Creates a complete copy of the tour including all scenes and hotspots.
    The new tour will be in draft status.
    """
    tour = await tour_service.duplicate_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )
    return tour


@router.get("/{tour_id}/analytics", response_model=TourAnalytics)
async def get_tour_analytics(
    tour_id: str,
    start_date: Optional[date] = Query(None, description="Analytics start date"),
    end_date: Optional[date] = Query(None, description="Analytics end date"),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get analytics data for a tour.

    Returns view counts, engagement metrics, device breakdown, and daily views.
    """
    # First verify ownership
    tour = await tour_service.get_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )
    if tour.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this tour's analytics"
        )

    analytics = await tour_service.get_tour_analytics(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


# Scene endpoints nested under tours
@router.get("/{tour_id}/scenes", response_model=List[Scene])
async def list_scenes(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    List all scenes for a tour.

    Returns scenes ordered by their order_index.
    """
    # Verify tour ownership
    tour = await tour_service.get_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )
    if tour.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this tour"
        )

    scenes = await tour_service.get_scenes(db=db, tour_id=tour_id, user_id=current_user.id)
    return scenes


@router.post("/{tour_id}/scenes", response_model=Scene, status_code=status.HTTP_201_CREATED)
async def create_scene(
    tour_id: str,
    scene_data: SceneCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Add a new scene to a tour.

    The scene will be added at the end of the tour's scene list.
    """
    scene = await tour_service.create_scene(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        data=scene_data,
    )
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )
    return scene


@router.put("/{tour_id}/scenes/reorder", response_model=List[Scene])
async def reorder_scenes(
    tour_id: str,
    reorder_data: SceneReorder,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Reorder scenes within a tour.

    Provide the scene IDs in the desired order.
    """
    scenes = await tour_service.reorder_scenes(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        scene_ids=reorder_data.scene_ids,
    )
    if scenes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )
    return scenes
