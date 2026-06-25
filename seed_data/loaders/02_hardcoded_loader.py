"""
HardcodedLoader — loads Category 1 (team-curated) data.

Reads JSON from seed_data/hardcoded/ and inserts into DB.
Populates the shared IDMap so seed/activity loaders can resolve references.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.blogs import BlogCategory, BlogTag
from app.models.core import FAQ, AppVersion, Page
from app.models.properties import Amenity, Property, PropertyAmenity, PropertyImage
from app.models.social import AppCatalog
from app.models.users import User

_base = importlib.import_module("seed_data.loaders.01_base")
HARDCODED_DIR = _base.HARDCODED_DIR
HARDCODED_PROPERTIES_DIR = HARDCODED_DIR / "properties"
SimpleLoader = _base.SimpleLoader
IDMap = _base.IDMap
load_json = _base.load_json

logger = get_logger(__name__)

# Map display-style property types (used in hardcoded property.json) to PropertyType enum values.
PROPERTY_TYPE_MAP: dict[str, str] = {
    "2BHK Apartment": "apartment",
    "3BHK Apartment": "apartment",
    "Apartment": "apartment",
    "Builder Floor": "builder_floor",
    "penthouse": "penthouse",
}

# Map listing image filenames (without extension) to ImageCategory enum values.
LISTING_IMAGE_CATEGORY_MAP: dict[str, str] = {
    "living_room": "hall",
    "drawing_room": "hall",
    "dining_room": "hall",
    "hall": "hall",
    "master_bedroom": "room",
    "kids_bedroom": "room",
    "bedroom_2": "room",
    "bedroom_3": "room",
    "bedroom_4": "room",
    "bedroom": "room",
    "study_room": "room",
    "puja_room": "room",
    "kitchen": "kitchen",
    "bathroom": "bathroom",
    "second_bathroom": "bathroom",
    "balcony": "balcony",
    "balcony_terrace": "terrace",
    "terrace": "terrace",
    "entrance": "entrance",
    "building_exterior": "exterior",
    "exterior": "exterior",
    "street_view": "exterior",
    "parking": "parking",
    "garden": "garden",
    "lobby": "others",
    "store_room": "others",
    "servant_room": "others",
    "utility": "others",
}

# Priority order for choosing a property's MAIN (hero) image. The exterior shot
# is always preferred so the listing card leads with the building/facade rather
# than a random interior. When a property has no exterior image we fall back
# down this list, and finally to the first image if none of these categories
# are present. Keep this in sync with the repair step in fix_property_images.py.
MAIN_IMAGE_CATEGORY_PRIORITY: tuple[str, ...] = (
    "exterior",
    "hall",
    "balcony",
    "terrace",
    "entrance",
    "kitchen",
    "room",
    "bathroom",
    "garden",
    "parking",
    "interior",
    "others",
)


def pick_main_image_index(categories: list[str]) -> int:
    """Return the index of the best main-image candidate given each image's
    category, preferring ``exterior`` (see ``MAIN_IMAGE_CATEGORY_PRIORITY``).

    Falls back to index 0 when none of the prioritized categories are present
    (the caller guarantees the list is non-empty).
    """
    for category in MAIN_IMAGE_CATEGORY_PRIORITY:
        for idx, cat in enumerate(categories):
            if cat == category:
                return idx
    return 0


# Fields in the source property.json that are not on the Property model and
# are not stored anywhere else. They go into the `features` JSON column.
HC_PROPERTY_EXTRA_FIELDS: tuple[str, ...] = (
    "slug",
    "facing",
    "furnishing_level",
    "occupancy_type",
    "rera_registered",
    "society_name",
    "vastu_compliant",
)

# Default owner for bulk hardcoded properties (Saksham's email).
DEFAULT_HC_OWNER_REF = "saksham1991999@gmail.com"

# Spread of the 39 rent-original properties across Flatmate / Stay.
# A single property can serve rent, sale, or flatmate — all rent properties
# are flatmate-eligible. Indices 0-28 → flatmate (29), indices 29-38 → stay (10).
HC_RENT_BUCKETS: tuple[str, ...] = (
    *("flatmate",) * 29,
    *("stay",) * 10,
)


def _classify_rent_property(rent_index: int) -> str:
    """Return the bucket label for a property whose original purpose is rent.

    ``rent_index`` is the zero-based index of this property among all
    rent-original properties, encountered in sorted directory order.
    """
    if rent_index < 0 or rent_index >= len(HC_RENT_BUCKETS):
        return "rent"
    return HC_RENT_BUCKETS[rent_index]


async def load_hardcoded_users(id_map: IDMap, media_urls: dict[str, str] | None = None) -> dict[str, int]:
    """Load hardcoded team users and populate IDMap."""
    records = load_json(HARDCODED_DIR / "01_users.json")
    created = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        for data in records:
            email = data.get("email")
            phone = data.get("phone")
            # Check existence by email or phone
            stmt = select(User).where(User.email == email)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                id_map.put("user", email, existing.id)
                id_map.put("user", phone, existing.id)
                skipped += 1
                continue

            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            clean["is_seed_data"] = True
            # Handle null supabase_user_id
            if clean.get("supabase_user_id") and clean["supabase_user_id"].startswith("PLACEHOLDER"):
                clean["supabase_user_id"] = f"seed-{email}"
            _resolve_media_refs(clean, media_urls or {})
            record = User(**clean)
            session.add(record)
            await session.flush()
            id_map.put("user", email, record.id)
            id_map.put("user", phone, record.id)
            created += 1

        await session.commit()

    logger.info("Hardcoded users: %d created, %d skipped", created, skipped)
    return {"created": created, "skipped": skipped}


async def load_hardcoded_agents(id_map: IDMap) -> dict[str, int]:
    """Load hardcoded agents and populate IDMap."""
    records = load_json(HARDCODED_DIR / "02_agents.json")
    created = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        for data in records:
            name = data.get("name")
            stmt = select(Agent).where(Agent.name == name)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                id_map.put("agent", name, existing.id)
                skipped += 1
                continue

            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            clean["is_seed_data"] = True
            record = Agent(**clean)
            session.add(record)
            await session.flush()
            id_map.put("agent", name, record.id)
            created += 1

        await session.commit()

    logger.info("Hardcoded agents: %d created, %d skipped", created, skipped)
    return {"created": created, "skipped": skipped}


async def load_hardcoded_properties(id_map: IDMap, media_urls: dict[str, str]) -> dict[str, int]:
    """Load hardcoded properties with images and amenities."""
    records = load_json(HARDCODED_DIR / "04_properties.json")
    created = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        for data in records:
            # Copy to avoid mutating the original dict
            data = dict(data)
            owner_ref = data.pop("owner_ref", None)
            amenity_titles = data.pop("amenity_titles", [])
            images_data = data.pop("images", [])

            # Resolve owner
            owner_id = id_map.get("user", owner_ref)
            if not owner_id:
                logger.warning("Owner not found for ref %s, skipping property", owner_ref)
                skipped += 1
                continue
            data["owner_id"] = owner_id

            # Resolve media URLs
            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            clean["is_seed_data"] = True
            _resolve_media_refs(clean, media_urls)

            title = clean.get("title")
            stmt = select(Property).where(Property.title == title, Property.owner_id == owner_id)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                id_map.put("property", title, existing.id)
                skipped += 1
                continue

            record = Property(**clean)
            session.add(record)
            await session.flush()
            id_map.put("property", title, record.id)

            # Create property images
            for img in images_data:
                img_url = _resolve_url(img.get("url", ""), media_urls)
                img_record = PropertyImage(
                    property_id=record.id,
                    image_url=img_url,
                    caption=img.get("caption"),
                    image_category=img.get("category", "others"),
                    is_main_image=img.get("is_main", False),
                    display_order=img.get("display_order", 0),
                )
                session.add(img_record)

            # Create property amenities
            for title_str in amenity_titles:
                amenity_stmt = select(Amenity).where(Amenity.title == title_str)
                amenity = (await session.execute(amenity_stmt)).scalar_one_or_none()
                if amenity:
                    pa = PropertyAmenity(property_id=record.id, amenity_id=amenity.id)
                    session.add(pa)

            created += 1

        await session.commit()

    logger.info("Hardcoded properties: %d created, %d skipped", created, skipped)
    return {"created": created, "skipped": skipped}


def _resolve_url(ref: str, media_urls: dict[str, str]) -> str:
    """Replace media/ references with real Supabase URLs."""
    if ref.startswith("media/") and ref in media_urls:
        return media_urls[ref]
    return ref


def _resolve_media_refs(data: dict[str, Any], media_urls: dict[str, str]) -> None:
    """In-place resolve media/ refs via the shared resolver rule.

    Unresolved refs become NULL (never a relative path) — see
    ``01_base.resolve_media_value``.
    """
    for key, value in data.items():
        data[key] = _base.resolve_media_value(value, media_urls, key=key)


async def load_hc_properties_from_dirs(
    id_map: IDMap,
    media_urls: dict[str, str],
    default_owner_ref: str = DEFAULT_HC_OWNER_REF,
) -> dict[str, int]:
    """Bulk-load hardcoded properties from per-property directories.

    Each directory under ``hardcoded/properties/`` is expected to contain:
    - ``property.json`` with a ``property`` dict + ``images`` array
    - ``listing_images/`` with webp images (referenced from the images array)
    - ``floor_plan.png``

    Listing images (only) become ``PropertyImage`` rows with categories
    inferred from the filename. Equirectangular (360) images are skipped.
    Extra metadata (society_name, rera_registered, vastu_compliant, facing,
    furnishing_level, occupancy_type, slug) is folded into the ``features``
    JSON column. When amenity names match a known ``Amenity`` row, a
    ``PropertyAmenity`` link is also created. Matching is case-sensitive
    first, then falls back to case-insensitive. Unmatched features are
    logged as warnings but remain in the ``features`` JSON column.
    """
    if not HARDCODED_PROPERTIES_DIR.exists():
        logger.warning("Hardcoded properties directory not found: %s", HARDCODED_PROPERTIES_DIR)
        return {"created": 0, "skipped": 0}

    owner_id = id_map.get("user", default_owner_ref)
    if not owner_id:
        logger.warning("Default owner %s not found in IDMap, skipping hc properties", default_owner_ref)
        return {"created": 0, "skipped": 0}

    # Pre-build amenity title → id lookup (case-sensitive + case-insensitive fallback)
    async with AsyncSessionLocal() as session:
        all_amenities = (await session.execute(select(Amenity))).scalars().all()
    amenity_id_by_title: dict[str, int] = {a.title: a.id for a in all_amenities}
    amenity_id_by_title_lower: dict[str, int] = {a.title.lower().strip(): a.id for a in all_amenities}

    created = 0
    skipped = 0
    failed = 0
    rent_index = 0  # Tracks the position among rent-original properties for bucket assignment
    bucket_counts: dict[str, int] = {"sale": 0, "rent": 0, "stay": 0, "flatmate": 0}
    total_unmatched_features = 0  # Tally across all properties

    async with AsyncSessionLocal() as session:
        for prop_dir in sorted(HARDCODED_PROPERTIES_DIR.iterdir()):
            if not prop_dir.is_dir() or not prop_dir.name.startswith("00"):
                continue
            slug = prop_dir.name
            property_json = prop_dir / "property.json"
            if not property_json.exists():
                logger.warning("Missing property.json in %s, skipping", slug)
                skipped += 1
                continue

            try:
                with open(property_json, encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception as exc:
                logger.error("Failed to read %s: %s", property_json, exc)
                failed += 1
                continue

            prop_data = raw.get("property", raw)
            images_list = raw.get("images", [])

            title = prop_data.get("title")
            if not title:
                logger.warning("Property %s has no title, skipping", slug)
                skipped += 1
                continue

            # Determine the spread bucket before dedup so the bucket counter is stable
            raw_purpose_norm = (prop_data.get("purpose") or "").strip().lower()
            if raw_purpose_norm == "buy":
                bucket = "sale"
            elif raw_purpose_norm == "rent":
                bucket = _classify_rent_property(rent_index)
                rent_index += 1
            else:
                bucket = None  # unknown → keep source purpose

            # Dedup by the directory slug stored in the features JSON. We must
            # compare against what _build_hc_property_payload actually STORES —
            # ``extras["slug"] = slug`` (the directory name, e.g.
            # ``00101-godrej-...``) — NOT ``prop_data["slug"]`` (the source
            # value ``godrej-...``), which is never written. Comparing against
            # the source value made this lookup never match, so every re-run
            # re-inserted all 109 properties (8 historical runs → 865 rows).
            # We do NOT fall back to title+owner because the source has 109
            # properties that share only 33 unique titles — title-based dedup
            # would incorrectly drop 76 distinct listings.
            source_slug = slug
            slug_stmt = select(Property).where(
                cast(Property.features, JSONB)["slug"].astext == source_slug,
                Property.owner_id == owner_id,
            )
            existing = (await session.execute(slug_stmt)).scalar_one_or_none()
            if existing:
                id_map.put("property", source_slug, existing.id)
                skipped += 1
                continue

            clean = _build_hc_property_payload(prop_data, slug, owner_id, media_urls, bucket=bucket)
            if clean is None:
                failed += 1
                continue

            try:
                record = Property(**clean)
                session.add(record)
                await session.flush()
            except Exception as exc:
                logger.error("Failed to insert property %s: %s", title, exc)
                await session.rollback()
                failed += 1
                continue

            id_map.put("property", title, record.id)

            # Listing images (filter to listing_images/ only — skip 360 panoramas)
            listing_images = [img for img in images_list if isinstance(img, str) and img.startswith("listing_images/")]
            # Choose the exterior shot (or best fallback) as the main image so
            # every listing leads with the building facade, not a random room.
            main_idx = pick_main_image_index([_listing_image_category(p) for p in listing_images]) if listing_images else 0
            for order, img_path in enumerate(listing_images):
                url = _add_listing_image(
                    session, record.id, slug, img_path, order, media_urls,
                    is_main=(order == main_idx),
                )
                if order == main_idx:
                    record.main_image_url = url

            # Floor plan
            floor_plan_path = prop_dir / "floor_plan.png"
            if floor_plan_path.exists():
                _set_floor_plan(record, slug, media_urls)

            # Amenity links (try to match features list against known amenities)
            features_list = prop_data.get("features") or []
            prop_unmatched = 0
            if isinstance(features_list, list):
                for amenity_title in features_list:
                    if not isinstance(amenity_title, str):
                        continue
                    # Exact match first, then case-insensitive fallback
                    amenity_id = amenity_id_by_title.get(amenity_title)
                    if amenity_id is None:
                        amenity_id = amenity_id_by_title_lower.get(amenity_title.lower().strip())
                    if amenity_id:
                        existing_pa = await session.execute(
                            select(PropertyAmenity).where(
                                PropertyAmenity.property_id == record.id,
                                PropertyAmenity.amenity_id == amenity_id,
                            )
                        )
                        if existing_pa.scalar_one_or_none() is None:
                            session.add(PropertyAmenity(property_id=record.id, amenity_id=amenity_id))
                    else:
                        prop_unmatched += 1
                        total_unmatched_features += 1

            if prop_unmatched:
                logger.warning(
                    "Property %s: %d feature(s) did not match any catalog amenity",
                    slug, prop_unmatched,
                )

            created += 1
            if bucket is not None:
                bucket_counts[bucket] += 1

        await session.commit()

    if total_unmatched_features:
        logger.warning(
            "Hardcoded properties (bulk): %d total feature(s) across all properties "
            "did not match any catalog amenity — these are stored in the features "
            "JSON column but have no PropertyAmenity join row",
            total_unmatched_features,
        )
    logger.info(
        "Hardcoded properties (bulk): %d created, %d skipped, %d failed | buckets=%s",
        created, skipped, failed, bucket_counts,
    )
    return {"created": created, "skipped": skipped, "failed": failed}


def _build_hc_property_payload(
    prop_data: dict[str, Any],
    slug: str,
    owner_id: int,
    media_urls: dict[str, str],
    bucket: str | None = None,
) -> dict[str, Any] | None:
    """Build a Property model payload from a raw hardcoded property dict.

    ``bucket`` is one of ``"sale"`` / ``"rent"`` / ``"stay"`` / ``"flatmate"`` /
    ``None``. When provided, it overrides the source-purpose's role in the
    four-categories spread:
      - ``sale``      → ``purpose="buy"``
      - ``rent``      → ``purpose="rent"``
      - ``stay``      → ``purpose="short_stay"`` with derived ``daily_rate``
      - ``flatmate``  → ``purpose="rent"`` with ``property_type="flatmate"``

    When ``bucket`` is ``None`` (default), the source purpose is honored as-is.

    Returns ``None`` if the property cannot be mapped to the model.
    """
    # Map property_type to enum
    raw_type = prop_data.get("property_type")
    mapped_type = PROPERTY_TYPE_MAP.get(raw_type) if isinstance(raw_type, str) else None
    if mapped_type is None:
        logger.warning("Unknown property_type %r for %s, skipping", raw_type, slug)
        return None

    # Normalize purpose from source data
    raw_purpose = prop_data.get("purpose")
    src_purpose = raw_purpose.strip().lower() if isinstance(raw_purpose, str) else None
    if src_purpose not in {"buy", "rent", "short_stay"}:
        logger.warning("Unknown purpose %r for %s, defaulting to 'rent'", raw_purpose, slug)
        src_purpose = "rent"

    # Apply the spread bucket
    purpose = src_purpose
    if bucket == "sale":
        purpose = "buy"
    elif bucket == "rent":
        purpose = "rent"
    elif bucket == "stay":
        purpose = "short_stay"
    elif bucket == "flatmate":
        purpose = "rent"
        mapped_type = "flatmate"
    elif bucket is not None:
        logger.warning("Unknown bucket %r for %s, falling back to source purpose", bucket, slug)

    # Normalize status
    status = prop_data.get("status") or "available"

    # Property.base_price is Numeric(10, 2) — cap at the column max to avoid DB errors.
    # Original value is preserved in features["base_price_original"] for visibility.
    NUMERIC_10_2_MAX = 99_999_999.99
    base_price = prop_data.get("base_price")
    if isinstance(base_price, (int, float)) and base_price > NUMERIC_10_2_MAX:
        logger.warning(
            "base_price %.2f exceeds Numeric(10, 2) max for %s, capping to %.2f",
            base_price, slug, NUMERIC_10_2_MAX,
        )
        base_price = NUMERIC_10_2_MAX

    # Derive price fields from the chosen purpose
    monthly_rent = prop_data.get("monthly_rent")
    daily_rate = prop_data.get("daily_rate")
    if purpose == "buy":
        # Sale: keep base_price (sale price); no rent fields
        monthly_rent = None
        daily_rate = None
    elif purpose == "short_stay":
        # Stay: derive daily_rate from monthly_rent if missing
        if daily_rate is None and isinstance(monthly_rent, (int, float)) and monthly_rent > 0:
            daily_rate = round(monthly_rent / 30.0, 2)
        monthly_rent = None
        # base_price for short_stay is the daily_rate (matches existing seed conventions)
        if daily_rate is not None:
            base_price = daily_rate
    else:
        # rent / flatmate: keep monthly_rent, no daily_rate
        daily_rate = None

    # Fold extras into features JSON
    extras: dict[str, Any] = {}
    for field in HC_PROPERTY_EXTRA_FIELDS:
        if field in prop_data:
            extras[field] = prop_data[field]
    # Override slug with the directory slug (unique per file). The source's
    # ``slug`` field collides across many files (e.g. 22 files share
    # ``ompee-drona-floors-palam-vihar-3bhk-builder-floor``); the directory
    # name has a numeric prefix that is unique.
    extras["slug"] = slug
    features_list = prop_data.get("features") or []
    if isinstance(features_list, list):
        extras["amenities"] = features_list
    # Preserve the original (uncapped) base_price if it was capped above
    original_bp = prop_data.get("base_price")
    if isinstance(original_bp, (int, float)) and original_bp > NUMERIC_10_2_MAX:
        extras["base_price_original"] = original_bp
    # Note the bucket this property was placed into for traceability
    if bucket is not None:
        extras["listing_bucket"] = bucket

    # Build clean payload
    payload: dict[str, Any] = {
        "title": prop_data.get("title"),
        "description": prop_data.get("description"),
        "property_type": mapped_type,
        "purpose": purpose,
        "status": status,
        "latitude": prop_data.get("latitude"),
        "longitude": prop_data.get("longitude"),
        "city": prop_data.get("city"),
        "state": prop_data.get("state"),
        "country": prop_data.get("country", "India"),
        "pincode": prop_data.get("pincode"),
        "locality": prop_data.get("locality"),
        "sub_locality": prop_data.get("sub_locality"),
        "landmark": prop_data.get("landmark"),
        "full_address": prop_data.get("full_address"),
        "area_type": prop_data.get("area_type"),
        "base_price": base_price,
        "price_per_sqft": prop_data.get("price_per_sqft"),
        "monthly_rent": monthly_rent,
        "daily_rate": daily_rate,
        "security_deposit": prop_data.get("security_deposit"),
        "maintenance_charges": prop_data.get("maintenance_charges"),
        "area_sqft": prop_data.get("area_sqft"),
        "bedrooms": prop_data.get("bedrooms"),
        "bathrooms": prop_data.get("bathrooms"),
        "balconies": prop_data.get("balconies"),
        "parking_spaces": prop_data.get("parking_spaces"),
        "floor_number": prop_data.get("floor_number"),
        "total_floors": prop_data.get("total_floors"),
        "age_of_property": prop_data.get("age_of_property"),
        "max_occupancy": prop_data.get("max_occupancy"),
        "minimum_stay_days": (
            1 if purpose == "short_stay"
            else prop_data.get("minimum_stay_days", 1)
        ),
        "features": extras,
        "virtual_tour_url": None,
        "video_tour_url": None,
        "tags": prop_data.get("tags"),
        "search_keywords": prop_data.get("search_keywords"),
        "owner_id": owner_id,
        "owner_name": prop_data.get("owner_name"),
        "owner_contact": prop_data.get("owner_contact"),
        "builder_name": prop_data.get("builder_name"),
        "is_available": True,
        "is_seed_data": True,
    }

    # PostGIS location if both lat/lng are present
    lat = payload.get("latitude")
    lng = payload.get("longitude")
    if lat is not None and lng is not None:
        payload["location"] = f"SRID=4326;POINT({lng} {lat})"

    return payload


def _listing_image_category(img_path: str) -> str:
    """Infer the ``image_category`` for a listing image from its filename."""
    stem = Path(img_path).stem
    return LISTING_IMAGE_CATEGORY_MAP.get(stem, "others")


def _add_listing_image(
    session: Any,
    property_id: int,
    slug: str,
    img_path: str,
    display_order: int,
    media_urls: dict[str, str],
    *,
    is_main: bool,
) -> str:
    """Add a single listing image as a ``PropertyImage`` row and return its URL.

    ``img_path`` is the relative path inside the property directory
    (e.g. ``"listing_images/living_room.webp"``). It is converted to a
    ``media/...`` ref and resolved against the uploaded media URLs. The caller
    decides which image is the main one (see ``pick_main_image_index``) and
    passes ``is_main`` accordingly, rather than defaulting to the first image.
    """
    filename = Path(img_path).name
    stem = Path(filename).stem
    category = LISTING_IMAGE_CATEGORY_MAP.get(stem, "others")
    media_ref = f"media/hc_properties/{slug}/listing_images/{filename}"
    resolved_url = media_urls.get(media_ref, media_ref)

    session.add(PropertyImage(
        property_id=property_id,
        image_url=resolved_url,
        caption=stem.replace("_", " ").title(),
        image_category=category,
        is_main_image=is_main,
        display_order=display_order,
    ))
    return resolved_url


def _set_floor_plan(record: Property, slug: str, media_urls: dict[str, str]) -> None:
    """Set the floor plan URL on a property from its local floor_plan.png."""
    media_ref = f"media/hc_properties/{slug}/floor_plan.png"
    record.floor_plan_url = media_urls.get(media_ref, media_ref)


async def load_all_hardcoded(id_map: IDMap, media_urls: dict[str, str]) -> dict[str, dict[str, int]]:
    """Load all hardcoded data in dependency order."""
    results: dict[str, dict[str, int]] = {}

    # 1. Amenities (properties reference them)
    loader = SimpleLoader(Amenity, ["title"])
    results["amenities"] = await loader.load(load_json(HARDCODED_DIR / "03_amenities.json"))

    # 2. Users
    results["users"] = await load_hardcoded_users(id_map, media_urls)

    # 3. Agents
    results["agents"] = await load_hardcoded_agents(id_map)

    # 4. Properties (with images + amenities)
    results["properties"] = await load_hardcoded_properties(id_map, media_urls)

    # 4b. Bulk hardcoded properties (109 real listings with real images)
    results["hc_properties"] = await load_hc_properties_from_dirs(id_map, media_urls)

    # 5. FAQs
    loader = SimpleLoader(FAQ, ["question"])
    results["faqs"] = await loader.load(load_json(HARDCODED_DIR / "05_faqs.json"))

    # 6. Pages
    loader = SimpleLoader(Page, ["unique_name"])
    results["pages"] = await loader.load(load_json(HARDCODED_DIR / "06_pages.json"))

    # 7. App versions
    loader = SimpleLoader(AppVersion, [])
    results["app_versions"] = await loader.load(load_json(HARDCODED_DIR / "07_app_versions.json"))

    # 8. Blog categories
    loader = SimpleLoader(BlogCategory, ["slug"])
    results["blog_categories"] = await loader.load(load_json(HARDCODED_DIR / "08_blog_categories.json"))

    # 9. Blog tags
    loader = SimpleLoader(BlogTag, ["slug"])
    results["blog_tags"] = await loader.load(load_json(HARDCODED_DIR / "09_blog_tags.json"))

    # 10. Lifestyle catalogs (AppCatalog)
    loader = SimpleLoader(AppCatalog, ["key"])
    results["lifestyle_catalogs"] = await loader.load(load_json(HARDCODED_DIR / "10_lifestyle_catalogs.json"))

    return results
