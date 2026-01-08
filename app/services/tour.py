"""
Service layer for 360 Virtual Tour operations.

This module contains business logic for tour, scene, and hotspot management.
"""
import asyncio
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.enums import TourStatus
from app.models.tours import FloorPlan, Hotspot, Scene, Tour, TourAnalyticsEvent
from app.schemas.tour import (
    DailyView,
    DashboardStats,
    DeviceBreakdown,
    FloorPlanCreate,
    FloorPlanUpdate,
    HotspotCreate,
    HotspotPositionUpdate,
    HotspotUpdate,
    SceneCreate,
    SceneUpdate,
    TourAnalytics,
    TourCreate,
    TourUpdate,
)

logger = get_logger(__name__)


# Background task registry for scene processing
_scene_processing_tasks: dict = {}


# ====================
# Tour Services
# ====================

async def get_tours(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    search: Optional[str] = None
) -> dict:
    """Get paginated list of tours for a user."""
    query = select(Tour).where(
        and_(
            Tour.user_id == user_id,
            Tour.deleted_at.is_(None)
        )
    )

    if status_filter:
        query = query.where(Tour.status == status_filter)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Tour.title.ilike(search_term),
                Tour.description.ilike(search_term)
            )
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Calculate pagination
    total_pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size

    # Fetch tours with scene count
    query = query.options(selectinload(Tour.scenes)).order_by(Tour.created_at.desc())
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    tours = result.scalars().all()

    return {
        "items": tours,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


async def get_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: Optional[int] = None,
    include_scenes: bool = True
) -> Tour:
    """Get a single tour by ID."""
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None)
        )
    )

    if include_scenes:
        query = query.options(
            selectinload(Tour.scenes).selectinload(Scene.hotspots)
        )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    # Check access for non-public tours
    if not tour.is_public and tour.status != TourStatus.published:
        if user_id is None or tour.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this tour"
            )

    return tour


async def create_tour(
    db: AsyncSession,
    user_id: int,
    data: TourCreate
) -> Tour:
    """Create a new tour."""
    tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=data.title,
        description=data.description,
        status=data.status or TourStatus.draft,
        is_public=data.is_public or False,
        settings=data.settings.model_dump() if data.settings else None
    )

    db.add(tour)
    await db.commit()
    await db.refresh(tour)

    logger.info(f"Tour created: {tour.id} by user {user_id}")
    return tour


async def update_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    data: TourUpdate
) -> Tour:
    """Update a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    # Check ownership
    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this tour"
        )

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "settings" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
        setattr(tour, field, value)

    await db.commit()
    await db.refresh(tour)

    logger.info(f"Tour updated: {tour_id}")
    return tour


async def delete_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: int
) -> bool:
    """Soft delete a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this tour"
        )

    tour.deleted_at = datetime.utcnow()
    tour.status = TourStatus.archived
    await db.commit()

    logger.info(f"Tour deleted: {tour_id}")
    return True


async def publish_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: int
) -> Tour:
    """Publish a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to publish this tour"
        )

    # Check if tour has scenes
    if not tour.scenes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot publish a tour without scenes"
        )

    tour.status = TourStatus.published
    tour.published_at = datetime.utcnow()
    tour.is_public = True

    await db.commit()
    await db.refresh(tour)

    logger.info(f"Tour published: {tour_id}")
    return tour


async def unpublish_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: int
) -> Tour:
    """Unpublish a tour (set to draft)."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to unpublish this tour"
        )

    tour.status = TourStatus.draft
    tour.is_public = False

    await db.commit()
    await db.refresh(tour)

    logger.info(f"Tour unpublished: {tour_id}")
    return tour


async def duplicate_tour(
    db: AsyncSession,
    tour_id: str,
    user_id: int
) -> Tour:
    """Duplicate a tour with all its scenes and hotspots."""
    original = await get_tour(db, tour_id, user_id, include_scenes=True)

    if original.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to duplicate this tour"
        )

    # Create new tour
    new_tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=f"{original.title} (Copy)",
        description=original.description,
        status=TourStatus.draft,
        is_public=False,
        settings=original.settings,
        thumbnail_url=original.thumbnail_url
    )
    db.add(new_tour)

    # Map old scene IDs to new scene IDs for hotspot targets
    scene_id_map = {}

    # Duplicate scenes
    for scene in original.scenes or []:
        new_scene_id = str(uuid4())
        scene_id_map[scene.id] = new_scene_id

        new_scene = Scene(
            id=new_scene_id,
            tour_id=new_tour.id,
            title=scene.title,
            description=scene.description,
            image_url=scene.image_url,
            thumbnail_url=scene.thumbnail_url,
            order_index=scene.order_index,
            scene_metadata=scene.scene_metadata,
            is_processed=scene.is_processed
        )
        db.add(new_scene)

    await db.flush()

    # Duplicate hotspots
    for scene in original.scenes or []:
        for hotspot in scene.hotspots or []:
            new_target_scene_id = None
            if hotspot.target_scene_id:
                new_target_scene_id = scene_id_map.get(hotspot.target_scene_id)

            new_hotspot = Hotspot(
                id=str(uuid4()),
                scene_id=scene_id_map[scene.id],
                type=hotspot.type,
                position=hotspot.position,
                target_scene_id=new_target_scene_id,
                title=hotspot.title,
                description=hotspot.description,
                icon=hotspot.icon,
                icon_name=hotspot.icon_name,
                icon_color=hotspot.icon_color,
                icon_size=hotspot.icon_size,
                content=hotspot.content,
                custom_data=hotspot.custom_data,
                order_index=hotspot.order_index,
                is_active=hotspot.is_active
            )
            db.add(new_hotspot)

    await db.commit()

    # Reload with scenes
    return await get_tour(db, new_tour.id, user_id, include_scenes=True)


# ====================
# Scene Services
# ====================

async def get_scenes(
    db: AsyncSession,
    tour_id: str,
    user_id: Optional[int] = None
) -> List[Scene]:
    """Get all scenes for a tour."""
    # Verify tour access
    await get_tour(db, tour_id, user_id, include_scenes=False)

    query = select(Scene).where(Scene.tour_id == tour_id).options(
        selectinload(Scene.hotspots)
    ).order_by(Scene.order_index)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_scene(
    db: AsyncSession,
    scene_id: str,
    user_id: Optional[int] = None
) -> Scene:
    """Get a single scene by ID."""
    query = select(Scene).where(Scene.id == scene_id).options(
        selectinload(Scene.hotspots),
        selectinload(Scene.tour)
    )

    result = await db.execute(query)
    scene = result.scalar_one_or_none()

    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    # Check tour access
    if user_id is not None and scene.tour.user_id != user_id:
        if not scene.tour.is_public:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this scene"
            )

    return scene


async def create_scene(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    data: SceneCreate
) -> Scene:
    """Create a new scene in a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to add scenes to this tour"
        )

    # Get max order_index
    max_order_query = select(func.max(Scene.order_index)).where(Scene.tour_id == tour_id)
    result = await db.execute(max_order_query)
    max_order = result.scalar() or -1

    scene = Scene(
        id=str(uuid4()),
        tour_id=tour_id,
        title=data.title,
        description=data.description,
        image_url=data.image_url,
        thumbnail_url=data.thumbnail_url,
        order_index=data.order_index if data.order_index is not None else max_order + 1,
        scene_metadata=data.metadata.model_dump() if data.metadata else None,
        is_processed=False,  # Will be set to True after background processing
    )

    db.add(scene)
    await db.commit()
    await db.refresh(scene)

    # Schedule background processing for thumbnail generation
    if data.image_url and not data.thumbnail_url:
        schedule_scene_processing(
            scene_id=scene.id,
            tour_id=tour_id,
            image_url=data.image_url,
        )
    else:
        # Mark as processed if thumbnail already provided
        scene.is_processed = True
        await db.commit()

    logger.info(f"Scene created: {scene.id} in tour {tour_id}")
    return scene


async def update_scene(
    db: AsyncSession,
    scene_id: str,
    user_id: int,
    data: SceneUpdate
) -> Scene:
    """Update a scene."""
    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this scene"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "metadata" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
            setattr(scene, "scene_metadata", value)
        else:
            setattr(scene, field, value)

    await db.commit()
    await db.refresh(scene)

    logger.info(f"Scene updated: {scene_id}")
    return scene


async def delete_scene(
    db: AsyncSession,
    scene_id: str,
    user_id: int
) -> bool:
    """Delete a scene."""
    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this scene"
        )

    await db.delete(scene)
    await db.commit()

    logger.info(f"Scene deleted: {scene_id}")
    return True


async def reorder_scenes(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    scene_ids: List[str]
) -> List[Scene]:
    """Reorder scenes in a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to reorder scenes"
        )

    # Update order_index for each scene
    for index, scene_id in enumerate(scene_ids):
        query = select(Scene).where(
            and_(Scene.id == scene_id, Scene.tour_id == tour_id)
        )
        result = await db.execute(query)
        scene = result.scalar_one_or_none()

        if scene:
            scene.order_index = index

    await db.commit()

    # Return reordered scenes
    return await get_scenes(db, tour_id, user_id)


# ====================
# Hotspot Services
# ====================

async def get_hotspots(
    db: AsyncSession,
    scene_id: str,
    user_id: Optional[int] = None
) -> List[Hotspot]:
    """Get all hotspots for a scene."""
    # Verify scene access
    await get_scene(db, scene_id, user_id)

    query = select(Hotspot).where(Hotspot.scene_id == scene_id).order_by(Hotspot.order_index)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hotspot(
    db: AsyncSession,
    hotspot_id: str,
    user_id: Optional[int] = None
) -> Hotspot:
    """Get a single hotspot by ID."""
    query = select(Hotspot).where(Hotspot.id == hotspot_id).options(
        selectinload(Hotspot.scene).selectinload(Scene.tour)
    )

    result = await db.execute(query)
    hotspot = result.scalar_one_or_none()

    if not hotspot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotspot not found"
        )

    return hotspot


async def create_hotspot(
    db: AsyncSession,
    scene_id: str,
    user_id: int,
    data: HotspotCreate
) -> Hotspot:
    """Create a new hotspot in a scene."""
    scene = await get_scene(db, scene_id, user_id)

    if scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to add hotspots to this scene"
        )

    # Get max order_index
    max_order_query = select(func.max(Hotspot.order_index)).where(Hotspot.scene_id == scene_id)
    result = await db.execute(max_order_query)
    max_order = result.scalar() or -1

    hotspot = Hotspot(
        id=str(uuid4()),
        scene_id=scene_id,
        type=data.type,
        position=data.position.model_dump(),
        target_scene_id=data.target_scene_id,
        title=data.title,
        description=data.description,
        icon=data.icon,
        icon_name=data.icon_name,
        icon_color=data.icon_color,
        icon_size=data.icon_size or 32,
        content=data.content,
        custom_data=data.custom_data,
        order_index=max_order + 1
    )

    db.add(hotspot)
    await db.commit()
    await db.refresh(hotspot)

    logger.info(f"Hotspot created: {hotspot.id} in scene {scene_id}")
    return hotspot


async def update_hotspot(
    db: AsyncSession,
    hotspot_id: str,
    user_id: int,
    data: HotspotUpdate
) -> Hotspot:
    """Update a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    # Get scene and tour for permission check
    scene = await get_scene(db, hotspot.scene_id, user_id)
    if scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this hotspot"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "position" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
        setattr(hotspot, field, value)

    await db.commit()
    await db.refresh(hotspot)

    logger.info(f"Hotspot updated: {hotspot_id}")
    return hotspot


async def delete_hotspot(
    db: AsyncSession,
    hotspot_id: str,
    user_id: int
) -> bool:
    """Delete a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    scene = await get_scene(db, hotspot.scene_id, user_id)
    if scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this hotspot"
        )

    await db.delete(hotspot)
    await db.commit()

    logger.info(f"Hotspot deleted: {hotspot_id}")
    return True


async def update_hotspot_position(
    db: AsyncSession,
    hotspot_id: str,
    user_id: int,
    position: HotspotPositionUpdate
) -> Hotspot:
    """Update only the position of a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    scene = await get_scene(db, hotspot.scene_id, user_id)
    if scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this hotspot"
        )

    # Update position while preserving radius if it exists
    current_position = hotspot.position or {}
    hotspot.position = {
        "yaw": position.yaw,
        "pitch": position.pitch,
        "radius": current_position.get("radius")
    }

    await db.commit()
    await db.refresh(hotspot)

    logger.info(f"Hotspot position updated: {hotspot_id}")
    return hotspot


# ====================
# Analytics Services
# ====================

async def get_tour_analytics(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> TourAnalytics:
    """Get analytics for a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to analytics for this tour"
        )

    # Build query with date filters
    query = select(TourAnalyticsEvent).where(TourAnalyticsEvent.tour_id == tour_id)

    if start_date:
        query = query.where(TourAnalyticsEvent.created_at >= start_date)
    if end_date:
        query = query.where(TourAnalyticsEvent.created_at <= end_date)

    result = await db.execute(query)
    events = list(result.scalars().all())

    # Calculate analytics
    scene_views: dict = {}
    hotspot_clicks: dict = {}
    device_counts = {"desktop": 0, "mobile": 0, "tablet": 0, "vr": 0}
    country_counts: dict = {}
    daily_views_map: dict = {}
    unique_sessions: set = set()
    heatmap_points: List[dict] = []
    share_breakdown: dict = {}
    session_starts: dict = {}
    session_durations: List[float] = []

    for event in events:
        event_payload = event.event_data or {}

        if event.session_id:
            unique_sessions.add(event.session_id)

        if event.event_type == "scene_view" and event.scene_id:
            scene_views[event.scene_id] = scene_views.get(event.scene_id, 0) + 1

        if event.event_type == "hotspot_click" and event.hotspot_id:
            hotspot_clicks[event.hotspot_id] = hotspot_clicks.get(event.hotspot_id, 0) + 1

        if event.event_type == "heatmap":
            heatmap_points.append(
                {
                    "scene_id": event.scene_id,
                    "yaw": event_payload.get("yaw"),
                    "pitch": event_payload.get("pitch"),
                    "x": event_payload.get("x"),
                    "y": event_payload.get("y"),
                    "intensity": event_payload.get("intensity", 1.0),
                }
            )

        if event.event_type == "share":
            platform = event_payload.get("platform") or event_payload.get("channel") or "unknown"
            share_breakdown[platform] = share_breakdown.get(platform, 0) + 1

        if event.event_type == "session_start" and event.session_id:
            session_starts[event.session_id] = event.created_at

        if event.event_type in {"session_end", "session_duration"}:
            duration = event_payload.get("duration_seconds")
            if duration is None and event_payload.get("duration_ms") is not None:
                duration = event_payload.get("duration_ms") / 1000
            if duration is None and event_payload.get("duration") is not None:
                duration = event_payload.get("duration")
            if duration is None and event.session_id and event.session_id in session_starts:
                duration = (event.created_at - session_starts[event.session_id]).total_seconds()
            if duration is not None:
                session_durations.append(float(duration))

        if event.device_type and event.device_type in device_counts:
            device_counts[event.device_type] += 1

        if event.country:
            country_counts[event.country] = country_counts.get(event.country, 0) + 1

        date_str = event.created_at.strftime("%Y-%m-%d")
        if event.event_type == "view":
            daily_views_map[date_str] = daily_views_map.get(date_str, 0) + 1

    daily_views = [
        DailyView(date=date, views=views)
        for date, views in sorted(daily_views_map.items())
    ]

    avg_session_duration = (
        sum(session_durations) / len(session_durations) if session_durations else 0.0
    )

    return TourAnalytics(
        tour_id=tour_id,
        total_views=tour.view_count,
        unique_views=len(unique_sessions),
        total_likes=tour.like_count,
        total_shares=tour.share_count,
        avg_session_duration=avg_session_duration,
        scene_views=scene_views,
        hotspot_clicks=hotspot_clicks,
        heatmap_points=heatmap_points,
        share_breakdown=share_breakdown,
        session_durations=session_durations,
        device_breakdown=DeviceBreakdown(**device_counts),
        country_breakdown=country_counts,
        daily_views=daily_views
    )


async def get_dashboard_stats(
    db: AsyncSession,
    user_id: int
) -> DashboardStats:
    """Get dashboard statistics for a user."""
    # Count tours
    total_tours_query = select(func.count(Tour.id)).where(
        and_(Tour.user_id == user_id, Tour.deleted_at.is_(None))
    )
    total_result = await db.execute(total_tours_query)
    total_tours = total_result.scalar() or 0

    # Count published tours
    published_query = select(func.count(Tour.id)).where(
        and_(
            Tour.user_id == user_id,
            Tour.status == TourStatus.published,
            Tour.deleted_at.is_(None)
        )
    )
    published_result = await db.execute(published_query)
    published_tours = published_result.scalar() or 0

    # Sum view counts
    views_query = select(func.sum(Tour.view_count)).where(
        and_(Tour.user_id == user_id, Tour.deleted_at.is_(None))
    )
    views_result = await db.execute(views_query)
    total_views = views_result.scalar() or 0

    # Count scenes
    scenes_query = select(func.count(Scene.id)).join(Tour).where(
        and_(Tour.user_id == user_id, Tour.deleted_at.is_(None))
    )
    scenes_result = await db.execute(scenes_query)
    total_scenes = scenes_result.scalar() or 0

    # Storage calculation would require file tracking
    # For now, estimate based on scene count (average 10MB per scene)
    storage_used = total_scenes * 10 * 1024 * 1024  # 10MB per scene
    storage_limit = 5 * 1024 * 1024 * 1024  # 5GB default

    return DashboardStats(
        total_tours=total_tours,
        published_tours=published_tours,
        total_views=total_views,
        total_scenes=total_scenes,
        storage_used=storage_used,
        storage_limit=storage_limit
    )


async def record_analytics_event(
    db: AsyncSession,
    tour_id: str,
    event_type: str,
    scene_id: Optional[str] = None,
    hotspot_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
    device_type: Optional[str] = None,
    session_id: Optional[str] = None,
    country: Optional[str] = None,
    event_data: Optional[dict] = None,
    increment_counts: bool = True,
) -> None:
    """Record an analytics event for a tour."""
    event = TourAnalyticsEvent(
        tour_id=tour_id,
        event_type=event_type,
        scene_id=scene_id,
        hotspot_id=hotspot_id,
        user_agent=user_agent,
        ip_address=ip_address,
        device_type=device_type,
        session_id=session_id,
        country=country,
        event_data=event_data,
    )

    db.add(event)

    # Also increment tour counters when requested
    if increment_counts and event_type in {"view", "like", "unlike", "share"}:
        tour_query = select(Tour).where(Tour.id == tour_id)
        result = await db.execute(tour_query)
        tour = result.scalar_one_or_none()
        if tour:
            if event_type == "view":
                tour.view_count += 1
            elif event_type == "like":
                tour.like_count += 1
            elif event_type == "unlike":
                tour.like_count = max(tour.like_count - 1, 0)
            elif event_type == "share":
                tour.share_count += 1

    await db.commit()


async def get_dashboard_realtime_stats(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """Get realtime dashboard metrics for tours."""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    last_hour = now - timedelta(hours=1)
    active_window = now - timedelta(minutes=5)

    tour_ids_query = select(Tour.id).where(
        and_(Tour.user_id == user_id, Tour.deleted_at.is_(None))
    )
    tour_ids_result = await db.execute(tour_ids_query)
    tour_ids = [row[0] for row in tour_ids_result.fetchall()]
    if not tour_ids:
        return {
            "active_sessions": 0,
            "views_last_hour": 0,
            "likes_last_hour": 0,
            "shares_last_hour": 0,
            "avg_session_duration": 0.0,
            "recent_views": [],
        }

    events_query = select(TourAnalyticsEvent).where(
        and_(
            TourAnalyticsEvent.tour_id.in_(tour_ids),
            TourAnalyticsEvent.created_at >= last_hour,
        )
    )
    events_result = await db.execute(events_query)
    events = list(events_result.scalars().all())

    active_sessions = {
        event.session_id
        for event in events
        if event.session_id and event.created_at >= active_window
    }

    views_last_hour = sum(1 for event in events if event.event_type == "view")
    likes_last_hour = sum(1 for event in events if event.event_type == "like")
    shares_last_hour = sum(1 for event in events if event.event_type == "share")

    session_starts: dict = {}
    session_durations: List[float] = []
    for event in events:
        payload = event.event_data or {}
        if event.event_type == "session_start" and event.session_id:
            session_starts[event.session_id] = event.created_at
        if event.event_type in {"session_end", "session_duration"}:
            duration = payload.get("duration_seconds")
            if duration is None and payload.get("duration_ms") is not None:
                duration = payload.get("duration_ms") / 1000
            if duration is None and payload.get("duration") is not None:
                duration = payload.get("duration")
            if duration is None and event.session_id and event.session_id in session_starts:
                duration = (event.created_at - session_starts[event.session_id]).total_seconds()
            if duration is not None:
                session_durations.append(float(duration))

    avg_session_duration = (
        sum(session_durations) / len(session_durations) if session_durations else 0.0
    )

    bucket_minutes = 5
    buckets: dict = {}
    for event in events:
        if event.event_type != "view":
            continue
        bucket_start = event.created_at.replace(
            minute=(event.created_at.minute // bucket_minutes) * bucket_minutes,
            second=0,
            microsecond=0,
        )
        key = bucket_start.isoformat()
        buckets[key] = buckets.get(key, 0) + 1

    recent_views = [
        DailyView(date=ts, views=count)
        for ts, count in sorted(buckets.items())
    ]

    return {
        "active_sessions": len(active_sessions),
        "views_last_hour": views_last_hour,
        "likes_last_hour": likes_last_hour,
        "shares_last_hour": shares_last_hour,
        "avg_session_duration": avg_session_duration,
        "recent_views": recent_views,
    }


# ====================
# Scene Image Processing
# ====================

async def process_scene_image_background(
    scene_id: str,
    tour_id: str,
    image_url: str,
    db_url: str,
) -> None:
    """
    Background task to process a scene image and generate thumbnails.

    This function runs asynchronously after scene creation to generate
    thumbnails and extract metadata without blocking the API response.

    Args:
        scene_id: The scene ID
        tour_id: The tour ID
        image_url: URL of the scene image
        db_url: Database URL for creating a new session
    """
    from app.core.database import get_async_session_factory
    from app.services.storage import storage_service

    try:
        logger.info(f"Starting background processing for scene {scene_id}")

        # Process the image
        result = await storage_service.process_existing_scene_image(
            image_url=image_url,
            tour_id=tour_id,
            scene_id=scene_id,
        )

        # Create a new database session for the background task
        session_factory = get_async_session_factory()
        async with session_factory() as db:
            # Update the scene with the processed data
            query = select(Scene).where(Scene.id == scene_id)
            db_result = await db.execute(query)
            scene = db_result.scalar_one_or_none()

            if scene:
                if result.get("thumbnail_url"):
                    scene.thumbnail_url = result["thumbnail_url"]

                # Update metadata with EXIF info
                current_metadata = scene.scene_metadata or {}
                if result.get("exif"):
                    current_metadata["exif"] = result["exif"]
                if result.get("width") and result.get("height"):
                    current_metadata["dimensions"] = {
                        "width": result["width"],
                        "height": result["height"],
                    }
                if result.get("is_panorama") is not None:
                    current_metadata["is_panorama"] = result["is_panorama"]

                scene.scene_metadata = current_metadata
                scene.is_processed = True

                await db.commit()
                logger.info(f"Scene {scene_id} processed successfully")
            else:
                logger.warning(f"Scene {scene_id} not found during processing")

    except Exception as e:
        logger.error(f"Failed to process scene {scene_id}: {str(e)}")
        # Mark scene as failed
        try:
            session_factory = get_async_session_factory()
            async with session_factory() as db:
                query = select(Scene).where(Scene.id == scene_id)
                db_result = await db.execute(query)
                scene = db_result.scalar_one_or_none()
                if scene:
                    scene.is_processed = True
                    scene.processing_error = str(e)
                    await db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to update scene processing error: {str(inner_e)}")
    finally:
        # Clean up task registry
        _scene_processing_tasks.pop(scene_id, None)


def schedule_scene_processing(
    scene_id: str,
    tour_id: str,
    image_url: str,
) -> None:
    """
    Schedule a scene for background processing.

    Args:
        scene_id: The scene ID
        tour_id: The tour ID
        image_url: URL of the scene image
    """
    from app.core.config import settings

    if not image_url:
        logger.warning(f"No image URL provided for scene {scene_id}")
        return

    # Avoid duplicate processing
    if scene_id in _scene_processing_tasks:
        logger.info(f"Scene {scene_id} already being processed")
        return

    # Schedule the background task
    task = asyncio.create_task(
        process_scene_image_background(
            scene_id=scene_id,
            tour_id=tour_id,
            image_url=image_url,
            db_url=settings.ASYNC_DATABASE_URL,
        )
    )
    _scene_processing_tasks[scene_id] = task
    logger.info(f"Scheduled processing for scene {scene_id}")


# ====================
# Floor Plan Services
# ====================

async def get_floor_plans(
    db: AsyncSession,
    tour_id: str,
    user_id: int
) -> List[FloorPlan]:
    """Get all floor plans for a tour."""
    # Verify tour access
    await get_tour(db, tour_id, user_id, include_scenes=False)

    query = select(FloorPlan).where(
        FloorPlan.tour_id == tour_id
    ).order_by(FloorPlan.floor_number)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_floor_plan(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int
) -> FloorPlan:
    """Get a floor plan by ID."""
    query = select(FloorPlan).where(FloorPlan.id == floor_plan_id)
    result = await db.execute(query)
    floor_plan = result.scalar_one_or_none()

    if not floor_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Floor plan not found"
        )

    # Verify tour ownership
    tour = await get_tour(db, floor_plan.tour_id, user_id, include_scenes=False)
    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this floor plan"
        )

    return floor_plan


async def create_floor_plan(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    data: FloorPlanCreate
) -> FloorPlan:
    """Create a new floor plan for a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)

    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to add floor plans to this tour"
        )

    # Convert markers to list of dicts
    markers_data = [m.model_dump() for m in data.markers] if data.markers else []

    floor_plan = FloorPlan(
        id=str(uuid4()),
        tour_id=tour_id,
        name=data.name,
        image_url=data.image_url,
        floor_number=data.floor_number,
        markers=markers_data,
    )

    db.add(floor_plan)
    await db.commit()
    await db.refresh(floor_plan)

    logger.info(f"Floor plan created: {floor_plan.id} in tour {tour_id}")
    return floor_plan


async def update_floor_plan(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int,
    data: FloorPlanUpdate
) -> FloorPlan:
    """Update a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "markers" and value is not None:
            # Convert markers to list of dicts
            value = [m if isinstance(m, dict) else m.model_dump() for m in value]
        setattr(floor_plan, field, value)

    await db.commit()
    await db.refresh(floor_plan)

    logger.info(f"Floor plan updated: {floor_plan_id}")
    return floor_plan


async def update_floor_plan_markers(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int,
    markers: List[dict]
) -> FloorPlan:
    """Update only the markers of a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id)

    floor_plan.markers = markers
    await db.commit()
    await db.refresh(floor_plan)

    logger.info(f"Floor plan markers updated: {floor_plan_id}")
    return floor_plan


async def delete_floor_plan(
    db: AsyncSession,
    floor_plan_id: str,
    user_id: int
) -> bool:
    """Delete a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id)

    await db.delete(floor_plan)
    await db.commit()

    logger.info(f"Floor plan deleted: {floor_plan_id}")
    return True
