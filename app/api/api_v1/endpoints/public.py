"""
Public 360 Virtual Tour API Endpoints.

This module provides unauthenticated endpoints for viewing published tours.
These endpoints are used by the public viewer and embed page.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.logging import get_logger
from app.models.tours import Tour, Scene
from app.models.enums import TourStatus
from app.schemas.tour import TourWithScenes
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)


def get_device_type(user_agent: str) -> str:
    """Determine device type from user agent string."""
    user_agent_lower = user_agent.lower()

    if "oculus" in user_agent_lower or "quest" in user_agent_lower:
        return "vr"
    elif any(x in user_agent_lower for x in ["ipad", "tablet", "kindle"]):
        return "tablet"
    elif any(x in user_agent_lower for x in ["mobile", "android", "iphone", "ipod"]):
        return "mobile"
    else:
        return "desktop"


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request, considering proxies."""
    # Check for forwarded headers (reverse proxy)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip

    return request.client.host if request.client else "unknown"


@router.get("/tours/{tour_id}", response_model=TourWithScenes)
async def get_public_tour(
    tour_id: str,
    request: Request,
    track: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a publicly accessible tour by ID.

    This endpoint is used by the public viewer and embed page.
    It does not require authentication but the tour must be:
    - Published (status = 'published')
    - Public (is_public = True)
    - Not deleted

    Optionally tracks view analytics (disable with track=false query param).

    Returns the complete tour structure including scenes and hotspots,
    ordered by scene order_index.
    """
    # Query tour with scenes and hotspots
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None)
        )
    ).options(
        selectinload(Tour.scenes).selectinload(Scene.hotspots)
    )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    # Check if tour is published and public
    if tour.status != TourStatus.published or not tour.is_public:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or is not publicly accessible"
        )

    # Track view analytics (optional, disabled with track=false)
    if track:
        try:
            user_agent = request.headers.get("user-agent", "")
            client_ip = get_client_ip(request)
            device_type = get_device_type(user_agent)

            # Generate or extract session ID from cookies/headers
            session_id = request.cookies.get("session_id") or request.headers.get("x-session-id")

            await tour_service.record_analytics_event(
                db=db,
                tour_id=tour_id,
                event_type="view",
                user_agent=user_agent,
                ip_address=client_ip,
                device_type=device_type,
                session_id=session_id,
            )
            logger.info(f"Tracked view for tour {tour_id} from {device_type}")
        except Exception as e:
            # Don't fail the request if analytics tracking fails
            logger.warning(f"Failed to track analytics for tour {tour_id}: {e}")

    return tour


@router.get("/tours/{tour_id}/scenes")
async def get_public_tour_scenes(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all scenes for a publicly accessible tour.

    Returns scenes ordered by order_index with their hotspots.
    """
    # Verify tour exists and is public
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.is_public == True
        )
    )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or is not publicly accessible"
        )

    # Get scenes
    scenes_query = select(Scene).where(
        Scene.tour_id == tour_id
    ).options(
        selectinload(Scene.hotspots)
    ).order_by(Scene.order_index)

    scenes_result = await db.execute(scenes_query)
    scenes = list(scenes_result.scalars().all())

    return scenes


@router.post("/tours/{tour_id}/events")
async def track_tour_event(
    tour_id: str,
    event_type: str,
    request: Request,
    scene_id: Optional[str] = None,
    hotspot_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Track an analytics event for a public tour.

    Event types:
    - view: Tour was loaded
    - scene_view: A specific scene was viewed
    - hotspot_click: A hotspot was clicked
    - share: Tour was shared
    - fullscreen: Fullscreen mode was toggled
    - vr_enter: VR mode was entered

    This endpoint does not require authentication.
    """
    # Validate event type
    allowed_events = {"view", "scene_view", "hotspot_click", "share", "fullscreen", "vr_enter"}
    if event_type not in allowed_events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event type. Must be one of: {', '.join(allowed_events)}"
        )

    # Verify tour exists and is public
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.is_public == True
        )
    )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    try:
        user_agent = request.headers.get("user-agent", "")
        client_ip = get_client_ip(request)
        device_type = get_device_type(user_agent)
        session_id = request.cookies.get("session_id") or request.headers.get("x-session-id")

        await tour_service.record_analytics_event(
            db=db,
            tour_id=tour_id,
            event_type=event_type,
            scene_id=scene_id,
            hotspot_id=hotspot_id,
            user_agent=user_agent,
            ip_address=client_ip,
            device_type=device_type,
            session_id=session_id,
        )

        # Update share count if it's a share event
        if event_type == "share":
            tour.share_count = (tour.share_count or 0) + 1
            await db.commit()

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to track event for tour {tour_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to track event"
        )


@router.post("/tours/{tour_id}/like")
async def like_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Increment the like count for a public tour.

    Note: This is a simple implementation without user tracking.
    For production, consider storing likes per user/session to prevent abuse.
    """
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.is_public == True
        )
    )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    tour.like_count = (tour.like_count or 0) + 1
    await db.commit()

    return {"like_count": tour.like_count}


@router.delete("/tours/{tour_id}/like")
async def unlike_tour(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Decrement the like count for a public tour.
    """
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.is_public == True
        )
    )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    tour.like_count = max((tour.like_count or 0) - 1, 0)
    await db.commit()

    return {"like_count": tour.like_count}
