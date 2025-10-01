from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from app.core.database import AsyncSessionLocal
from app.core.auth import verify_supabase_token
from app.core.logging import get_logger
from app.schemas.property import (
    UnifiedPropertyFilter,
    PropertySwipe,
)
from app.schemas.visit import VisitCreate
from app.services import property as property_svc
from app.services import swipe as swipe_svc
from app.services import visit as visit_svc
from app.services.user import get_or_create_user_from_supabase


logger = get_logger(__name__)
mcp = FastMCP("ghar360")

# Note: This module maintains a simple in-process session token for convenience.
# MCP clients typically spawn a dedicated process per user, so this is acceptable.
_SESSION_JWT: Optional[str] = None


async def _get_db():
    async with AsyncSessionLocal() as db:
        yield db


async def _get_user_from_jwt(db, jwt: Optional[str]) -> Optional[Any]:
    token = jwt or _SESSION_JWT
    if not token:
        return None
    supa = await verify_supabase_token(token)
    if not supa:
        return None
    user = await get_or_create_user_from_supabase(db, supa)
    return user


@mcp.tool("auth.set_jwt")
async def auth_set_jwt(jwt: str) -> Dict[str, Any]:
    """Store a bearer JWT for subsequent tool calls in this MCP session."""
    global _SESSION_JWT
    # Basic shape check
    if not isinstance(jwt, str) or len(jwt.split(".")) < 3:
        return {"ok": False, "error": "invalid_jwt"}
    _SESSION_JWT = jwt
    return {"ok": True}


@mcp.tool("auth.whoami")
async def auth_whoami(jwt: Optional[str] = None) -> Dict[str, Any]:
    """Return the current authenticated user (id, email, phone)."""
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"authenticated": False}
        return {
            "authenticated": True,
            "user": {
                "id": user.id,
                "email": getattr(user, "email", None),
                "phone": getattr(user, "phone", None),
                "full_name": getattr(user, "full_name", None),
            },
        }


@mcp.tool("properties.search")
async def properties_search(
    jwt: Optional[str] = None,
    search_query: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: int = 5,
    page: int = 1,
    limit: int = 20,
    include_unavailable: bool = False,
) -> Dict[str, Any]:
    """Search properties with optional text and location filters."""
    limit = min(max(1, limit), 50)
    if latitude is not None and not (-90 <= latitude <= 90):
        raise ValueError("invalid latitude")
    if longitude is not None and not (-180 <= longitude <= 180):
        raise ValueError("invalid longitude")
    if radius_km < 0 or radius_km > 50:
        raise ValueError("radius_km must be between 0 and 50")

    filters = UnifiedPropertyFilter(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        search_query=search_query,
        include_unavailable=include_unavailable,
    )

    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        uid = user.id if user else None
        data = await property_svc.get_unified_properties_optimized(
            db=db, filters=filters, user_id=uid, page=page, limit=limit
        )
        # Serialize minimal fields for MCP clients
        items = []
        for p in data["items"]:
            items.append(
                {
                    "id": p.id,
                    "title": p.title,
                    "city": p.city,
                    "locality": p.locality,
                    "price": p.base_price,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "main_image_url": p.main_image_url,
                }
            )
        return {
            "total": data["total"],
            "page": page,
            "limit": limit,
            "total_pages": data.get("total_pages", 1),
            "items": items,
        }


@mcp.tool("properties.get")
async def properties_get(property_id: int, jwt: Optional[str] = None) -> Dict[str, Any]:
    """Get a single property with details."""
    async for db in _get_db():
        # user may be used later for personalization
        _ = await _get_user_from_jwt(db, jwt)
        prop = await property_svc.get_property(db, property_id)
        if not prop:
            return {"found": False}
        return {
            "found": True,
            "property": {
                "id": prop.id,
                "title": prop.title,
                "description": prop.description,
                "city": prop.city,
                "locality": prop.locality,
                "price": prop.base_price,
                "latitude": prop.latitude,
                "longitude": prop.longitude,
                "images": [i.image_url for i in (prop.images or [])],
                "amenities": [
                    getattr(a, "amenity", a).title if hasattr(a, "amenity") else getattr(a, "title", None)
                    for a in (prop.amenities or [])
                ],
            },
        }


@mcp.tool("discovery.feed")
async def discovery_feed(jwt: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Get a recommended property feed for the current user."""
    limit = min(max(1, limit), 50)
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        uid = user.id if user else None
        props = await property_svc.get_property_recommendations(db, user_id=uid, limit=limit)
        items = [
            {
                "id": p.id,
                "title": p.title,
                "city": p.city,
                "locality": p.locality,
                "price": p.base_price,
                "main_image_url": p.main_image_url,
            }
            for p in props
        ]
        return {"items": items}


@mcp.tool("swipes.like")
async def swipes_like(property_id: int, jwt: Optional[str] = None) -> Dict[str, Any]:
    """Like a property."""
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"ok": False, "error": "unauthorized"}
        ok = await swipe_svc.record_swipe(db, user.id, PropertySwipe(property_id=property_id, is_liked=True))
        await db.commit()
        return {"ok": bool(ok)}


@mcp.tool("swipes.dislike")
async def swipes_dislike(property_id: int, jwt: Optional[str] = None) -> Dict[str, Any]:
    """Dislike a property."""
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"ok": False, "error": "unauthorized"}
        ok = await swipe_svc.record_swipe(db, user.id, PropertySwipe(property_id=property_id, is_liked=False))
        await db.commit()
        return {"ok": bool(ok)}


@mcp.tool("swipes.undo")
async def swipes_undo(jwt: Optional[str] = None) -> Dict[str, Any]:
    """Undo last swipe for the current user."""
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"ok": False, "error": "unauthorized"}
        last = await swipe_svc.undo_last_swipe(db, user.id)
        await db.commit()
        return {"ok": last is not None}


@mcp.tool("shortlist.list")
async def shortlist_list(
    jwt: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """List liked properties for the current user."""
    limit = min(max(1, limit), 50)
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"ok": False, "error": "unauthorized"}
        filters = UnifiedPropertyFilter()
        data = await swipe_svc.get_swipe_history(db, user.id, filters, page, limit, is_liked=True)
        items: List[Dict[str, Any]] = []
        for swipe in data["items"]:
            p = swipe.property
            if not p:
                continue
            items.append(
                {
                    "id": p.id,
                    "title": p.title,
                    "city": p.city,
                    "locality": p.locality,
                    "price": p.base_price,
                    "main_image_url": p.main_image_url,
                }
            )
        return {
            "ok": True,
            "total": data["total"],
            "page": data["page"],
            "limit": data["limit"],
            "total_pages": data["total_pages"],
            "items": items,
        }


@mcp.tool("visits.schedule")
async def visits_schedule(
    property_id: int,
    scheduled_date_iso: str,
    special_requirements: Optional[str] = None,
    jwt: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule a property visit for the current user."""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(scheduled_date_iso)
    except Exception:
        raise ValueError("scheduled_date_iso must be ISO-8601")

    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"ok": False, "error": "unauthorized"}
        visit = await visit_svc.create_visit(
            db,
            user_id=user.id,
            visit=VisitCreate(property_id=property_id, scheduled_date=dt, special_requirements=special_requirements),
        )
        await db.commit()
        return {"ok": True, "visit_id": visit.id}


@mcp.tool("visits.list")
async def visits_list(jwt: Optional[str] = None) -> Dict[str, Any]:
    """List visits for the current user."""
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"ok": False, "error": "unauthorized"}
        data = await visit_svc.get_user_visits(db, user.id)
        out = []
        for v in data["visits"]:
            out.append(
                {
                    "id": v.id,
                    "property_id": v.property_id,
                    "scheduled_date": getattr(v, "scheduled_date", None).isoformat() if getattr(v, "scheduled_date", None) else None,
                    "status": v.status,
                    "property": {
                        "id": v.property.id if v.property else None,
                        "title": v.property.title if v.property else None,
                        "main_image_url": v.property.main_image_url if v.property else None,
                    }
                    if v.property
                    else None,
                }
            )
        return {"ok": True, **{k: v for k, v in data.items() if k != "visits"}, "visits": out}


@mcp.tool("visits.cancel")
async def visits_cancel(visit_id: int, reason: str, jwt: Optional[str] = None) -> Dict[str, Any]:
    """Cancel a visit for the current user."""
    async for db in _get_db():
        user = await _get_user_from_jwt(db, jwt)
        if not user:
            return {"ok": False, "error": "unauthorized"}
        # Basic ownership check: ensure the visit belongs to the user
        v = await visit_svc.get_visit(db, visit_id)
        if not v or v.user_id != user.id:
            return {"ok": False, "error": "not_found_or_forbidden"}
        updated = await visit_svc.cancel_visit(db, visit_id, reason)
        await db.commit()
        return {"ok": bool(updated)}


def run():
    mcp.run()


if __name__ == "__main__":
    run()
