"""
Public 360 Virtual Tour API Endpoints.

Unauthenticated endpoints for viewing published tours, tracking viewer events,
and liking tours. Every write from a viewer is rate-limited per IP. Views, events
and likes are counted once per viewer, keyed on the server-side client IP (see the
dedupe windows in services.tour). The rate limits are kept in memory, per worker
process, so the effective limit is the per-worker limit times the worker count.
"""

from __future__ import annotations

import threading
import time
import uuid as _uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.middleware.rate_limit import get_client_ip
from app.models.enums import TourEventType
from app.models.tours import Tour, TourLike
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.tour import PublicScene, PublicTourWithScenes, TourEventPayload, TourLikeCount
from app.services import tour as tour_service

router = APIRouter()
logger = get_logger(__name__)


# ── Per-IP sliding-window rate limiter ─────────────────────────────────────────
# One helper serves the like and event endpoints. Each store is a per-worker dict.
_REAP_INTERVAL_S = 300  # reap stale keys every 5 minutes
_reaper_lock = threading.Lock()


def _is_ip_rate_limited(
    client_ip: str,
    *,
    store: dict[str, Any],
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
    store[client_ip] = [t for t in timestamps if t > window_start]
    if len(store[client_ip]) >= limit:
        return True
    store[client_ip].append(now)

    last_reap = store.get(last_reap_attr, 0.0)
    if now - last_reap > _REAP_INTERVAL_S:
        with _reaper_lock:
            if now - store.get(last_reap_attr, 0.0) <= _REAP_INTERVAL_S:
                return False
            store[last_reap_attr] = now
            stale = [k for k, v in store.items() if k == last_reap_attr or not v]
            for k in stale:
                if k != last_reap_attr:
                    del store[k]
    return False


_like_store: dict[str, Any] = defaultdict(list)
_LIKE_RATE_LIMIT = 10  # max requests
_LIKE_RATE_WINDOW_S = 60  # per window

_event_store: dict[str, Any] = defaultdict(list)
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
    return "desktop"


def _viewer_session(request: Request, session_id: str | None) -> str | None:
    """The viewer's session id: from the body, the cookie, or the header."""
    return session_id or request.cookies.get("session_id") or request.headers.get("x-session-id")


def _viewer_key(client_ip: str) -> str:
    """Key that counts one viewer once for likes. The client IP, never a client session id."""
    return f"ip:{client_ip}"


async def _get_public_tour(db: AsyncSession, tour_id: str) -> Tour:
    """A published, non-private tour. Anything else is 404."""
    try:
        _uuid.UUID(tour_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tour not found"
        ) from None
    tour = await tour_service.get_tour(db, tour_id, None, include_scenes=False)
    return tour


@router.get("/tours/{tour_id}", response_model=PublicTourWithScenes, summary="Get public tour")
async def get_public_tour(
    tour_id: str,
    request: Request,
    track: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a publicly accessible tour by ID.

    The tour must be published and not private. Returns the tour with its scenes,
    hotspots and floor plans. With track=true (the default) a view is counted once
    per viewer per dedupe window.
    """
    tour = await tour_service.get_tour(db, tour_id, None, include_scenes=True)

    if track:
        try:
            user_agent = request.headers.get("user-agent", "")
            client_ip = get_client_ip(request)
            session_id = _viewer_session(request, None)
            if not await tour_service.is_repeat_viewer_event(
                db,
                tour_id=tour_id,
                event_type=TourEventType.view.value,
                scene_id=None,
                hotspot_id=None,
                ip_address=client_ip,
                window_s=tour_service.VIEW_DEDUPE_WINDOW_S,
            ):
                await tour_service.record_analytics_event(
                    db=db,
                    tour_id=tour_id,
                    event_type=TourEventType.view.value,
                    user_agent=user_agent,
                    ip_address=client_ip,
                    device_type=get_device_type(user_agent),
                    session_id=session_id,
                    event_data={"referrer": request.headers.get("referer")},
                )
        except Exception as e:
            # Don't fail the request if analytics tracking fails
            logger.warning("Failed to track analytics for tour %s: %s", tour_id, e)
            await db.rollback()

    return tour_service.public_tour_view(tour)


@router.get(
    "/tours/{tour_id}/scenes",
    response_model=CursorPage[PublicScene],
    summary="Get public tour scenes",
)
async def get_public_tour_scenes(
    tour_id: str,
    page: CursorParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the scenes of a publicly accessible tour, in order_index order, with their hotspots.
    """
    items, next_payload, total = await tour_service.get_scenes_page(
        db,
        tour_id,
        None,
        page.decoded(),
        page.limit,
        include_total=page.include_total,
    )
    public_items = [
        tour_service.active_hotspots_only(PublicScene.model_validate(item)) for item in items
    ]
    return build_cursor_page(public_items, limit=page.limit, next_payload=next_payload, total=total)


@router.post(
    "/tours/{tour_id}/events",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Track tour event",
)
async def track_tour_event(
    tour_id: str,
    request: Request,
    payload: TourEventPayload = Body(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Track one viewer event for a public tour. Returns 204.

    A repeat of the same event by the same viewer inside the dedupe window is
    accepted and not counted again. scene_view events must carry yaw and pitch
    in event_data. Those values feed the heatmap.
    """
    client_ip = get_client_ip(request)
    if _is_event_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Event rate limit exceeded. Try again later.",
        )

    tour = await _get_public_tour(db, tour_id)

    event_data = dict(payload.event_data or {})
    if "referrer" not in event_data:
        event_data["referrer"] = request.headers.get("referer")

    user_agent = request.headers.get("user-agent", "")
    session_id = _viewer_session(request, payload.session_id)
    event_type = payload.event_type.value

    try:
        if await tour_service.is_repeat_viewer_event(
            db,
            tour_id=tour.id,
            event_type=event_type,
            scene_id=payload.scene_id,
            hotspot_id=payload.hotspot_id,
            ip_address=client_ip,
            window_s=tour_service.EVENT_DEDUPE_WINDOW_S,
        ):
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        await tour_service.record_analytics_event(
            db=db,
            tour_id=tour.id,
            event_type=event_type,
            scene_id=payload.scene_id,
            hotspot_id=payload.hotspot_id,
            user_agent=user_agent,
            ip_address=client_ip,
            device_type=get_device_type(user_agent),
            session_id=session_id,
            event_data=event_data,
        )
    except Exception as e:
        logger.error("Failed to track event for tour %s: %s", tour_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to track event",
        ) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tours/{tour_id}/like", response_model=TourLikeCount, summary="Like tour")
async def like_tour(
    tour_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Like a public tour. A viewer's second like does not change the count.
    """
    client_ip = get_client_ip(request)
    if _is_like_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Like rate limit exceeded. Try again later.",
        )

    tour = await _get_public_tour(db, tour_id)
    # Read the key before any commit: the commit expires the row, and a lazy load would fail here.
    tour_pk = tour.id
    session_id = _viewer_session(request, None)
    viewer = _viewer_key(client_ip)

    inserted = (
        await db.execute(
            pg_insert(TourLike)
            .values(tour_id=tour_pk, viewer_key=viewer, created_at=utc_now())
            .on_conflict_do_nothing(index_elements=[TourLike.tour_id, TourLike.viewer_key])
            .returning(TourLike.tour_id)
        )
    ).scalar_one_or_none()

    if inserted is not None:
        # Commits the like row and the tour counter together.
        await tour_service.record_analytics_event(
            db=db,
            tour_id=tour_pk,
            event_type=TourEventType.like.value,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=client_ip,
            session_id=session_id,
            increment_counts=True,
        )
    else:
        await db.rollback()

    count = (await db.execute(select(Tour.like_count).where(Tour.id == tour_pk))).scalar_one()
    return TourLikeCount(like_count=int(count or 0))


@router.delete("/tours/{tour_id}/like", response_model=TourLikeCount, summary="Unlike tour")
async def unlike_tour(
    tour_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove this viewer's like from a public tour. Without a like, the count does not change.
    """
    client_ip = get_client_ip(request)
    if _is_like_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Like rate limit exceeded. Try again later.",
        )

    tour = await _get_public_tour(db, tour_id)
    # Read the key before any commit: the commit expires the row, and a lazy load would fail here.
    tour_pk = tour.id
    session_id = _viewer_session(request, None)
    viewer = _viewer_key(client_ip)

    removed = (
        await db.execute(
            delete(TourLike)
            .where(TourLike.tour_id == tour_pk, TourLike.viewer_key == viewer)
            .returning(TourLike.tour_id)
        )
    ).scalar_one_or_none()

    if removed is not None:
        await tour_service.record_analytics_event(
            db=db,
            tour_id=tour_pk,
            event_type=TourEventType.unlike.value,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=client_ip,
            session_id=session_id,
            increment_counts=True,
        )
    else:
        await db.rollback()

    count = (await db.execute(select(Tour.like_count).where(Tour.id == tour_pk))).scalar_one()
    return TourLikeCount(like_count=int(count or 0))
