"""
Public 360 Virtual Tour API Endpoints.

This module provides unauthenticated endpoints for viewing published tours.
These endpoints are used by the public viewer and embed page.
"""
import threading
import time
import uuid as _uuid
from collections import defaultdict

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.enums import TourStatus, TourVisibility
from app.models.tours import FloorPlan, Scene, Tour
from app.schemas.tour import TourEventPayload, TourWithScenes
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)

# ── Generic per-IP sliding-window rate limiter ─────────────────────────────────
# One helper serves both like and event endpoints; previously they had
# copy-pasted state dicts and shared a single reaper constant, which coupled
# their reap cadences and let each per-worker dict grow unbounded.
_REAP_INTERVAL_S = 300  # reap stale keys every 5 minutes
_reaper_lock = threading.Lock()


def _is_ip_rate_limited(
    client_ip: str,
    *,
    store: dict[str, list[float]],
    limit: int,
    window_s: int,
    last_reap_attr: str,
) -> bool:
    """Return True if ``client_ip`` has exceeded the per-IP rate limit.

    Mutates ``store[client_ip]`` in place (prune to window, append now) and
    periodically reaps keys whose entire window has expired. The reaper is
    guarded by a module-level lock so concurrent workers don't race on the
    same dict.
    """
    now = time.monotonic()
    window_start = now - window_s
    timestamps = store[client_ip]
    # Prune entries older than the window
    store[client_ip] = [t for t in timestamps if t > window_start]
    if len(store[client_ip]) >= limit:
        return True
    store[client_ip].append(now)

    # Periodic reap of fully-stale keys to bound memory under sustained
    # traffic from many distinct IPs. We do this on every call (cheap) and
    # gate on a per-helper last-reap timestamp stored on the store itself.
    last_reap = store.get(last_reap_attr, 0.0)
    if now - last_reap > _REAP_INTERVAL_S:
        with _reaper_lock:
            # Re-check under lock so two workers don't both decide to reap
            if now - store.get(last_reap_attr, 0.0) <= _REAP_INTERVAL_S:
                return False
            store[last_reap_attr] = now
            stale = [k for k, v in store.items() if k == last_reap_attr or not v]
            for k in stale:
                if k != last_reap_attr:
                    del store[k]
    return False


# Per-IP limiter state for like/unlike endpoints.
_like_store: dict[str, list[float]] = defaultdict(list)
_LIKE_RATE_LIMIT = 10  # max requests
_LIKE_RATE_WINDOW_S = 60  # per window


# Per-IP limiter state for analytics event endpoints.
_event_store: dict[str, list[float]] = defaultdict(list)
_EVENT_RATE_LIMIT = 120  # max requests per window (generous for heatmap pings)
_EVENT_RATE_WINDOW_S = 60


def _is_event_rate_limited(client_ip: str) -> bool:
    return _is_ip_rate_limited(
        client_ip,
        store=_event_store,
        limit=_EVENT_RATE_LIMIT,
        window_s=_EVENT_RATE_WINDOW_S,
        last_reap_attr="_last_event_reap",
    )


def _is_like_rate_limited(client_ip: str) -> bool:
    return _is_ip_rate_limited(
        client_ip,
        store=_like_store,
        limit=_LIKE_RATE_LIMIT,
        window_s=_LIKE_RATE_WINDOW_S,
        last_reap_attr="_last_like_reap",
    )


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
    """Extract the real client IP, trusting only ``settings.TRUSTED_PROXY_HOPS``
    proxies in front of us.

    X-Forwarded-For is a comma-separated chain APPENDED-TO by each proxy:
    ``client, proxy1, proxy2``. The right-most entry that we DON'T trust is
    the real client. With ``TRUSTED_PROXY_HOPS=1`` (Railway default) we trust
    one hop, so the rightmost untrusted hop = the second-from-right entry
    (the real client, with the trusted proxy's IP tacked on at the right).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        # Index from the right: 0 = closest trusted proxy, 1 = the real client
        # when we trust 1 hop. Clamp to the leftmost entry if the client chain
        # is shorter than the configured hop count (e.g. direct connection).
        idx = max(0, len(hops) - 1 - settings.TRUSTED_PROXY_HOPS)
        return hops[idx]

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip

    return request.client.host if request.client else "unknown"


def normalize_event_type(event_type: str, event_data: dict) -> str:
    """Normalize incoming event types to the backend canonical set."""
    mapping = {
        "tour_view": "view",
        "tour_share": "share",
        "tour_like": "like",
    }

    normalized = mapping.get(event_type, event_type)

    # Back-compat: accept a generic "fullscreen" event with a state flag.
    if normalized == "fullscreen":
        is_fullscreen = event_data.get("is_fullscreen")
        if is_fullscreen is None:
            is_fullscreen = event_data.get("isFullscreen")

        if is_fullscreen is True:
            return "fullscreen_enter"
        if is_fullscreen is False:
            return "fullscreen_exit"

        # Fallback when the state is not provided.
        return "fullscreen_enter"

    return normalized


@router.get("/tours/{tour_id}", response_model=TourWithScenes, summary="Get public tour")
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
    # Validate UUID format before hitting the DB.
    # PostgreSQL will throw DataError (→ 500) if an invalid string is passed
    # to a UUID column. Return 404 early to keep this side-effect-free.
    try:
        _uuid.UUID(tour_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found",
        ) from None

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

    # Check if tour is published and publicly accessible (public or unlisted)
    # Private tours require authentication and are handled by authenticated endpoints
    if tour.status != TourStatus.published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found or is not publicly accessible"
        )

    # Check visibility: both 'public' and 'unlisted' tours are accessible via direct link
    # 'private' tours are not accessible without authentication
    if tour.visibility == TourVisibility.private:
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
                event_data={"referrer": request.headers.get("referer")},
            )
            logger.info("Tracked view for tour %s from %s", tour_id, device_type)
        except Exception as e:
            # Don't fail the request if analytics tracking fails
            logger.warning("Failed to track analytics for tour %s: %s", tour_id, e)

    # Hydrate floor plans into tour.settings for the viewer (floor plans are stored in a dedicated table).
    floor_plans_query = select(FloorPlan).where(FloorPlan.tour_id == tour_id).order_by(FloorPlan.floor_number)
    floor_plans_result = await db.execute(floor_plans_query)
    floor_plans = list(floor_plans_result.scalars().all())

    payload = TourWithScenes.model_validate(tour).model_dump()
    settings_payload = payload.get("settings") or {}
    settings_payload["floor_plans"] = [
        {
            "id": fp.id,
            "name": fp.name,
            "floor_number": fp.floor_number,
            "image_url": fp.image_url,
            "markers": fp.markers or [],
        }
        for fp in floor_plans
    ]
    payload["settings"] = settings_payload

    return payload


@router.get("/tours/{tour_id}/scenes", summary="Get public tour scenes")
async def get_public_tour_scenes(
    tour_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all scenes for a publicly accessible tour.

    Returns scenes ordered by order_index with their hotspots.
    """
    # Verify tour exists and is public (public or unlisted visibility)
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.visibility.in_([TourVisibility.public, TourVisibility.unlisted])
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


@router.post("/tours/{tour_id}/events", summary="Track tour event")
async def track_tour_event(
    tour_id: str,
    request: Request,
    payload: TourEventPayload | None = Body(default=None),
    event_type: str | None = None,
    scene_id: str | None = None,
    hotspot_id: str | None = None,
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
    # Rate-limit per IP to prevent analytics table flooding
    client_ip = get_client_ip(request)
    if _is_event_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Event rate limit exceeded. Try again later.",
        )

    # Validate event type
    if payload:
        event_type = payload.event_type
        scene_id = payload.scene_id or scene_id
        hotspot_id = payload.hotspot_id or hotspot_id

    event_data = payload.event_data.copy() if payload and payload.event_data else {}
    if "referrer" not in event_data:
        event_data["referrer"] = request.headers.get("referer")

    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing event_type",
        )

    event_type = normalize_event_type(event_type, event_data)

    allowed_events = {
        "view",
        "scene_view",
        "hotspot_click",
        "share",
        "fullscreen_enter",
        "fullscreen_exit",
        "vr_enter",
        "vr_exit",
        "heatmap",
        "session_start",
        "session_end",
        "session_duration",
    }
    if event_type not in allowed_events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event type. Must be one of: {', '.join(sorted(allowed_events))}",
        )

    # Verify tour exists and is public (public or unlisted visibility)
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.visibility.in_([TourVisibility.public, TourVisibility.unlisted])
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
        session_id = (
            payload.session_id
            if payload and payload.session_id
            else request.cookies.get("session_id") or request.headers.get("x-session-id")
        )

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
            event_data=event_data,
        )

        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to track event for tour %s: %s", tour_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to track event",
        ) from e


@router.post("/tours/{tour_id}/like", summary="Like tour")
async def like_tour(
    tour_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Increment the like count for a public tour.

    Rate-limited per IP to prevent count manipulation.
    """
    client_ip = get_client_ip(request)
    if _is_like_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Like rate limit exceeded. Try again later.",
        )
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.visibility.in_([TourVisibility.public, TourVisibility.unlisted])
        )
    )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    new_like_count = (
        await db.execute(
            update(Tour)
            .where(Tour.id == tour_id)
            .values(like_count=func.coalesce(Tour.like_count, 0) + 1)
            .returning(Tour.like_count)
        )
    ).scalar_one()
    await db.commit()

    try:
        user_agent = request.headers.get("user-agent", "")
        client_ip = get_client_ip(request)
        device_type = get_device_type(user_agent)
        session_id = request.cookies.get("session_id") or request.headers.get("x-session-id")
        await tour_service.record_analytics_event(
            db=db,
            tour_id=tour_id,
            event_type="like",
            user_agent=user_agent,
            ip_address=client_ip,
            device_type=device_type,
            session_id=session_id,
            increment_counts=False,
        )
    except Exception as e:
        logger.warning("Failed to track like event for tour %s: %s", tour_id, e)

    return {"like_count": new_like_count}


@router.delete("/tours/{tour_id}/like", summary="Unlike tour")
async def unlike_tour(
    tour_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Decrement the like count for a public tour.

    Rate-limited per IP to prevent count manipulation.
    """
    client_ip = get_client_ip(request)
    if _is_like_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Like rate limit exceeded. Try again later.",
        )
    query = select(Tour).where(
        and_(
            Tour.id == tour_id,
            Tour.deleted_at.is_(None),
            Tour.status == TourStatus.published,
            Tour.visibility.in_([TourVisibility.public, TourVisibility.unlisted])
        )
    )

    result = await db.execute(query)
    tour = result.scalar_one_or_none()

    if not tour:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tour not found"
        )

    new_like_count = (
        await db.execute(
            update(Tour)
            .where(Tour.id == tour_id)
            .values(like_count=func.greatest(func.coalesce(Tour.like_count, 0) - 1, 0))
            .returning(Tour.like_count)
        )
    ).scalar_one()
    await db.commit()

    try:
        user_agent = request.headers.get("user-agent", "")
        client_ip = get_client_ip(request)
        device_type = get_device_type(user_agent)
        session_id = request.cookies.get("session_id") or request.headers.get("x-session-id")
        await tour_service.record_analytics_event(
            db=db,
            tour_id=tour_id,
            event_type="unlike",
            user_agent=user_agent,
            ip_address=client_ip,
            device_type=device_type,
            session_id=session_id,
            increment_counts=False,
        )
    except Exception as e:
        logger.warning("Failed to track unlike event for tour %s: %s", tour_id, e)

    return {"like_count": new_like_count}
