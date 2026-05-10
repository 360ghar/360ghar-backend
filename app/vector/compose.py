from __future__ import annotations

import re
from html import unescape
from typing import Any


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    # Basic HTML tag stripper and unescape
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def build_embedding_text(prop: dict[str, Any], amenities: list[str], tags: list[str]) -> str:
    """Compose a canonical text for property embeddings.

    prop: dict of fields from properties
    amenities: list of amenity titles
    tags: list of tags
    """
    parts: list[str] = []
    # Headline
    parts.append(prop.get("title") or "")
    # Type & purpose
    ppt = prop.get("property_type")
    purp = prop.get("purpose")
    status = prop.get("status")
    if ppt or purp:
        parts.append(f"{ppt or ''} for {purp or ''} {status or ''}")
    # Location
    loc = " ".join(
        [
            prop.get("locality") or "",
            prop.get("city") or "",
            prop.get("state") or "",
            (prop.get("country") or "India"),
            str(prop.get("pincode") or ""),
        ]
    )
    parts.append(loc)
    # Key numbers
    beds = prop.get("bedrooms")
    baths = prop.get("bathrooms")
    area = prop.get("area_sqft")
    parking = prop.get("parking_spaces")
    numbers = []
    if beds:
        numbers.append(f"{beds} bedrooms")
    if baths:
        numbers.append(f"{baths} bathrooms")
    if area:
        numbers.append(f"{area} sqft")
    if parking:
        numbers.append(f"{parking} parking")
    if numbers:
        parts.append(", ".join(numbers))
    # Pricing (base price and rent)
    price = prop.get("base_price")
    if price:
        parts.append(f"price {price}")
    monthly = prop.get("monthly_rent")
    if monthly:
        parts.append(f"monthly rent {monthly}")
    # Description and keywords
    desc = _strip_html(prop.get("description"))
    if desc:
        parts.append(desc)
    search_kw = prop.get("search_keywords")
    if search_kw:
        parts.append(str(search_kw))
    # Amenities and tags
    if amenities:
        parts.append("amenities: " + ", ".join(sorted(set(amenities))))
    if tags:
        parts.append("tags: " + ", ".join(sorted(set(tags))))
    # Landmark
    if prop.get("landmark"):
        parts.append(f"near {prop['landmark']}")
    return ". ".join([p for p in parts if p]).strip()


def build_metadata(prop: dict[str, Any], amenities: list[str], tags: list[str]) -> dict[str, Any]:
    fields = [
        "id",
        "property_type",
        "purpose",
        "status",
        "is_available",
        "base_price",
        "monthly_rent",
        "area_sqft",
        "bedrooms",
        "bathrooms",
        "parking_spaces",
        "city",
        "locality",
        "state",
        "country",
        "pincode",
        "latitude",
        "longitude",
        "created_at",
        "updated_at",
    ]
    def _coerce(v: Any):
        try:
            import datetime as _dt
            if isinstance(v, (_dt.datetime, _dt.date)):
                return v.isoformat()
        except (TypeError, ValueError):
            pass
        return v

    md: dict[str, Any] = {k: _coerce(prop.get(k)) for k in fields}
    md["amenities"] = amenities
    md["tags"] = tags
    md["title"] = prop.get("title")
    md["main_image_url"] = prop.get("main_image_url")
    return md
