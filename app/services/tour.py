"""
Service layer for 360 Virtual Tour operations.

This module contains business logic for tour, scene, and hotspot management.
"""

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import bleach
from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.enums import HotspotType, TourStatus, TourVisibility
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


_HOTSPOT_HTML_ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "u",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "img",
    "div",
    "span",
    "code",
    "pre",
]
_HOTSPOT_HTML_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
}
_HOTSPOT_HTML_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]


def _ensure_tour_ownership(tour: Tour, user_id: int, action: str = "access") -> None:
    """Raise 403 if user doesn't own the tour."""
    if tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You don't have permission to {action} this tour",
        )


def _ensure_scene_ownership(scene: Scene, user_id: int, action: str = "access") -> None:
    """Raise 403 if user doesn't own the scene's tour."""
    if scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You don't have permission to {action} this scene",
        )


def _extract_session_duration(event: TourAnalyticsEvent, session_starts: dict) -> Optional[float]:
    """Extract session duration from an analytics event."""
    payload = event.event_data or {}
    duration = payload.get("duration_seconds")
    if duration is None and payload.get("duration_ms") is not None:
        duration = payload.get("duration_ms") / 1000
    if duration is None and payload.get("duration") is not None:
        duration = payload.get("duration")
    if duration is None and event.session_id and event.session_id in session_starts:
        duration = (event.created_at - session_starts[event.session_id]).total_seconds()
    return float(duration) if duration is not None else None


def _is_safe_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sanitize_hotspot_html(value: str) -> str:
    return bleach.clean(
        value,
        tags=_HOTSPOT_HTML_ALLOWED_TAGS,
        attributes=_HOTSPOT_HTML_ALLOWED_ATTRIBUTES,
        protocols=_HOTSPOT_HTML_ALLOWED_PROTOCOLS,
        strip=True,
    )


def _extract_youtube_id(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.hostname or "").lower()
    if host in {"youtu.be"}:
        video_id = parsed.path.lstrip("/")
        return video_id or None

    if host.endswith("youtube.com"):
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            return (qs.get("v", [None])[0]) or None
        if parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                return parts[1] or None

    return None


def _extract_vimeo_id(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.hostname or "").lower()
    if not host.endswith("vimeo.com"):
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    if parts[0] == "video" and len(parts) >= 2:
        return parts[1] if parts[1].isdigit() else None

    return parts[0] if parts[0].isdigit() else None


def _normalize_hotspot_content(
    hotspot_type: HotspotType,
    content: Optional[dict],
) -> Optional[dict]:
    if content is None:
        content = {}

    if not isinstance(content, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Hotspot content must be an object",
        )

    normalized: dict = {"kind": hotspot_type.value}

    if hotspot_type == HotspotType.link:
        raw_url = content.get("url") or content.get("link_url")
        if not raw_url or not isinstance(raw_url, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Link hotspots require content.url",
            )
        if not _is_safe_http_url(raw_url):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Link hotspots require a valid http(s) URL",
            )
        normalized["url"] = raw_url
        target = content.get("target")
        if target not in {"_blank", "_self", None}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Link hotspot content.target must be _blank or _self",
            )
        if target is None:
            link_new_tab = content.get("link_new_tab")
            normalized["target"] = "_self" if link_new_tab is False else "_blank"
        else:
            normalized["target"] = target
        label = content.get("label")
        if isinstance(label, str) and label.strip():
            normalized["label"] = label.strip()[:255]
        return normalized

    if hotspot_type == HotspotType.audio:
        audio_url = content.get("audio_url") or content.get("url")
        if not audio_url or not isinstance(audio_url, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Audio hotspots require content.audio_url",
            )
        if not _is_safe_http_url(audio_url):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Audio hotspots require a valid http(s) URL",
            )
        normalized["audio_url"] = audio_url
        if "autoplay" in content:
            normalized["autoplay"] = bool(content.get("autoplay"))
        if "loop" in content:
            normalized["loop"] = bool(content.get("loop"))
        return normalized

    if hotspot_type == HotspotType.video:
        youtube_id = content.get("youtube_id")
        vimeo_id = content.get("vimeo_id")
        video_url = content.get("video_url") or content.get("url")

        if isinstance(video_url, str) and (youtube_id is None and vimeo_id is None):
            youtube_id = _extract_youtube_id(video_url)
            vimeo_id = _extract_vimeo_id(video_url)

        if isinstance(youtube_id, str) and youtube_id.strip():
            normalized["youtube_id"] = youtube_id.strip()
        elif isinstance(vimeo_id, str) and vimeo_id.strip():
            normalized["vimeo_id"] = vimeo_id.strip()
        elif isinstance(video_url, str) and video_url.strip():
            if not _is_safe_http_url(video_url):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Video hotspots require a valid http(s) URL",
                )
            normalized["video_url"] = video_url.strip()
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Video hotspots require content.video_url or content.youtube_id or content.vimeo_id",
            )

        for key in ("autoplay", "muted", "loop"):
            if key in content:
                normalized[key] = bool(content.get(key))

        poster_url = content.get("poster_url") or content.get("poster")
        if isinstance(poster_url, str) and poster_url.strip():
            if not _is_safe_http_url(poster_url):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Video hotspot poster_url must be a valid http(s) URL",
                )
            normalized["poster_url"] = poster_url.strip()

        return normalized

    if hotspot_type == HotspotType.info:
        text = content.get("text")
        html = content.get("html")
        image_url = content.get("image_url")

        if isinstance(text, str) and text.strip():
            normalized["text"] = text
        if isinstance(html, str) and html.strip():
            normalized["html"] = _sanitize_hotspot_html(html)
        if isinstance(image_url, str) and image_url.strip():
            if not _is_safe_http_url(image_url):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Info hotspot image_url must be a valid http(s) URL",
                )
            normalized["image_url"] = image_url.strip()

        return normalized if len(normalized) > 1 else None

    if hotspot_type == HotspotType.custom:
        html = content.get("html") or content.get("custom_html")
        if isinstance(html, str) and html.strip():
            normalized["html"] = _sanitize_hotspot_html(html)

        component_key = content.get("component_key") or content.get("component")
        if isinstance(component_key, str) and component_key.strip():
            normalized["component_key"] = component_key.strip()[:100]

        props = content.get("props")
        if isinstance(props, dict):
            normalized["props"] = props

        return normalized if len(normalized) > 1 else None

    # Navigation hotspots typically rely on target_scene_id; content is optional.
    if hotspot_type == HotspotType.navigation:
        return normalized

    return content or None


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
    search: Optional[str] = None,
) -> dict:
    """Get paginated list of tours for a user."""
    query = select(Tour).where(and_(Tour.user_id == user_id, Tour.deleted_at.is_(None)))

    if status_filter:
        query = query.where(Tour.status == status_filter)

    if search:
        search_term = f"%{search}%"
        query = query.where(or_(Tour.title.ilike(search_term), Tour.description.ilike(search_term)))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Calculate pagination
    total_pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size

    scene_counts = (
        select(
            Scene.tour_id.label("tour_id"),
            func.count(Scene.id).label("scene_count"),
        )
        .group_by(Scene.tour_id)
        .subquery()
    )

    query = (
        query.outerjoin(scene_counts, scene_counts.c.tour_id == Tour.id)
        .add_columns(
            func.coalesce(scene_counts.c.scene_count, 0).label("scene_count"),
        )
        .order_by(Tour.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(query)
    rows = result.all()

    tours: List[dict] = []
    for tour, scene_count in rows:
        tours.append(
            {
                "id": tour.id,
                "user_id": tour.user_id,
                "title": tour.title,
                "description": tour.description,
                "status": tour.status,
                "is_public": tour.is_public,
                "settings": tour.settings,
                "is_featured": tour.is_featured,
                "view_count": tour.view_count,
                "like_count": tour.like_count,
                "share_count": tour.share_count,
                "thumbnail_url": tour.thumbnail_url,
                "published_at": tour.published_at,
                "archived_at": tour.archived_at,
                "created_at": tour.created_at,
                "updated_at": tour.updated_at,
                "deleted_at": tour.deleted_at,
                "scene_count": int(scene_count or 0),
                "scenes": None,
            }
        )

    return {
        "items": tours,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


async def get_tour(
    db: AsyncSession, tour_id: str, user_id: Optional[int] = None, include_scenes: bool = True
) -> Tour:
    """Get a single tour by ID."""
    query = select(Tour).where(and_(Tour.id == tour_id, Tour.deleted_at.is_(None)))

    if include_scenes:
        query = query.options(selectinload(Tour.scenes).selectinload(Scene.hotspots))

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tour not found")

    is_owner = user_id is not None and tour.user_id == user_id
    is_publicly_accessible = tour.status == TourStatus.published and bool(tour.is_public)

    if not is_owner and not is_publicly_accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN
            if user_id is not None
            else status.HTTP_404_NOT_FOUND,
            detail="You don't have access to this tour"
            if user_id is not None
            else "Tour not found",
        )

    return tour


async def create_tour(db: AsyncSession, user_id: int, data: TourCreate) -> Tour:
    """Create a new tour."""
    # Determine visibility - prefer explicit visibility, fall back to is_public for backward compat
    visibility = (
        data.visibility
        if data.visibility
        else (TourVisibility.public if data.is_public else TourVisibility.private)
    )
    # Keep is_public in sync for backward compatibility
    is_public = visibility == TourVisibility.public

    tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=data.title,
        description=data.description,
        status=data.status or TourStatus.draft,
        is_public=is_public,
        visibility=visibility,
        settings=data.settings.model_dump() if data.settings else None,
    )

    db.add(tour)
    await db.commit()

    logger.info(f"Tour created: {tour.id} by user {user_id}")
    return await get_tour(db=db, tour_id=tour.id, user_id=user_id, include_scenes=True)


async def update_tour(db: AsyncSession, tour_id: str, user_id: int, data: TourUpdate) -> Tour:
    """Update a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "update")

    # Update fields
    update_data = data.model_dump(exclude_unset=True)

    # Handle visibility/is_public sync for backward compatibility
    if "visibility" in update_data:
        # If visibility is set, sync is_public
        update_data["is_public"] = update_data["visibility"] == TourVisibility.public
    elif "is_public" in update_data:
        # If only is_public is set (legacy), derive visibility
        update_data["visibility"] = (
            TourVisibility.public if update_data["is_public"] else TourVisibility.private
        )

    for field, value in update_data.items():
        if field == "settings" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
        setattr(tour, field, value)

    await db.commit()

    logger.info(f"Tour updated: {tour_id}")
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def delete_tour(db: AsyncSession, tour_id: str, user_id: int) -> bool:
    """Soft delete a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "delete")

    tour.deleted_at = datetime.utcnow()
    tour.status = TourStatus.archived
    await db.commit()

    logger.info(f"Tour deleted: {tour_id}")
    return True


async def publish_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Publish a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=True)
    _ensure_tour_ownership(tour, user_id, "publish")

    # Check if tour has scenes
    if not tour.scenes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot publish a tour without scenes"
        )

    tour.status = TourStatus.published
    tour.published_at = datetime.utcnow()
    tour.is_public = True

    await db.commit()

    logger.info(f"Tour published: {tour_id}")
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def unpublish_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Unpublish a tour (set to draft)."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "unpublish")

    tour.status = TourStatus.draft
    tour.is_public = False

    await db.commit()

    logger.info(f"Tour unpublished: {tour_id}")
    return await get_tour(db=db, tour_id=tour_id, user_id=user_id, include_scenes=True)


async def duplicate_tour(db: AsyncSession, tour_id: str, user_id: int) -> Tour:
    """Duplicate a tour with all its scenes and hotspots."""
    original = await get_tour(db, tour_id, user_id, include_scenes=True)
    _ensure_tour_ownership(original, user_id, "duplicate")

    # Create new tour
    new_tour = Tour(
        id=str(uuid4()),
        user_id=user_id,
        title=f"{original.title} (Copy)",
        description=original.description,
        status=TourStatus.draft,
        is_public=False,
        visibility=original.visibility,
        settings=original.settings,
        thumbnail_url=original.thumbnail_url,
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
            is_processed=scene.is_processed,
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
                is_active=hotspot.is_active,
            )
            db.add(new_hotspot)

    await db.commit()

    # Reload with scenes
    return await get_tour(db, new_tour.id, user_id, include_scenes=True)


# ====================
# Scene Services
# ====================


async def get_scenes(db: AsyncSession, tour_id: str, user_id: Optional[int] = None) -> List[Scene]:
    """Get all scenes for a tour."""
    # Verify tour access
    await get_tour(db, tour_id, user_id, include_scenes=False)

    query = (
        select(Scene)
        .where(Scene.tour_id == tour_id)
        .options(selectinload(Scene.hotspots))
        .order_by(Scene.order_index)
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_scene(db: AsyncSession, scene_id: str, user_id: Optional[int] = None) -> Scene:
    """Get a single scene by ID."""
    query = (
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.hotspots), selectinload(Scene.tour))
    )

    result = await db.execute(query)
    scene = result.scalar_one_or_none()

    if not scene:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene not found")

    if user_id is not None and scene.tour.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this scene",
        )

    return scene


async def create_scene(db: AsyncSession, tour_id: str, user_id: int, data: SceneCreate) -> Scene:
    """Create a new scene in a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "add scenes to")

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

    # Schedule background processing for thumbnail generation
    if data.image_url and not data.thumbnail_url:
        schedule_scene_processing(
            scene_id=scene.id,
            tour_id=tour_id,
            image_url=data.image_url,
            user_id=user_id,
        )
    else:
        # Mark as processed if thumbnail already provided
        scene.is_processed = True
        await db.commit()

    logger.info(f"Scene created: {scene.id} in tour {tour_id}")
    return await get_scene(db=db, scene_id=scene.id, user_id=user_id)


async def update_scene(db: AsyncSession, scene_id: str, user_id: int, data: SceneUpdate) -> Scene:
    """Update a scene."""
    scene = await get_scene(db, scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "update")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "metadata" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
            setattr(scene, "scene_metadata", value)
        else:
            setattr(scene, field, value)

    await db.commit()

    logger.info(f"Scene updated: {scene_id}")
    return await get_scene(db=db, scene_id=scene_id, user_id=user_id)


async def delete_scene(db: AsyncSession, scene_id: str, user_id: int) -> bool:
    """Delete a scene."""
    scene = await get_scene(db, scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "delete")

    await db.delete(scene)
    await db.commit()

    logger.info(f"Scene deleted: {scene_id}")
    return True


async def reorder_scenes(
    db: AsyncSession, tour_id: str, user_id: int, scene_ids: List[str]
) -> List[Scene]:
    """Reorder scenes in a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "reorder scenes in")

    # Validation: Check for duplicates
    if len(scene_ids) != len(set(scene_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate scene_ids found in reorder request",
        )

    # Get all existing scenes for this tour
    existing_scenes_query = select(Scene.id).where(Scene.tour_id == tour_id)
    result = await db.execute(existing_scenes_query)
    existing_scene_ids = set(result.scalars().all())

    # Validation: Check all provided scene_ids exist and belong to this tour
    provided_scene_ids = set(scene_ids)
    invalid_scene_ids = provided_scene_ids - existing_scene_ids
    if invalid_scene_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid scene_ids: {list(invalid_scene_ids)}. Scenes must exist and belong to this tour.",
        )

    # Validation: Check all scenes in the tour are included
    missing_scene_ids = existing_scene_ids - provided_scene_ids
    if missing_scene_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing scene_ids: {list(missing_scene_ids)}. All tour scenes must be included in reorder request.",
        )

    # Update order_index for each scene
    for index, scene_id in enumerate(scene_ids):
        query = select(Scene).where(and_(Scene.id == scene_id, Scene.tour_id == tour_id))
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
    db: AsyncSession, scene_id: str, user_id: Optional[int] = None
) -> List[Hotspot]:
    """Get all hotspots for a scene."""
    # Verify scene access
    await get_scene(db, scene_id, user_id)

    query = select(Hotspot).where(Hotspot.scene_id == scene_id).order_by(Hotspot.order_index)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hotspot(db: AsyncSession, hotspot_id: str, user_id: Optional[int] = None) -> Hotspot:
    """Get a single hotspot by ID."""
    query = (
        select(Hotspot)
        .where(Hotspot.id == hotspot_id)
        .options(selectinload(Hotspot.scene).selectinload(Scene.tour))
    )

    result = await db.execute(query)
    hotspot = result.scalar_one_or_none()

    if not hotspot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotspot not found")

    return hotspot


async def create_hotspot(
    db: AsyncSession, scene_id: str, user_id: int, data: HotspotCreate
) -> Hotspot:
    """Create a new hotspot in a scene."""
    scene = await get_scene(db, scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "add hotspots to")

    if data.type == HotspotType.navigation:
        if not data.target_scene_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Navigation hotspots require target_scene_id",
            )
        target_scene = await get_scene(db, data.target_scene_id, user_id)
        if target_scene.tour_id != scene.tour_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Navigation hotspots must target a scene in the same tour",
            )

    normalized_content = _normalize_hotspot_content(data.type, data.content)

    # Get max order_index
    max_order_query = select(func.max(Hotspot.order_index)).where(Hotspot.scene_id == scene_id)
    result = await db.execute(max_order_query)
    max_order = result.scalar() or -1

    hotspot = Hotspot(
        id=str(uuid4()),
        scene_id=scene_id,
        type=data.type,
        position=data.position.model_dump(),
        target_scene_id=data.target_scene_id if data.type == HotspotType.navigation else None,
        title=data.title,
        description=data.description,
        icon=data.icon,
        icon_name=data.icon_name,
        icon_color=data.icon_color,
        icon_size=data.icon_size or 32,
        content=normalized_content,
        custom_data=data.custom_data,
        order_index=max_order + 1,
    )

    db.add(hotspot)
    await db.commit()
    await db.refresh(hotspot)

    logger.info(f"Hotspot created: {hotspot.id} in scene {scene_id}")
    return hotspot


async def update_hotspot(
    db: AsyncSession, hotspot_id: str, user_id: int, data: HotspotUpdate
) -> Hotspot:
    """Update a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    # Get scene for permission check
    scene = await get_scene(db, hotspot.scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "update hotspots in")

    update_data = data.model_dump(exclude_unset=True)

    next_type = data.type or hotspot.type
    next_target_scene_id = (
        data.target_scene_id if "target_scene_id" in update_data else hotspot.target_scene_id
    )
    next_content = data.content if "content" in update_data else hotspot.content

    if next_type == HotspotType.navigation:
        if not next_target_scene_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Navigation hotspots require target_scene_id",
            )
        target_scene = await get_scene(db, next_target_scene_id, user_id)
        if target_scene.tour_id != scene.tour_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Navigation hotspots must target a scene in the same tour",
            )
    else:
        next_target_scene_id = None

    normalized_content = _normalize_hotspot_content(next_type, next_content)

    for field, value in update_data.items():
        if field == "position" and value is not None:
            value = value if isinstance(value, dict) else value.model_dump()
        if field == "content":
            value = normalized_content
        if field == "target_scene_id":
            value = next_target_scene_id
        setattr(hotspot, field, value)

    if "content" not in update_data and normalized_content != hotspot.content:
        hotspot.content = normalized_content
    if "target_scene_id" not in update_data and next_target_scene_id != hotspot.target_scene_id:
        hotspot.target_scene_id = next_target_scene_id

    await db.commit()
    await db.refresh(hotspot)

    logger.info(f"Hotspot updated: {hotspot_id}")
    return hotspot


async def delete_hotspot(db: AsyncSession, hotspot_id: str, user_id: int) -> bool:
    """Delete a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    scene = await get_scene(db, hotspot.scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "delete hotspots from")

    await db.delete(hotspot)
    await db.commit()

    logger.info(f"Hotspot deleted: {hotspot_id}")
    return True


async def update_hotspot_position(
    db: AsyncSession, hotspot_id: str, user_id: int, position: HotspotPositionUpdate
) -> Hotspot:
    """Update only the position of a hotspot."""
    hotspot = await get_hotspot(db, hotspot_id, user_id)

    scene = await get_scene(db, hotspot.scene_id, user_id)
    _ensure_scene_ownership(scene, user_id, "update hotspots in")

    # Update position while preserving radius if it exists
    current_position = hotspot.position or {}
    hotspot.position = {
        "yaw": position.yaw,
        "pitch": position.pitch,
        "radius": current_position.get("radius"),
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
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> TourAnalytics:
    """Get analytics for a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "access analytics for")

    # Build query with date filters
    query = select(TourAnalyticsEvent).where(TourAnalyticsEvent.tour_id == tour_id)

    if start_date:
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        query = query.where(TourAnalyticsEvent.created_at >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
        query = query.where(TourAnalyticsEvent.created_at < end_dt)

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
            duration = _extract_session_duration(event, session_starts)
            if duration is not None:
                session_durations.append(duration)

        if event.device_type and event.device_type in device_counts:
            device_counts[event.device_type] += 1

        if event.country:
            country_counts[event.country] = country_counts.get(event.country, 0) + 1

        date_str = event.created_at.strftime("%Y-%m-%d")
        if event.event_type == "view":
            daily_views_map[date_str] = daily_views_map.get(date_str, 0) + 1

    daily_views = [
        DailyView(date=date, views=views) for date, views in sorted(daily_views_map.items())
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
        daily_views=daily_views,
    )


async def get_dashboard_stats(db: AsyncSession, user_id: int) -> DashboardStats:
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
            Tour.user_id == user_id, Tour.status == TourStatus.published, Tour.deleted_at.is_(None)
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
    scenes_query = (
        select(func.count(Scene.id))
        .join(Tour)
        .where(and_(Tour.user_id == user_id, Tour.deleted_at.is_(None)))
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
        storage_limit=storage_limit,
    )


async def get_tour_heatmap(
    db: AsyncSession,
    tour_id: str,
    scene_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get aggregated heatmap data for a tour.

    Returns heatmap points grouped by scene with aggregated intensity values
    for visualization of user interaction patterns.

    Args:
        db: Database session
        tour_id: Tour ID to get heatmap for
        scene_id: Optional scene ID to filter by
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering

    Returns:
        Dictionary with scene_ids as keys and lists of heatmap points
    """
    from datetime import datetime

    # Query heatmap events
    conditions = [TourAnalyticsEvent.tour_id == tour_id, TourAnalyticsEvent.event_type == "heatmap"]

    if scene_id:
        conditions.append(TourAnalyticsEvent.scene_id == scene_id)

    if start_date:
        conditions.append(
            TourAnalyticsEvent.created_at >= datetime.combine(start_date, datetime.min.time())
        )

    if end_date:
        conditions.append(
            TourAnalyticsEvent.created_at <= datetime.combine(end_date, datetime.max.time())
        )

    query = select(TourAnalyticsEvent).where(and_(*conditions))
    result = await db.execute(query)
    events = result.scalars().all()

    # Group heatmap points by scene and aggregate by grid cells
    scene_heatmaps: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for event in events:
        event_data = event.event_data or {}
        scene_key = event.scene_id or "unknown"

        if scene_key not in scene_heatmaps:
            scene_heatmaps[scene_key] = {}

        # Create grid cell key (rounded to nearest 5 degrees for aggregation)
        yaw = event_data.get("yaw", 0)
        pitch = event_data.get("pitch", 0)
        grid_key = f"{round(yaw / 5) * 5}_{round(pitch / 5) * 5}"

        if grid_key not in scene_heatmaps[scene_key]:
            scene_heatmaps[scene_key][grid_key] = {
                "yaw": round(yaw / 5) * 5,
                "pitch": round(pitch / 5) * 5,
                "intensity": 0,
                "count": 0,
            }

        # Aggregate intensity
        scene_heatmaps[scene_key][grid_key]["intensity"] += event_data.get("intensity", 1)
        scene_heatmaps[scene_key][grid_key]["count"] += 1

    # Convert to output format with normalized intensity
    output: Dict[str, List[Dict[str, Any]]] = {}

    for scene_key, grid_cells in scene_heatmaps.items():
        points = list(grid_cells.values())

        # Normalize intensity to 0-1 range
        if points:
            max_intensity = max(p["intensity"] for p in points)
            if max_intensity > 0:
                for p in points:
                    p["intensity"] = p["intensity"] / max_intensity

        output[scene_key] = points

    return output


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

    tour_ids_query = select(Tour.id).where(and_(Tour.user_id == user_id, Tour.deleted_at.is_(None)))
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
        if event.event_type == "session_start" and event.session_id:
            session_starts[event.session_id] = event.created_at
        if event.event_type in {"session_end", "session_duration"}:
            duration = _extract_session_duration(event, session_starts)
            if duration is not None:
                session_durations.append(duration)

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

    recent_views = [DailyView(date=ts, views=count) for ts, count in sorted(buckets.items())]

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
    user_id: int,
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
        user_id: User ID for user-scoped storage paths
    """
    from app.core.database import get_async_session_factory
    from app.services.storage import storage_service

    try:
        logger.info(f"Starting background processing for scene {scene_id}")

        # Process the image with user-scoped path
        result = await storage_service.process_existing_scene_image(
            image_url=image_url,
            tour_id=tour_id,
            scene_id=scene_id,
            user_id=user_id,
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
    user_id: int,
) -> None:
    """
    Schedule a scene for background processing.

    Args:
        scene_id: The scene ID
        tour_id: The tour ID
        image_url: URL of the scene image
        user_id: User ID for user-scoped storage paths
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
            user_id=user_id,
        )
    )
    _scene_processing_tasks[scene_id] = task
    logger.info(f"Scheduled processing for scene {scene_id}")


# ====================
# Floor Plan Services
# ====================


async def get_floor_plans(db: AsyncSession, tour_id: str, user_id: int) -> List[FloorPlan]:
    """Get all floor plans for a tour."""
    # Verify tour access
    await get_tour(db, tour_id, user_id, include_scenes=False)

    query = select(FloorPlan).where(FloorPlan.tour_id == tour_id).order_by(FloorPlan.floor_number)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_floor_plan(db: AsyncSession, floor_plan_id: str, user_id: int) -> FloorPlan:
    """Get a floor plan by ID."""
    query = select(FloorPlan).where(FloorPlan.id == floor_plan_id)
    result = await db.execute(query)
    floor_plan = result.scalar_one_or_none()

    if not floor_plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Floor plan not found")

    # Verify tour ownership
    tour = await get_tour(db, floor_plan.tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "access floor plans in")

    return floor_plan


async def create_floor_plan(
    db: AsyncSession, tour_id: str, user_id: int, data: FloorPlanCreate
) -> FloorPlan:
    """Create a new floor plan for a tour."""
    tour = await get_tour(db, tour_id, user_id, include_scenes=False)
    _ensure_tour_ownership(tour, user_id, "add floor plans to")

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
    db: AsyncSession, floor_plan_id: str, user_id: int, data: FloorPlanUpdate
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
    db: AsyncSession, floor_plan_id: str, user_id: int, markers: List[dict]
) -> FloorPlan:
    """Update only the markers of a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id)

    floor_plan.markers = markers
    await db.commit()
    await db.refresh(floor_plan)

    logger.info(f"Floor plan markers updated: {floor_plan_id}")
    return floor_plan


async def delete_floor_plan(db: AsyncSession, floor_plan_id: str, user_id: int) -> bool:
    """Delete a floor plan."""
    floor_plan = await get_floor_plan(db, floor_plan_id, user_id)

    await db.delete(floor_plan)
    await db.commit()

    logger.info(f"Floor plan deleted: {floor_plan_id}")
    return True
