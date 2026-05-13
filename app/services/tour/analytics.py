"""
Analytics service functions.

Tour analytics, dashboard stats, heatmap aggregation,
event recording, and realtime dashboard metrics.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.enums import TourStatus
from app.models.tours import Scene, Tour, TourAnalyticsEvent
from app.schemas.tour import (
    DailyView,
    DashboardStats,
    DeviceBreakdown,
    HeatmapPoint,
    TourAnalytics,
)
from app.services.tour.helpers import (
    _ensure_tour_ownership,
    _extract_session_duration,
)
from app.services.tour.tours import get_tour

logger = get_logger(__name__)


async def get_tour_analytics(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
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
    heatmap_points: list[HeatmapPoint] = []
    share_breakdown: dict = {}
    session_starts: dict = {}
    session_durations: list[float] = []

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
                HeatmapPoint(
                    scene_id=event.scene_id,
                    yaw=float(event_payload.get("yaw", 0.0)) if event_payload.get("yaw") is not None else None,
                    pitch=float(event_payload.get("pitch", 0.0)) if event_payload.get("pitch") is not None else None,
                    x=float(event_payload.get("x", 0.0)) if event_payload.get("x") is not None else None,
                    y=float(event_payload.get("y", 0.0)) if event_payload.get("y") is not None else None,
                    intensity=float(event_payload.get("intensity", 1.0)),
                )
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
    scene_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
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
    # Query heatmap events
    conditions = [TourAnalyticsEvent.tour_id == tour_id, TourAnalyticsEvent.event_type == "heatmap"]

    if scene_id:
        conditions.append(TourAnalyticsEvent.scene_id == scene_id)

    if start_date:
        conditions.append(
            TourAnalyticsEvent.created_at >= datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        )

    if end_date:
        conditions.append(
            TourAnalyticsEvent.created_at <= datetime.combine(end_date, time.max, tzinfo=timezone.utc)
        )

    query = select(TourAnalyticsEvent).where(and_(*conditions))
    result = await db.execute(query)
    events = result.scalars().all()

    # Group heatmap points by scene and aggregate by grid cells
    scene_heatmaps: dict[str, dict[str, dict[str, Any]]] = {}

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
    output: dict[str, list[dict[str, Any]]] = {}

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
    scene_id: str | None = None,
    hotspot_id: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
    device_type: str | None = None,
    session_id: str | None = None,
    country: str | None = None,
    event_data: dict | None = None,
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
    now = utc_now()
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
    session_durations: list[float] = []
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
