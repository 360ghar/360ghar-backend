"""Search helper operations for MCP tools.

Provides natural language query parsing, city alias resolution,
and empty-result UX helpers for property search.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger
from app.utils.geo import CITY_ALIASES, normalize_city

# Re-export for backwards compatibility with existing callers.
__all__ = [
    "CITY_ALIASES",
    "build_empty_result_message",
    "normalize_city",
    "parse_natural_query",
]

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Property type keyword mapping
# ---------------------------------------------------------------------------
_PROPERTY_TYPE_KEYWORDS: dict[str, str] = {
    "flat": "apartment",
    "flats": "apartment",
    "apartment": "apartment",
    "apartments": "apartment",
    "flatmate": "flatmate",
    "flatmates": "flatmate",
    "pg": "pg",
    "paying guest": "pg",
    "house": "house",
    "houses": "house",
    "villa": "villa",
    "villas": "villa",
    "plot": "plot",
    "plots": "plot",
    "land": "plot",
    "room": "room",
    "rooms": "room",
    "studio": "studio",
    "penthouse": "penthouse",
    "builder floor": "builder_floor",
    "builder-floor": "builder_floor",
    "condo": "condo",
    "office": "office",
    "shop": "shop",
    "warehouse": "warehouse",
    "loft": "loft",
}

# ---------------------------------------------------------------------------
# Purpose keyword mapping
# ---------------------------------------------------------------------------
_PURPOSE_KEYWORDS: dict[str, str] = {
    "buy": "buy",
    "purchase": "buy",
    "invest": "buy",
    "rent": "rent",
    "lease": "rent",
    "rental": "rent",
    "stay": "short_stay",
    "short stay": "short_stay",
    "short-stay": "short_stay",
    "hotel": "short_stay",
    "vacation": "short_stay",
    "booking": "short_stay",
}

# ---------------------------------------------------------------------------
# BHK / bedroom patterns
# ---------------------------------------------------------------------------
_BHK_PATTERN = re.compile(
    r"(\d+)\s*(?:bhk|bed(?:room)?s?|br)\b",
    re.IGNORECASE,
)

# Price patterns: "under 2 crore", "below 50 lakh", "max 30000", "< 2cr"
_PRICE_UNDER_PATTERN = re.compile(
    r"(?:under|below|max|upto|up\s*to|less\s*than|<)\s*"
    r"([\d,.]+)\s*"
    r"(cr(?:ore)?s?|l(?:akh)?s?|lacs?|k\b)?",
    re.IGNORECASE,
)

# Price range: "10k to 20k", "50 lakh - 1 crore"
_PRICE_RANGE_PATTERN = re.compile(
    r"([\d,.]+)\s*(cr(?:ore)?s?|l(?:akh)?s?|lacs?|k\b)?\s*(?:to|-|–)\s*([\d,.]+)\s*(cr(?:ore)?s?|l(?:akh)?s?|lacs?|k\b)?",
    re.IGNORECASE,
)


def _parse_price_value(value_str: str, unit: str | None) -> float | None:
    """Convert a price string + optional unit to a numeric value in INR."""
    try:
        value = float(value_str.replace(",", ""))
    except (ValueError, TypeError):
        return None

    if unit is None:
        return value

    unit_lower = unit.lower()
    if unit_lower.startswith("cr"):
        return value * 10_000_000
    if unit_lower.startswith("l") or unit_lower == "lac":
        return value * 100_000
    if unit_lower == "k":
        return value * 1_000
    return value


def parse_natural_query(query: str) -> dict[str, Any]:
    """Extract structured filters from a natural language property query.

    Parses common Indian real estate query patterns like:
    - "3BHK flat in Gurugram under 2 crore"
    - "2 bedroom apartment for rent in Bangalore below 50000"
    - "buy villa in Goa 3-5 crore"

    Returns:
        Dict with extracted filters: bedrooms, price_min, price_max,
        property_type, purpose, city, cleaned_query (remaining text for FTS).
    """
    if not query:
        return {"cleaned_query": ""}

    text = query.strip()
    extracted: dict[str, Any] = {}

    # 1. Extract bedrooms (BHK)
    bhk_match = _BHK_PATTERN.search(text)
    if bhk_match:
        extracted["bedrooms"] = int(bhk_match.group(1))
        text = text[: bhk_match.start()] + text[bhk_match.end() :]

    # 2. Extract price range (under/below pattern first, then range)
    price_under = _PRICE_UNDER_PATTERN.search(text)
    price_range = _PRICE_RANGE_PATTERN.search(text)

    if price_under:
        max_price = _parse_price_value(price_under.group(1), price_under.group(2))
        if max_price:
            extracted["price_max"] = max_price
            text = text[: price_under.start()] + text[price_under.end() :]
    elif price_range:
        min_price = _parse_price_value(price_range.group(1), price_range.group(2))
        max_price = _parse_price_value(price_range.group(3), price_range.group(4))
        if min_price:
            extracted["price_min"] = min_price
        if max_price:
            extracted["price_max"] = max_price
        text = text[: price_range.start()] + text[price_range.end() :]

    # 3. Extract property type keywords (sorted by length descending to match "flatmate" before "flat")
    for keyword, prop_type in sorted(_PROPERTY_TYPE_KEYWORDS.items(), key=lambda x: -len(x[0])):
        # Match whole words only
        pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            extracted.setdefault("property_types", []).append(prop_type)
            text = text[: match.start()] + text[match.end() :]
            break  # Take first match to avoid over-extraction

    # 4. Extract purpose keywords
    for keyword, purpose in _PURPOSE_KEYWORDS.items():
        pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            extracted["purpose"] = purpose
            text = text[: match.start()] + text[match.end() :]
            break

    # 5. Extract city names (try known cities from alias map)
    # Sort by length descending to match longer names first (e.g., "New Delhi" before "Delhi")
    sorted_cities = sorted(CITY_ALIASES.keys(), key=len, reverse=True)
    for city_name in sorted_cities:
        pattern = re.compile(r"\b" + re.escape(city_name) + r"\b", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            extracted["city"] = CITY_ALIASES[city_name.lower()]
            text = text[: match.start()] + text[match.end() :]
            break

    # 6. Clean up remaining text for FTS
    # Remove common filler words
    filler_words = {"in", "for", "with", "near", "around", "the", "a", "an", "and", "or", "is", "are"}
    cleaned_tokens = [
        t.strip() for t in re.split(r"\s+", text.strip()) if t.strip() and t.strip().lower() not in filler_words
    ]
    cleaned_query = " ".join(cleaned_tokens).strip()

    extracted["cleaned_query"] = cleaned_query
    return extracted


def build_empty_result_message(
    filters_applied: dict[str, Any],
    city: str | None = None,
) -> str:
    """Build a helpful message when search returns zero results.

    Includes contextual suggestions based on which filters were applied.
    """
    parts = ["No properties found matching your criteria."]

    suggestions = []

    if city:
        suggestions.append(f"try searching without the city filter for '{city}'")

    if filters_applied.get("price_min") or filters_applied.get("price_max"):
        suggestions.append("try widening the price range")

    if filters_applied.get("bedrooms_min") or filters_applied.get("bedrooms_max"):
        suggestions.append("try a different number of bedrooms")

    if filters_applied.get("property_type"):
        suggestions.append("try a different property type")

    if filters_applied.get("query"):
        suggestions.append("try simpler search terms")

    if suggestions:
        parts.append("Suggestions: " + "; ".join(suggestions) + ".")

    parts.append("360Ghar is expanding to new areas. Check back soon for more listings.")

    return " ".join(parts)
