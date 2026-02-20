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


@router.get(
    "",
    response_model=PaginatedTourResponse,
    response_model_exclude={"items": {"__all__": {"scenes"}}},
)
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


@router.post("", response_model=Tour, status_code=status.HTTP_201_CREATED)
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
    return await tour_service.get_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )


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
    return await tour_service.update_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        data=tour_data,
    )


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
    await tour_service.delete_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
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
    return await tour_service.publish_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )


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
    return await tour_service.unpublish_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )


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
    return await tour_service.duplicate_tour(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
    )


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
    return await tour_service.get_tour_analytics(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )


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
    return await tour_service.get_scenes(db=db, tour_id=tour_id, user_id=current_user.id)


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
    return await tour_service.create_scene(
        db=db,
        tour_id=tour_id,
        user_id=current_user.id,
        data=scene_data,
    )


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


@router.get("/{tour_id}/qr-code")
async def get_tour_qr_code(
    tour_id: str,
    size: int = Query(256, ge=64, le=1024, description="QR code size in pixels"),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Generate a QR code for the tour URL.

    Returns a PNG image of the QR code that links to the public tour page.
    """
    import qrcode
    from io import BytesIO
    from fastapi.responses import StreamingResponse

    tour = await tour_service.get_tour(db=db, tour_id=tour_id, user_id=current_user.id)
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )

    # Generate tour URL - use PUBLIC_BASE_URL if configured
    from app.core.config import settings
    base_url = settings.PUBLIC_BASE_URL or "https://360ghar.com"
    tour_url = f"{base_url}/tour/{tour_id}"

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(tour_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Resize to requested size
    from PIL import Image
    img = img.resize((size, size), Image.Resampling.LANCZOS)

    # Convert to bytes
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=tour-{tour_id}-qr.png"}
    )


@router.get("/{tour_id}/heatmap")
async def get_tour_heatmap(
    tour_id: str,
    scene_id: Optional[str] = Query(None, description="Filter by specific scene"),
    start_date: Optional[date] = Query(None, description="Start date for filtering"),
    end_date: Optional[date] = Query(None, description="End date for filtering"),
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_current_active_user),
):
    """
    Get aggregated heatmap data for a tour.

    Returns heatmap points grouped by scene with intensity values
    for visualization of user interaction patterns.
    """
    tour = await tour_service.get_tour(db=db, tour_id=tour_id, user_id=current_user.id)
    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or not authorized"
        )

    heatmap_data = await tour_service.get_tour_heatmap(
        db=db,
        tour_id=tour_id,
        scene_id=scene_id,
        start_date=start_date,
        end_date=end_date,
    )

    return {"tour_id": tour_id, "heatmap": heatmap_data}
