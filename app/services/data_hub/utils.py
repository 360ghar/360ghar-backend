from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def normalize_address(addr: str) -> str:
    """Lowercase, collapse whitespace, standardize 'sector', 'gurgaon'/'gurugram'."""
    addr = addr.lower().strip()
    addr = unicodedata.normalize("NFKD", addr)
    addr = re.sub(r"\s+", " ", addr)
    # Standardize gurgaon/gurugram
    addr = re.sub(r"\bgurgaon\b", "gurugram", addr)
    # Standardize sector notation: sec-57, sec 57 → sector 57
    addr = re.sub(r"\bsec(?:tor)?[\s\-\.]+(\d+)", r"sector \1", addr)
    return addr


def address_hash(addr: str) -> str:
    """SHA-256 of normalized address for dedup."""
    return hashlib.sha256(normalize_address(addr).encode()).hexdigest()


def generate_slug(*parts: str) -> str:
    """Kebab-case URL slug from parts."""
    combined = " ".join(str(p) for p in parts if p is not None)
    slug = combined.lower()
    slug = unicodedata.normalize("NFKD", slug)
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


# Columns excluded from the upsert values dict.
_BANK_AUCTION_SKIP = {"id", "created_at", "updated_at"}

# Unique constraint columns for BankAuction upserts.
BANK_AUCTION_INDEX_ELEMENTS = ["bank_name", "normalized_address_hash", "auction_date"]

# Default set_ fields for BankAuction upsert (5 columns).
BANK_AUCTION_DEFAULT_SET: dict[str, Any] = {
    "reserve_price": "excluded",
    "emd_amount": "excluded",
    "raw_data": "excluded",
    "is_active": True,
    "source_url": "excluded",
}

# Extended set_ fields for BankAuction upsert (8 columns, used by DDA/HSVP).
BANK_AUCTION_EXTENDED_SET: dict[str, Any] = {
    **BANK_AUCTION_DEFAULT_SET,
    "property_type": "excluded",
    "area_sqft": "excluded",
    "locality": "excluded",
}


async def upsert_bank_auction(
    db: AsyncSession,
    rec: dict[str, Any],
    set_fields: dict[str, Any] | None = None,
) -> None:
    """Upsert a single BankAuction record.

    Args:
        db: Database session.
        rec: Record dict with BankAuction column values.
        set_fields: Fields to update on conflict. Values of "excluded" map to
            stmt.excluded.<col>; other values are used as literals.
            Defaults to BANK_AUCTION_DEFAULT_SET.

    Raises:
        Exception: On database errors (caller should handle rollback).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.data_hub import BankAuction

    if set_fields is None:
        set_fields = BANK_AUCTION_DEFAULT_SET

    rec.setdefault("is_active", True)
    rec.setdefault("auction_date", date(1970, 1, 1))

    stmt = pg_insert(BankAuction).values(
        **{k: v for k, v in rec.items() if hasattr(BankAuction, k) and k not in _BANK_AUCTION_SKIP}
    )

    resolved_set: dict[str, Any] = {}
    for key, val in set_fields.items():
        if val == "excluded":
            resolved_set[key] = getattr(stmt.excluded, key)
        else:
            resolved_set[key] = val

    stmt = stmt.on_conflict_do_update(
        index_elements=BANK_AUCTION_INDEX_ELEMENTS,
        set_=resolved_set,
    )
    await db.execute(stmt)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        logger.warning("PDF text extraction failed: %s", e)
        return ""


# Keywords for gazette relevance classification
_GAZETTE_KEYWORDS: dict[str, list[str]] = {
    "land_acquisition": ["land acquisition", "section 4", "section 6", "compensation", "award"],
    "rate_revision": ["circle rate", "collector rate", "revised rate", "dlc rate"],
    "policy": ["master plan", "policy", "regulation", "act", "ordinance", "amendment"],
    "clu_change": ["change of land use", "clu", "zoning", "land use change", "conversion"],
}


def classify_gazette_relevance(text: str) -> tuple[list[str], float]:
    """
    Keyword-match gazette text to categories.
    Returns (tags: list[str], relevance_score: float 0.0-1.0).
    """
    text_lower = text.lower()
    matched_tags = []
    total_hits = 0
    for tag, keywords in _GAZETTE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            matched_tags.append(tag)
            total_hits += hits
    # Score: capped at 1.0, scales with keyword density
    score = min(1.0, total_hits / 5.0)
    return matched_tags, round(score, 2)


# Haryana stamp duty rates
_STAMP_DUTY_RATES = {
    "male": 0.07,  # 7%
    "female": 0.05,  # 5%
    "joint": 0.06,  # 6%
}
_REGISTRATION_FEE_RATE = 0.01  # 1%


def calculate_stamp_duty(value: float, buyer_type: str) -> float:
    """Calculate Haryana stamp duty. buyer_type: 'male'|'female'|'joint'."""
    rate = _STAMP_DUTY_RATES.get(buyer_type.lower(), _STAMP_DUTY_RATES["male"])
    return round(value * rate, 2)


def calculate_registration_fee(value: float) -> float:
    """Registration fee = 1% of property value."""
    return round(value * _REGISTRATION_FEE_RATE, 2)


def calculate_builder_score(total_complaints: int, total_projects: int) -> float:
    """
    0-100 composite builder score.
    Starts at 100, deducted by complaint ratio.
    Zero projects → score of 50 (unknown).
    """
    if total_projects == 0:
        return 50.0
    complaint_ratio = total_complaints / total_projects
    # Each complaint per project deducts 15 points, capped at 0
    score = max(0.0, 100.0 - (complaint_ratio * 15.0))
    return round(score, 1)


# =============================================================================
# Shared auction parsing utilities
# =============================================================================


def _parse_currency(val: str) -> float | None:
    """Extract a numeric price from a string like '₹ 1,25,00,000' or '12500000'."""
    if not val:
        return None
    cleaned = val.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    # Remove any remaining non-numeric chars except dot
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(val: str) -> str | None:
    """Try common Indian date formats. Returns ISO date string or None."""
    if not val:
        return None
    from datetime import datetime

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _infer_property_type(text: str, category_map: dict[str, str]) -> str | None:
    """Guess property_type from description text using provided category map."""
    text_lower = text.lower()
    # Check multi-word phrases first (longer match wins)
    for keyword in sorted(category_map.keys(), key=len, reverse=True):
        if keyword in text_lower:
            return category_map[keyword]
    return None


def _extract_city_from_text(text: str, known_cities: list[str]) -> str | None:
    """Extract city name from text by matching known city names."""
    text_lower = text.lower()
    for city in known_cities:
        if city.lower() in text_lower:
            return city
    return None


def _parse_area_sqft(val: str) -> float | None:
    """Parse area value and convert to sqft based on unit in the string."""
    if not val:
        return None
    val_lower = val.lower()
    # Extract numeric value
    area_match = re.search(r"[\d,]+\.?\d*", val.replace(",", ""))
    if not area_match:
        return None
    try:
        area_val = float(area_match.group().replace(",", ""))
    except ValueError:
        return None

    # Detect unit from the value/string
    if "sqyd" in val_lower or "sq.yd" in val_lower or "yard" in val_lower:
        area_val *= 9  # 1 sqyd = 9 sqft
    elif "sqm" in val_lower or "sq.m" in val_lower or "sq meter" in val_lower:
        area_val *= 10.7639
    elif "sqft" in val_lower or "sq.ft" in val_lower or "sq ft" in val_lower:
        pass  # already in sqft
    elif "acre" in val_lower:
        area_val *= 43560
    elif "hectare" in val_lower:
        area_val *= 107639
    # If no unit detected, assume sqft (common in Indian auctions)
    return area_val


def _parse_notice_list_items(
    soup: BeautifulSoup,
    source_cfg: dict,
    keywords: list[str],
    base_url: str,
    city: str | None = None,
    known_cities: list[str] | None = None,
) -> list[dict]:
    """
    Parse auction notices from list-style HTML (common in DDA, YEIDA, etc.).
    Looks for anchor tags or list items containing auction-related keywords.
    """
    records: list[dict] = []

    # Find all links that might be auction notices
    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True)
        if not text or len(text) < 10:
            continue

        text_lower = text.lower()
        # Check if text contains any auction keywords
        if not any(kw in text_lower for kw in keywords):
            continue

        href = link["href"]
        if isinstance(href, list):
            href = href[0] if href else ""
        full_url = urljoin(base_url, href)

        # Try to extract details from the link text
        record = {
            "source": source_cfg["source"],
            "bank_name": source_cfg.get("bank_name", source_cfg["source"].value.upper()),
            "property_description": text,
            "source_url": full_url,
            "raw_data": {"link_text": text, "link_href": href},
        }

        # Try to extract city from text if not provided
        if city:
            record["city"] = city
        elif known_cities:
            extracted_city = _extract_city_from_text(text, known_cities)
            if extracted_city:
                record["city"] = extracted_city

        # Parse auction_date, reserve_price, emd_amount, area_sqft, locality from text
        # These patterns are common in notice list items
        date_patterns = [
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                parsed = _parse_date(match.group(1))
                if parsed:
                    record["auction_date"] = parsed
                    break

        # Price patterns
        price_match = re.search(r"(?:reserve|base|price|amount)[\s:]*[₹Rs]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
        if price_match:
            record["reserve_price"] = _parse_currency(price_match.group(1))

        emd_match = re.search(r"emd[\s:]*[₹Rs]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
        if emd_match:
            record["emd_amount"] = _parse_currency(emd_match.group(1))

        # Area patterns
        area_match = re.search(r"(?:area|size)[\s:]*([\d,]+\.?\d*\s*(?:sq\.?\s*(?:ft|yd|m|yd|meter|yard|acre|hectare)))", text, re.IGNORECASE)
        if area_match:
            record["area_sqft"] = _parse_area_sqft(area_match.group(1))

        # Locality/sector patterns
        sector_match = re.search(r"(?:sector|scheme|locality|zone)[\s:]*([A-Za-z0-9\s\-]+)", text, re.IGNORECASE)
        if sector_match:
            record["locality"] = sector_match.group(1).strip()

        if record.get("property_description"):
            records.append(record)

    return records


def _parse_generic_auction_table(
    soup: BeautifulSoup,
    source_cfg: dict,
    column_mappers: dict[str, Callable[[str, str], dict | None]] | None = None,
    expected_headers: list[str] | None = None,
) -> list[dict]:
    """
    Generic table parser for auction listings.

    Args:
        soup: BeautifulSoup object
        source_cfg: Source configuration dict
        column_mappers: Optional dict mapping header keywords to parser functions.
                       Each parser receives (header, value) and returns dict of fields to update.
        expected_headers: Optional list of expected header texts for validation.
                        If provided, validates that table headers match before parsing.
    """
    records: list[dict] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        # Validate headers if expected_headers provided
        if expected_headers:
            # Check if at least some expected headers are present
            matched = sum(1 for eh in expected_headers if any(eh.lower() in h for h in headers))
            if matched < min(2, len(expected_headers) // 2):
                # Not enough matching headers, skip this table
                continue

        for row in table.find_all("tr")[1:]:  # skip header row
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue

            record: dict = {
                "source": source_cfg["source"],
                "bank_name": source_cfg.get("bank_name", source_cfg["source"].value.upper()),
                "property_description": cells[0] if cells else "",
                "source_url": source_cfg.get("url", ""),
                "raw_data": {"headers": headers, "cells": cells},
            }

            # Map columns using provided mappers or default logic
            for i, h in enumerate(headers):
                if i >= len(cells):
                    break
                val = cells[i]

                if column_mappers:
                    # Use custom mappers
                    for keyword, mapper in column_mappers.items():
                        if keyword in h:
                            result = mapper(h, val)
                            if result:
                                record.update(result)
                            break
                else:
                    # Default mapping logic
                    h_lower = h.lower()
                    if "reserve" in h_lower or "price" in h_lower or "base" in h_lower or "tender" in h_lower:
                        price = _parse_currency(val)
                        if price is not None:
                            record["reserve_price"] = price
                    elif "emd" in h_lower or "earnest" in h_lower:
                        price = _parse_currency(val)
                        if price is not None:
                            record["emd_amount"] = price
                    elif "date" in h_lower and ("auction" in h_lower or "bid" in h_lower or "closing" in h_lower or "opening" in h_lower or "sale" in h_lower):
                        parsed = _parse_date(val)
                        if parsed:
                            record["auction_date"] = parsed
                    elif "address" in h_lower or "location" in h_lower or "sector" in h_lower or "locality" in h_lower:
                        if "sq" not in h_lower and "sqft" not in h_lower and "sqm" not in h_lower and "sqyd" not in h_lower:
                            record["locality"] = val
                            if not record.get("full_address"):
                                record["full_address"] = val
                    elif "property" in h_lower or "type" in h_lower or "category" in h_lower or "scheme" in h_lower:
                        if val and not record["property_description"]:
                            record["property_description"] = val
                    elif ("area" in h_lower or "size" in h_lower) and ("sq" in h_lower or "yard" in h_lower or "sqm" in h_lower or "sqyd" in h_lower or "ft" in h_lower or "meter" in h_lower):
                        area = _parse_area_sqft(val)
                        if area is not None:
                            record["area_sqft"] = area

            if record.get("property_description"):
                records.append(record)

    return records


def _parse_auction_with_fallback(
    html: str,
    source_cfg: dict,
    strategies: list[Callable[[BeautifulSoup, dict], list[dict]]],
) -> list[dict]:
    """
    Multi-strategy parsing with fallback.

    Args:
        html: HTML content to parse
        source_cfg: Source configuration
        strategies: List of parsing functions to try in order.
                   Each function receives (soup, source_cfg) and returns list of records.
                   First strategy that returns non-empty results wins.
    """
    soup = BeautifulSoup(html, "html.parser")

    for strategy in strategies:
        try:
            records = strategy(soup, source_cfg)
            if records:
                logger.info("Strategy %s returned %d records for %s", strategy.__name__, len(records), source_cfg.get("url"))
                return records
        except Exception as e:
            logger.warning("Strategy %s failed for %s: %s", strategy.__name__, source_cfg.get("url"), e)
            continue

    logger.warning("All strategies failed for %s", source_cfg.get("url"))
    return []
