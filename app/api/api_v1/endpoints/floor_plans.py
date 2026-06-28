"""
Floor Plan API Endpoints.

This module provides REST API endpoints for managing floor plans within virtual tours,
including CRUD operations and marker management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.tour import (
    FloorPlanCreate,
    FloorPlanMarker,
    FloorPlanResponse,
    FloorPlanUpdate,
)
from app.schemas.user import User as UserSchema
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/tours/{tour_id}/floor-plans", response_model=list[FloorPlanResponse], summary="List floor plans")
async def list_floor_plans(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
    limit: int = Query(100, le=100, description="Max floor plans to return (hard cap 100)"),
):
    """
    List all floor plans for a tour.

    Returns floor plans ordered by floor number.
    """
    floor_plans = await tour_service.get_floor_plans(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )
    return floor_plans[:limit]


@router.post(
    "/tours/{tour_id}/floor-plans",
    response_model=FloorPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create floor plan",
)
async def create_floor_plan(
    tour_id: str,
    data: FloorPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Create a new floor plan for a tour.

    Floor plans can include an image and markers that link to scenes.
    """
    floor_plan = await tour_service.create_floor_plan(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        data=data,
    )
    return floor_plan


@router.get(
    "/tours/{tour_id}/floor-plans/{floor_plan_id}",
    response_model=FloorPlanResponse,
    summary="Get floor plan",
)
async def get_floor_plan(
    tour_id: str,
    floor_plan_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get a floor plan by ID.
    """
    floor_plan = await tour_service.get_floor_plan(
        db=db,
        floor_plan_id=floor_plan_id,
        user_id=current_user.id,
        tour_id=tour_id,
    )
    return floor_plan


@router.put(
    "/tours/{tour_id}/floor-plans/{floor_plan_id}",
    response_model=FloorPlanResponse,
    summary="Update floor plan",
)
async def update_floor_plan(
    tour_id: str,
    floor_plan_id: str,
    data: FloorPlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Update a floor plan's properties.

    Can update name, image URL, floor number, and markers.
    """
    floor_plan = await tour_service.update_floor_plan(
        db=db,
        floor_plan_id=floor_plan_id,
        user_id=current_user.id,
        data=data,
        tour_id=tour_id,
    )
    return floor_plan


@router.put(
    "/tours/{tour_id}/floor-plans/{floor_plan_id}/markers",
    response_model=FloorPlanResponse,
    summary="Update floor plan markers",
)
async def update_floor_plan_markers(
    tour_id: str,
    floor_plan_id: str,
    markers: list[FloorPlanMarker],
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Update only the markers on a floor plan.

    This is a convenience endpoint for marker placement in the editor.
    """
    # Convert markers to list of dicts
    markers_data = [m.model_dump() for m in markers]

    floor_plan = await tour_service.update_floor_plan_markers(
        db=db,
        floor_plan_id=floor_plan_id,
        user_id=current_user.id,
        markers=markers_data,
        tour_id=tour_id,
    )
    return floor_plan


@router.delete(
    "/tours/{tour_id}/floor-plans/{floor_plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete floor plan",
)
async def delete_floor_plan(
    tour_id: str,
    floor_plan_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Delete a floor plan from a tour.
    """
    success = await tour_service.delete_floor_plan(
        db=db,
        floor_plan_id=floor_plan_id,
        user_id=current_user.id,
        tour_id=tour_id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Floor plan not found or not authorized",
        )
    return None
