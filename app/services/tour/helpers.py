"""
Shared helpers for the tour service package.

Contains ownership checks, HTML sanitization, URL validation,
content normalization, and other utilities used across sub-modules.
"""

from urllib.parse import parse_qs, urlparse

import bleach  # type: ignore[import-untyped]

from app.core.exceptions import BadRequestException, ForbiddenException
from app.models.enums import HotspotType
from app.models.tours import Scene, Tour

# ---------------------------------------------------------------------------
# Bleach sanitization constants
# ---------------------------------------------------------------------------

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
_HOTSPOT_HTML_ALLOWED_ATTRIBUTES: dict = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
}
_HOTSPOT_HTML_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]


# ---------------------------------------------------------------------------
# Ownership checks
# ---------------------------------------------------------------------------


def _ensure_tour_ownership(tour: Tour, user_id: int, action: str = "access") -> None:
    """Raise 403 if user doesn't own the tour."""
    if tour.user_id != user_id:
        raise ForbiddenException(detail=f"You don't have permission to {action} this tour")


def _ensure_scene_ownership(scene: Scene, user_id: int, action: str = "access") -> None:
    """Raise 403 if user doesn't own the scene's tour."""
    if scene.tour.user_id != user_id:
        raise ForbiddenException(detail=f"You don't have permission to {action} this scene")


# ---------------------------------------------------------------------------
# URL / HTML helpers
# ---------------------------------------------------------------------------


def _is_safe_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sanitize_hotspot_html(value: str) -> str:
    return str(bleach.clean(
        value,
        tags=_HOTSPOT_HTML_ALLOWED_TAGS,
        attributes=_HOTSPOT_HTML_ALLOWED_ATTRIBUTES,
        protocols=_HOTSPOT_HTML_ALLOWED_PROTOCOLS,
        strip=True,
    ))


# ---------------------------------------------------------------------------
# Video ID extraction
# ---------------------------------------------------------------------------


def _extract_youtube_id(url: str) -> str | None:
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


def _extract_vimeo_id(url: str) -> str | None:
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


# ---------------------------------------------------------------------------
# Analytics helper
# ---------------------------------------------------------------------------


def _extract_session_duration(event, session_starts: dict) -> float | None:
    """Extract session duration from an analytics event."""
    payload = event.event_data or {}
    duration = payload.get("duration_seconds")
    if duration is None and payload.get("duration_ms") is not None:
        duration = float(payload.get("duration_ms") or 0) / 1000
    if duration is None and payload.get("duration") is not None:
        duration = payload.get("duration")
    if duration is None and event.session_id and event.session_id in session_starts:
        duration = (event.created_at - session_starts[event.session_id]).total_seconds()
    return float(duration) if duration is not None else None


# ---------------------------------------------------------------------------
# Hotspot content normalization
# ---------------------------------------------------------------------------


def _normalize_hotspot_content(
    hotspot_type: HotspotType,
    content: dict | None,
) -> dict | None:
    if content is None:
        content = {}

    if not isinstance(content, dict):
        raise BadRequestException(detail="Hotspot content must be an object")

    normalized: dict = {"kind": hotspot_type.value}

    if hotspot_type == HotspotType.link:
        raw_url = content.get("url") or content.get("link_url")
        if not raw_url or not isinstance(raw_url, str):
            raise BadRequestException(detail="Link hotspots require content.url")
        if not _is_safe_http_url(raw_url):
            raise BadRequestException(detail="Link hotspots require a valid http(s) URL")
        normalized["url"] = raw_url
        target = content.get("target")
        if target not in {"_blank", "_self", None}:
            raise BadRequestException(detail="Link hotspot content.target must be _blank or _self")
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
            raise BadRequestException(detail="Audio hotspots require content.audio_url")
        if not _is_safe_http_url(audio_url):
            raise BadRequestException(detail="Audio hotspots require a valid http(s) URL")
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
                raise BadRequestException(detail="Video hotspots require a valid http(s) URL")
            normalized["video_url"] = video_url.strip()
        else:
            raise BadRequestException(
                detail="Video hotspots require content.video_url or content.youtube_id or content.vimeo_id"
            )

        for key in ("autoplay", "muted", "loop"):
            if key in content:
                normalized[key] = bool(content.get(key))

        poster_url = content.get("poster_url") or content.get("poster")
        if isinstance(poster_url, str) and poster_url.strip():
            if not _is_safe_http_url(poster_url):
                raise BadRequestException(detail="Video hotspot poster_url must be a valid http(s) URL")
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
                raise BadRequestException(detail="Info hotspot image_url must be a valid http(s) URL")
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


# ---------------------------------------------------------------------------
# Background task registry for scene processing
# ---------------------------------------------------------------------------

_scene_processing_tasks: dict = {}
