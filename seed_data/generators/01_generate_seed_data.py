#!/usr/bin/env python3
"""
Generate Category 2 seed JSON files.

Creates deterministic, realistic Indian data for all 360Ghar modules.
Run once, commit the output, edit as needed.

Usage:
    python -m seed_data.generators.generate_seed_data
    python seed_data/generators/generate_seed_data.py
"""

from __future__ import annotations

import json
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from seed_data.shared import (
    BANKS,
    BLOG_TOPICS,
    CLEANLINESS,
    FIRST_NAMES_F,
    FIRST_NAMES_M,
    FLATMATES_MODES,
    FOOD_HABITS,
    GUESTS_POLICIES,
    HARDCODED_AGENT_NAMES,
    HARDCODED_AMENITY_TITLES,
    HARDCODED_USER_EMAILS,
    HARDCODED_USER_NAMES,
    HC_DIR_PROPERTY_TITLES,
    LAST_NAMES,
    LOCATIONS,
    SLEEP_SCHEDULES,
    SMOKING_DRINKING,
    WORK_STYLES,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
MEDIA_USERS_DIR = Path(__file__).resolve().parent.parent / "media" / "users"
random.seed(42)

# Stable namespace for deterministic UUID generation (tour/scene/hotspot IDs)
_SEED_NAMESPACE = uuid.UUID("a3f2c8e1-7b4d-4f6a-9e1c-2d5b8f0a3c7e")


def _det_uuid(name: str) -> str:
    """Generate a deterministic UUID from a name string. Same name always yields same UUID."""
    return str(uuid.uuid5(_SEED_NAMESPACE, name))


def _parse_user_image_filename(filename: str) -> dict[str, str] | None:
    """Parse filenames like female_25yr_priya_22460619.webp → {gender, age, name, hash}."""
    stem = Path(filename).stem
    parts = stem.split("_")
    if len(parts) < 4:
        return None
    gender = parts[0]
    age_str = parts[1].replace("yr", "")
    name = parts[2]
    file_hash = parts[3]
    return {"gender": gender, "age": age_str, "name": name, "hash": file_hash, "filename": filename}


def _build_user_image_pool() -> list[dict[str, str]]:
    """Scan media/users/ and return parsed image metadata."""
    pool: list[dict[str, str]] = []
    if not MEDIA_USERS_DIR.exists():
        return pool
    for f in MEDIA_USERS_DIR.iterdir():
        if f.is_file() and not f.name.startswith("."):
            parsed = _parse_user_image_filename(f.name)
            if parsed:
                parsed["path"] = f"media/users/{f.name}"
                pool.append(parsed)
    return pool


USER_IMAGE_POOL = _build_user_image_pool()
_used_images: list[str] = []


def _match_user_image(gender: str, first_name: str) -> str:
    """Find a matching image by gender+name, fall back to gender, then random."""
    name_lower = first_name.lower()
    gender_key = "female" if gender == "F" else "male"

    # Exact gender+name match
    for img in USER_IMAGE_POOL:
        if img["gender"] == gender_key and img["name"] == name_lower and img["path"] not in _used_images:
            _used_images.append(img["path"])
            return img["path"]

    # Gender-only match
    for img in USER_IMAGE_POOL:
        if img["gender"] == gender_key and img["path"] not in _used_images:
            _used_images.append(img["path"])
            return img["path"]

    # Any unused image
    for img in USER_IMAGE_POOL:
        if img["path"] not in _used_images:
            _used_images.append(img["path"])
            return img["path"]

    # All used, pick random
    return random.choice(USER_IMAGE_POOL)["path"] if USER_IMAGE_POOL else f"media/avatars/user_{random.randint(1, 50):02d}.webp"


def _gen_phone() -> str:
    return f"+91{random.randint(7000000000, 9999999999)}"


def _gen_email(first: str, last: str, idx: int) -> str:
    domains = ["gmail.com", "outlook.com", "yahoo.co.in"]
    return f"{first.lower()}.{last.lower()}{idx}@{random.choice(domains)}"


def _rand_date(days_back: int = 365) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=random.randint(0, days_back))
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rand_date_date(days_back: int = 365) -> str:
    d = date.today() - timedelta(days=random.randint(0, days_back))
    return d.isoformat()


def generate_users() -> list[dict[str, Any]]:
    users = []
    idx = 1
    for loc_key in ["gurgaon"]:
        loc = LOCATIONS[loc_key]
        for _ in range(50):
            gender = random.choice(["M", "F"])
            first = random.choice(FIRST_NAMES_M if gender == "M" else FIRST_NAMES_F)
            last = random.choice(LAST_NAMES)
            email = _gen_email(first, last, idx)
            phone = _gen_phone()
            is_flatmate = random.random() < 0.65
            fm_mode = random.choice(FLATMATES_MODES) if is_flatmate else None

            user = {
                "supabase_user_id": f"PLACEHOLDER_SEED_{email}",
                "email": email,
                "full_name": f"{first} {last}",
                "phone": phone,
                "date_of_birth": f"{random.randint(1985, 2002)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}T00:00:00Z",
                "role": random.choice(["user", "user", "user", "agent"]),
                "is_active": True,
                "is_verified": random.random() < 0.8,
                "current_latitude": loc["lat"] + random.uniform(-0.05, 0.05),
                "current_longitude": loc["lng"] + random.uniform(-0.05, 0.05),
                "preferences": {
                    "property_type": random.sample(["apartment", "villa", "builder_floor", "house"], k=2),
                    "purpose": random.choice(["rent", "buy"]),
                    "budget_min": random.randint(20000, 50000),
                    "budget_max": random.randint(50000, 200000),
                },
                "notification_settings": {"email_notifications": True, "push_notifications": True, "sms_notifications": random.random() < 0.3},
                "privacy_settings": {"profile_visibility": random.choice(["public", "friends"]), "location_sharing": random.random() < 0.5},
                "profile_image_url": _match_user_image(gender, first),
                "flatmates_mode": fm_mode,
                "flatmates_profile_status": "active" if is_flatmate else "draft",
                "flatmates_onboarding_completed": is_flatmate,
                "flatmates_bio": f"Hi, I'm {first}. Looking for a great place in {loc['city']}!" if is_flatmate else None,
                "flatmates_budget_min": random.randint(8000, 20000) if is_flatmate else None,
                "flatmates_budget_max": random.randint(20000, 50000) if is_flatmate else None,
                "flatmates_move_in_timeline": random.choice(["immediately", "within_month", "within_3_months"]) if is_flatmate else None,
                "flatmates_city": loc["city"] if is_flatmate else None,
                "flatmates_locality": random.choice(loc["localities"]) if is_flatmate else None,
                "flatmates_sleep_schedule": random.choice(SLEEP_SCHEDULES) if is_flatmate else None,
                "flatmates_cleanliness": random.choice(CLEANLINESS) if is_flatmate else None,
                "flatmates_food_habits": random.choice(FOOD_HABITS) if is_flatmate else None,
                "flatmates_smoking_drinking": random.choice(SMOKING_DRINKING) if is_flatmate else None,
                "flatmates_guests_policy": random.choice(GUESTS_POLICIES) if is_flatmate else None,
                "flatmates_work_style": random.choice(WORK_STYLES) if is_flatmate else None,
            }
            users.append(user)
            idx += 1
    return users


def generate_agents() -> list[dict[str, Any]]:
    agents = []
    agent_data = [
        ("Gurgaon", "M", "Rajesh", "Rajesh Kumar", "specialist", "intermediate"),
        ("Gurgaon", "F", "Priya", "Priya Nair", "general", "expert"),
        ("Gurgaon", "M", "Deepak", "Deepak Chauhan", "specialist", "beginner"),
        ("Gurgaon", "M", "Manoj", "Manoj Tiwari", "general", "intermediate"),
        ("Gurgaon", "F", "Neha", "Neha Sharma", "senior", "expert"),
        ("Gurgaon", "M", "Vikram", "Vikram Yadav", "specialist", "intermediate"),
        ("Gurgaon", "M", "Amit", "Amit Verma", "senior", "expert"),
        ("Gurgaon", "F", "Sunita", "Sunita Reddy", "general", "intermediate"),
        ("Gurgaon", "M", "Rahul", "Rahul Pandey", "specialist", "beginner"),
        ("Gurgaon", "F", "Kavita", "Kavita Joshi", "senior", "expert"),
    ]
    for city, gender, first, name, atype, exp in agent_data:
        agents.append({
            "name": name,
            "description": f"{city}-based property consultant specializing in residential properties.",
            "avatar_url": _match_user_image(gender, first),
            "contact_number": _gen_phone(),
            "languages": ["english", "hindi"],
            "agent_type": atype,
            "experience_level": exp,
            "is_active": True,
            "is_available": True,
            "working_hours": {"start": "09:00", "end": "19:00", "timezone": "Asia/Kolkata", "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]},
            "total_users_assigned": random.randint(10, 60),
            "user_satisfaction_rating": round(random.uniform(4.0, 5.0), 1),
        })
    return agents


def generate_properties() -> list[dict[str, Any]]:
    props = []
    prop_types = ["apartment", "villa", "builder_floor", "pg", "flatmate", "house", "studio", "penthouse"]
    purposes_map = {"apartment": ["buy", "rent", "short_stay"], "villa": ["buy", "rent"], "builder_floor": ["rent"], "pg": ["rent"], "flatmate": ["rent"], "house": ["buy", "rent"], "studio": ["rent", "short_stay"], "penthouse": ["buy", "rent"]}

    # We reference users by email, resolved at load time
    owner_emails = HARDCODED_USER_EMAILS
    # Add seed user emails (will be resolved from seed/users.json)

    idx = 1
    for loc_key in ["gurgaon"]:
        loc = LOCATIONS[loc_key]
        count = 100
        # Shuffle localities and cycle through to maximize coverage
        shuffled_localities = list(loc["localities"])
        random.shuffle(shuffled_localities)
        locality_cycle = (shuffled_localities * ((count // len(shuffled_localities)) + 1))[:count]
        for prop_i in range(count):
            ptype = prop_types[prop_i % len(prop_types)]
            purpose = random.choice(purposes_map.get(ptype, ["rent"]))
            bhk_key = random.choice(["1bhk", "2bhk", "3bhk", "4bhk"]) if ptype not in ("studio", "pg", "flatmate") else "1bhk"
            bedrooms = int(bhk_key[0])
            locality = locality_cycle[prop_i]
            builder = random.choice(loc["builders"]) if random.random() < 0.5 else ""

            area_sqft = {"1bhk": (400, 800), "2bhk": (800, 1600), "3bhk": (1400, 2500), "4bhk": (2200, 4500)}[bhk_key]
            area = random.randint(*area_sqft)

            if purpose == "rent":
                base_price = random.randint(*loc["rent_range"].get(bhk_key, (10000, 30000)))
                monthly_rent = base_price
                daily_rate = round(base_price / 30) if purpose == "short_stay" else None
                security = base_price * random.choice([1, 2, 3])
            elif purpose == "short_stay":
                daily_rate = random.randint(*loc["daily_rate_range"])
                base_price = daily_rate
                monthly_rent = None
                security = daily_rate * 5
            else:
                base_price = random.randint(*loc["buy_range"].get(bhk_key, (3000000, 15000000)))
                monthly_rent = None
                daily_rate = None
                security = None

            bathrooms = max(1, bedrooms - 1) if bedrooms > 1 else 1

            # A single property can serve rent, sale, or flatmate contexts.
            # All rent-purpose properties are flatmate-eligible for the Flatmates app.
            display_type = ptype
            if purpose == "rent":
                ptype = "flatmate"

            title = f"{bedrooms}BHK {display_type.replace('_', ' ').title()} in {locality}"
            if display_type in ("pg", "flatmate"):
                title = f"{display_type.upper()} Room in {locality}"

            lat_offset = random.uniform(-0.08, 0.08)
            lng_offset = random.uniform(-0.08, 0.08)
            lat = loc["lat"] + lat_offset
            lng = loc["lng"] + lng_offset

            amenities = random.sample(HARDCODED_AMENITY_TITLES, k=min(random.randint(3, 7), len(HARDCODED_AMENITY_TITLES)))

            image_categories = ["exterior", "hall", "room", "kitchen", "bathroom", "balcony"]
            images = []
            for j, cat in enumerate(image_categories[:random.randint(3, 5)]):
                images.append({
                    "url": f"media/properties/prop_{idx:03d}/{cat}.webp",
                    "category": cat,
                    "caption": f"{cat.replace('_', ' ').title()} view",
                    "is_main": j == 0,
                    "display_order": j,
                })

            owner_email = random.choice(owner_emails)

            props.append({
                "owner_ref": owner_email,
                "title": title,
                "description": f"Beautiful {bedrooms}BHK {display_type.replace('_', ' ')} in {locality}, {loc['city']}. Spacious {area} sq ft with modern amenities. Located {random.choice(loc['landmarks']).lower()}.",
                "property_type": ptype,
                "purpose": purpose,
                "status": "available",
                "latitude": lat,
                "longitude": lng,
                "location": f"SRID=4326;POINT({lng} {lat})",
                "city": loc["city"],
                "state": loc["state"],
                "country": "India",
                "pincode": random.choice(loc["pincodes"]),
                "locality": locality,
                "sub_locality": locality,
                "landmark": random.choice(loc["landmarks"]),
                "full_address": f"{locality}, {loc['city']}, {loc['state']}",
                "area_type": "Carpet Area",
                "base_price": base_price,
                "price_per_sqft": round(base_price / area, 2) if area and purpose == "buy" else None,
                "monthly_rent": monthly_rent,
                "daily_rate": daily_rate,
                "security_deposit": security,
                "maintenance_charges": random.randint(0, 5000) if purpose == "rent" else 0,
                "area_sqft": area,
                "bedrooms": bedrooms if display_type not in ("pg", "flatmate", "studio") else None,
                "bathrooms": bathrooms,
                "balconies": random.randint(0, 2),
                "parking_spaces": random.randint(0, 2),
                "floor_number": random.randint(1, 25) if ptype == "apartment" else None,
                "total_floors": random.randint(10, 40) if ptype == "apartment" else None,
                "age_of_property": random.randint(0, 20),
                "max_occupancy": None,
                "minimum_stay_days": 1,
                "features": [],
                "main_image_url": images[0]["url"] if images else None,
                "virtual_tour_url": None,
                "floor_plan_url": None,
                "video_tour_url": None,
                "tags": [display_type, ptype, purpose, locality, f"{bedrooms}bhk"],
                "search_keywords": f"{display_type} {purpose} {locality} {bedrooms}bhk {loc['city']}",
                "owner_name": random.choice(HARDCODED_AGENT_NAMES + list(HARDCODED_USER_NAMES.values())),
                "owner_contact": _gen_phone(),
                "builder_name": builder,
                "is_available": True,
                "available_from": "2025-01-01T00:00:00Z",
                "view_count": random.randint(10, 500),
                "like_count": random.randint(0, 50),
                "interest_count": random.randint(0, 20),
                "amenity_titles": amenities,
                "images": images,
            })
            idx += 1
    return props


def generate_visits(property_titles: list[str] | None = None) -> list[dict[str, Any]]:
    """Generate property visit records."""
    statuses = ["scheduled", "confirmed", "completed", "cancelled"]
    visits = []
    if not property_titles:
        property_titles = HC_DIR_PROPERTY_TITLES
    for _ in range(40):
        visits.append({
            "user_id_ref": random.choice(HARDCODED_USER_EMAILS),
            "property_id_ref": random.choice(property_titles),
            "agent_id_ref": random.choice(HARDCODED_AGENT_NAMES),
            "visit_context": "property_tour",
            "scheduled_date": _rand_date(30),
            "status": random.choice(statuses),
            "special_requirements": random.choice([None, "Need wheelchair access", "Prefer evening slot", "Bring family"]),
            "interest_level": random.choice(["high", "medium", "low", None]),
        })
    return visits


def generate_bookings(property_titles: list[str] | None = None) -> list[dict[str, Any]]:
    """Generate 360 Stays booking records."""
    statuses = ["pending", "confirmed", "checked_in", "checked_out", "cancelled", "completed"]
    payment_statuses = ["pending", "paid", "refunded"]
    if not property_titles:
        property_titles = HC_DIR_PROPERTY_TITLES
    bookings = []
    for i in range(25):
        nights = random.randint(1, 7)
        check_in = datetime.now(timezone.utc) + timedelta(days=random.randint(-30, 30))
        check_out = check_in + timedelta(days=nights)
        base = random.randint(3000, 15000) * nights
        status = random.choice(statuses)
        prop_title = random.choice(property_titles)
        bookings.append({
            "user_id_ref": random.choice(HARDCODED_USER_EMAILS),
            "property_id_ref": prop_title,
            "booking_reference": f"360S-{_det_uuid(f'booking_{prop_title}_{check_in.date()}').replace('-', '')[:8].upper()}",
            "check_in_date": check_in.isoformat(),
            "check_out_date": check_out.isoformat(),
            "nights": nights,
            "guests": random.randint(1, 4),
            "base_amount": base,
            "taxes_amount": round(base * 0.18),
            "service_charges": round(base * 0.05),
            "discount_amount": 0,
            "total_amount": round(base * 1.23),
            "booking_status": status,
            "payment_status": "paid" if status in ("confirmed", "checked_in", "checked_out", "completed") else random.choice(payment_statuses),
            "primary_guest_name": random.choice(FIRST_NAMES_M) + " " + random.choice(LAST_NAMES),
            "primary_guest_phone": _gen_phone(),
            "primary_guest_email": f"guest{i}@example.com",
            "special_requests": random.choice([None, "Early check-in", "Extra pillows", "Late checkout"]),
        })
    return bookings


def generate_tours() -> list[dict[str, Any]]:
    """Generate virtual tours with scenes and hotspots."""
    tours = []
    scenes_all = []
    hotspots_all = []

    tour_data = [
        {"title": "DLF Phase 3 Luxury Tour", "city": "Gurgaon", "visibility": "public", "status": "published"},
        {"title": "Sohna Road Villa Tour", "city": "Gurgaon", "visibility": "unlisted", "status": "published"},
        {"title": "Sector 49 Builder Floor Tour", "city": "Gurgaon", "visibility": "public", "status": "published"},
        {"title": "Golf Course Road Apartment Tour", "city": "Gurgaon", "visibility": "private", "status": "draft"},
        {"title": "MG Road Commercial Tour", "city": "Gurgaon", "visibility": "private", "status": "draft"},
        {"title": "Cyber City Penthouse Tour", "city": "Gurgaon", "visibility": "public", "status": "published"},
        {"title": "Sector 56 Family Home Tour", "city": "Gurgaon", "visibility": "unlisted", "status": "published"},
        {"title": "Sushant Lok Independent House Tour", "city": "Gurgaon", "visibility": "public", "status": "published"},
        {"title": "Dwarka Expressway 3BHK Tour", "city": "Gurgaon", "visibility": "public", "status": "published"},
        {"title": "Sector 82 Affordable Housing Tour", "city": "Gurgaon", "visibility": "public", "status": "published"},
        {"title": "Nirvana Country Villa Tour", "city": "Gurgaon", "visibility": "unlisted", "status": "published"},
        {"title": "Emaar Palm Hills Premium Tour", "city": "Gurgaon", "visibility": "public", "status": "published"},
    ]

    for i, td in enumerate(tour_data):
        tour_id = _det_uuid(f"tour_{td['title']}")
        tours.append({
            "id": tour_id,
            "user_id_ref": HARDCODED_USER_EMAILS[0],
            "title": td["title"],
            "description": f"Virtual 360° tour of a property in {td['city']}.",
            "status": td["status"],
            "is_public": td["visibility"] == "public",
            "visibility": td["visibility"],
            "is_featured": i < 3,
            "view_count": random.randint(50, 1000),
            "like_count": random.randint(5, 100),
            "share_count": random.randint(0, 30),
            "settings": {"autoRotate": True, "autoRotateSpeed": 0.5},
            "thumbnail_url": f"media/tours/tour_{i+1:03d}_thumb.webp",
        })

        # Generate 3-5 scenes per tour — collect scene IDs first so hotspots can reference them
        scene_names = ["Living Room", "Master Bedroom", "Kitchen", "Bathroom", "Balcony", "Entrance Hall", "Second Bedroom", "Terrace"]
        num_scenes = random.randint(3, 5)
        tour_scene_ids: list[str] = []
        for j in range(num_scenes):
            scene_id = _det_uuid(f"scene_{td['title']}_{scene_names[j]}")
            tour_scene_ids.append(scene_id)
            scenes_all.append({
                "id": scene_id,
                "tour_id": tour_id,
                "title": scene_names[j],
                "image_url": f"media/tours/tour_{i+1:03d}_scene_{j+1:02d}.webp",
                "thumbnail_url": f"media/tours/tour_{i+1:03d}_scene_{j+1:02d}_thumb.webp",
                "order_index": j,
                "is_processed": True,
            })

        # Now create hotspots with correct scene references
        for j in range(num_scenes):
            scene_id = tour_scene_ids[j]

            # Navigation hotspot to next scene
            if j < num_scenes - 1:
                hotspots_all.append({
                    "id": _det_uuid(f"hotspot_nav_{td['title']}_{scene_names[j]}_{scene_names[j+1]}"),
                    "scene_id": scene_id,
                    "type": "navigation",
                    "position": {"yaw": random.uniform(-180, 180), "pitch": random.uniform(-30, 30)},
                    "target_scene_id": tour_scene_ids[j + 1],
                    "title": f"Go to {scene_names[j+1]}",
                    "icon": "arrow_forward",
                    "order_index": j,
                    "is_active": True,
                })

            # Info hotspot
            if random.random() < 0.5:
                hotspots_all.append({
                    "id": _det_uuid(f"hotspot_info_{td['title']}_{scene_names[j]}"),
                    "scene_id": scene_id,
                    "type": "info",
                    "position": {"yaw": random.uniform(-180, 180), "pitch": random.uniform(-20, 40)},
                    "title": f"{scene_names[j]} Details",
                    "description": f"Beautifully designed {scene_names[j].lower()} with premium finishes.",
                    "icon": "info",
                    "order_index": j + 10,
                    "is_active": True,
                })

    return tours, scenes_all, hotspots_all


def generate_pm_data() -> dict[str, list]:
    """Generate Property Management data: leases, rent, maintenance, etc."""
    leases = []
    rent_charges = []
    rent_payments = []
    expenses = []
    maintenance = []
    documents = []
    inspections = []
    rental_apps = []

    lease_statuses = ["active", "active", "active", "expiring_soon", "draft", "pending_signature", "active", "active"]
    # Track per-lease property and tenant for consistent child records
    lease_prop_map: dict[str, str] = {}
    lease_tenant_map: dict[str, str] = {}
    form_slugs: list[str] = []

    for i in range(15):
        l_ref = f"lease_{i+1:03d}"
        prop_ref = random.choice(HC_DIR_PROPERTY_TITLES)
        tenant_ref = random.choice(HARDCODED_USER_EMAILS[1:])  # Skip first (owner)
        lease_prop_map[l_ref] = prop_ref
        lease_tenant_map[l_ref] = tenant_ref
        start = date.today() - timedelta(days=random.randint(30, 365))
        end = start + timedelta(days=365)
        monthly = random.randint(15000, 85000)

        leases.append({
            "_lease_ref": l_ref,
            "property_id_ref": prop_ref,
            "owner_id_ref": HARDCODED_USER_EMAILS[0],
            "tenant_user_id_ref": tenant_ref,
            "tenant_name": random.choice(FIRST_NAMES_M) + " " + random.choice(LAST_NAMES),
            "tenant_phone": _gen_phone(),
            "tenant_email": f"tenant{i+1}@example.com",
            "status": random.choice(lease_statuses),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "monthly_rent": monthly,
            "security_deposit": monthly * 2,
            "grace_period_days": 5,
            "payment_due_day": 1,
        })

        # 3 months of rent charges
        for m in range(3):
            total_months = start.month - 1 + m
            charge_year = start.year + total_months // 12
            charge_month = total_months % 12 + 1
            month_date = date(charge_year, charge_month, 1)
            due = date(month_date.year, month_date.month, 1)
            is_paid = random.random() < 0.8
            rc_status = "paid" if is_paid else random.choice(["pending", "overdue"])
            charge_ref = f"charge_{l_ref}_{m+1:02d}"

            rent_charges.append({
                "_charge_ref": charge_ref,
                "lease_id_ref": l_ref,
                "property_id_ref": prop_ref,
                "owner_id_ref": HARDCODED_USER_EMAILS[0],
                "tenant_user_id_ref": tenant_ref,
                "billing_month": month_date.isoformat(),
                "period_start": month_date.isoformat(),
                "period_end": (month_date + timedelta(days=27)).isoformat(),
                "due_date": due.isoformat(),
                "amount_due": monthly,
                "late_fee_assessed": 0 if is_paid else round(monthly * 0.02),
                "status": rc_status,
            })

            if is_paid:
                rent_payments.append({
                    "charge_id_ref": charge_ref,
                    "lease_id_ref": l_ref,
                    "property_id_ref": prop_ref,
                    "owner_id_ref": HARDCODED_USER_EMAILS[0],
                    "tenant_user_id_ref": tenant_ref,
                    "paid_at": (due + timedelta(days=random.randint(0, 5))).isoformat() + "T10:00:00Z",
                    "amount_paid": monthly,
                    "payment_method": random.choice(["upi", "bank_transfer", "cheque"]),
                    "reference": f"PAY-{_det_uuid(f'pay_{charge_ref}').replace('-', '')[:8]}",
                })

    # Expenses
    expense_cats = ["maintenance", "repairs", "insurance", "property_tax", "utilities", "hoa"]
    for i in range(20):
        expenses.append({
            "property_id_ref": random.choice(HC_DIR_PROPERTY_TITLES),
            "owner_id_ref": HARDCODED_USER_EMAILS[0],
            "category": random.choice(expense_cats),
            "amount": random.randint(2000, 50000),
            "expense_date": _rand_date_date(180),
            "description": f"{expense_cats[i % len(expense_cats)].replace('_', ' ').title()} expense",
        })

    # Maintenance requests
    maint_cats = ["plumbing", "electrical", "hvac", "appliance", "structural", "pest_control", "cleaning"]
    maint_statuses = ["open", "in_review", "work_order_created", "resolved", "closed"]
    for i in range(15):
        l_ref = f"lease_{(i % 8) + 1:03d}"
        maintenance.append({
            "property_id_ref": lease_prop_map.get(l_ref, random.choice(HC_DIR_PROPERTY_TITLES)),
            "lease_id_ref": l_ref,
            "owner_id_ref": HARDCODED_USER_EMAILS[0],
            "tenant_user_id_ref": lease_tenant_map.get(l_ref, HARDCODED_USER_EMAILS[1]),
            "category": maint_cats[i % len(maint_cats)],
            "urgency": random.choice(["low", "medium", "high", "emergency"]),
            "title": f"{maint_cats[i % len(maint_cats)].title()} Issue in Flat",
            "description": f"Reporting {maint_cats[i % len(maint_cats)]} issue that needs attention.",
            "request_status": maint_statuses[i % len(maint_statuses)],
            "estimated_cost": random.randint(1000, 25000) if random.random() < 0.5 else None,
        })

    # Documents
    doc_types = ["lease_agreement", "id_proof", "receipt", "invoice", "property_deed", "insurance_policy"]
    for i in range(15):
        l_ref = f"lease_{(i % 8) + 1:03d}"
        documents.append({
            "owner_id_ref": HARDCODED_USER_EMAILS[0],
            "property_id_ref": lease_prop_map.get(l_ref, random.choice(HC_DIR_PROPERTY_TITLES)),
            "lease_id_ref": l_ref,
            "document_type": doc_types[i % len(doc_types)],
            "title": f"{doc_types[i % len(doc_types)].replace('_', ' ').title()} #{i+1}",
            "file_url": f"media/documents/{doc_types[i % len(doc_types)]}_{i+1}.pdf",
            "file_path": f"documents/{doc_types[i % len(doc_types)]}_{i+1}.pdf",
            "mime_type": "application/pdf",
            "file_size": random.randint(10000, 5000000),
        })

    # Inspections
    for i in range(8):
        l_ref = f"lease_{(i % 8) + 1:03d}"
        inspections.append({
            "property_id_ref": lease_prop_map.get(l_ref, random.choice(HC_DIR_PROPERTY_TITLES)),
            "lease_id_ref": l_ref,
            "owner_id_ref": HARDCODED_USER_EMAILS[0],
            "inspection_type": random.choice(["move_in", "move_out", "routine"]),
            "conducted_by_user_id_ref": HARDCODED_USER_EMAILS[0],
            "conducted_at": _rand_date(180),
            "rooms_data": {"rooms": [{"name": "Living Room", "condition": "good", "notes": ""}]},
            "overall_notes": "Inspection completed. Property in good condition.",
        })

    # Rental applications
    for i in range(6):
        form_slug = f"rental-form-{LOCATIONS['gurgaon']['localities'][i].lower().replace(' ', '-')}"
        form_slugs.append(form_slug)
        rental_apps.append({
            "_type": "form",
            "owner_id_ref": HARDCODED_USER_EMAILS[0],
            "property_id_ref": random.choice(HC_DIR_PROPERTY_TITLES),
            "title": f"Rental Application - {LOCATIONS['gurgaon']['localities'][i]}",
            "description": "Standard rental application form",
            "slug": form_slug,
            "is_active": True,
        })

    for i in range(10):
        rental_apps.append({
            "_type": "application",
            "form_id_ref": random.choice(form_slugs),
            "property_id_ref": random.choice(HC_DIR_PROPERTY_TITLES),
            "owner_id_ref": HARDCODED_USER_EMAILS[0],
            "status": random.choice(["applicant", "approved", "active"]),
            "applicant_full_name": random.choice(FIRST_NAMES_M) + " " + random.choice(LAST_NAMES),
            "applicant_phone": _gen_phone(),
            "applicant_email": f"applicant{i+1}@example.com",
            "submitted_at": _rand_date(60),
        })

    return {
        "leases": leases,
        "rent_charges": rent_charges,
        "rent_payments": rent_payments,
        "expenses": expenses,
        "maintenance": maintenance,
        "documents": documents,
        "inspections": inspections,
        "rental_applications": rental_apps,
    }


def generate_blog_posts() -> list[dict[str, Any]]:
    """Generate blog posts with content."""
    posts = []
    for topic in BLOG_TOPICS:
        slug = topic["slug"]
        posts.append({
            "title": topic["title"],
            "slug": slug,
            "content": f"<h2>{topic['title']}</h2><p>This is a comprehensive guide about {topic['title'].lower()}. In today's Indian real estate market, understanding these concepts is crucial for making informed decisions.</p><p>The Indian real estate sector has seen significant growth in recent years, with Gurgaon leading the way in both residential and commercial development. RERA has brought much-needed transparency, and platforms like 360Ghar are making property discovery easier than ever.</p><p>Whether you're a first-time buyer or an experienced investor, staying informed about market trends, legal requirements, and neighborhood developments will help you make the best decisions for your future.</p>",
            "excerpt": f"A comprehensive guide covering {topic['title'].lower()} — essential reading for anyone navigating the Indian real estate market.",
            "cover_image_url": f"media/blogs/{slug}_cover.webp",
            "active": True,
            "status": "published",
            "author_id_ref": HARDCODED_USER_EMAILS[0],
            "_category_slugs": [topic["category"]],
            "_tag_slugs": topic["tags"],
        })
    return posts


def generate_data_hub() -> dict[str, list]:
    """Generate Data Hub seed data."""
    circle_rates = []
    sectors = [
        "Sector 1", "Sector 4", "Sector 5", "Sector 7", "Sector 9", "Sector 9A",
        "Sector 10", "Sector 10A", "Sector 12", "Sector 14", "Sector 15",
        "Sector 17", "Sector 21", "Sector 23", "Sector 24", "Sector 28", "Sector 29",
        "Sector 31", "Sector 33", "Sector 34", "Sector 37", "Sector 39", "Sector 40",
        "Sector 41", "Sector 43", "Sector 45", "Sector 46", "Sector 49", "Sector 50",
        "Sector 52", "Sector 56", "Sector 57", "Sector 65", "Sector 67", "Sector 70",
        "Sector 79", "Sector 82", "Sector 84", "Sector 85", "Sector 86", "Sector 88",
        "Sector 90", "Sector 92", "Sector 102", "Sector 104", "Sector 109",
        "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4", "DLF Phase 5",
        "Sohna Road", "Golf Course Road", "MG Road", "Dwarka Expressway",
        "Sushant Lok 1", "South City 1", "Palam Vihar", "Nirvana Country",
        "Udyog Vihar", "Manesar",
    ]
    for sector in sectors:
        for ptype in ["residential", "commercial", "plot"]:
            rate = random.randint(5000, 25000)
            circle_rates.append({
                "district": "Gurugram",
                "sector": sector,
                "property_type": ptype,
                "rate_per_sqft": rate,
                "rate_per_sqyd": rate * 9,
                "rate_per_sqm": round(rate * 10.76),
                "revision_year": 2024,
                "effective_date": "2024-04-01",
                "slug": f"gurugram-{sector.lower().replace(' ', '-')}-{ptype}",
            })

    rera_projects = []
    project_names = [
        "DLF Park Place", "M3M Golf Estate", "Sobha City", "Godrej Summit",
        "Emaar Palm Hills", "Vatika India Next", "Tata Primanti", "Mahindra Aura",
        "Experion Wind Song", "Ansal API Esencia", "Raheja Revanta", "DLF Skycourt",
        "M3M Woodshire", "Sobha International City", "Godrej Air",
        "Signature Global Orchard", "AIPL Joy Street", "Smart World Gems",
        "Bestech Parkview Spa", "IREO Grand Arch", "Puri Amanvilas",
        "BPTP Parklands", "Vatika Sovereign Park", "M3M Skywalk",
        "DLF Camellias", "Emaar Palm Drive", "Supertech Azaliya",
        "Godrej Meridien", "Tata La Vida", "M3M Prive",
    ]
    developers = LOCATIONS["gurgaon"]["builders"]
    for i, name in enumerate(project_names):
        rera_projects.append({
            "rera_number": f"HRERA-GGM-{random.randint(100, 999)}-{random.randint(100, 999)}",
            "project_name": name,
            "developer_name": developers[i % len(developers)],
            "location": LOCATIONS["gurgaon"]["localities"][i % len(LOCATIONS["gurgaon"]["localities"])],
            "district": "Gurugram",
            "total_units": random.randint(100, 2000),
            "units_booked": random.randint(50, 1500),
            "possession_date": f"202{random.randint(4,7)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            "status": random.choice(["registered", "registered", "registered", "lapsed", "completed"]),
            "complaint_count": random.randint(0, 50),
        })

    bank_auctions = []
    banks = BANKS
    for i in range(20):
        bank_auctions.append({
            "source": random.choice(["sbi", "pnb", "bob", "canara", "hdfc", "icici", "union", "yes_bank"]),
            "bank_name": banks[i % len(banks)],
            "property_description": f"Residential flat in {random.choice(LOCATIONS['gurgaon']['localities'])}, Gurgaon",
            "property_type": random.choice(["residential", "commercial"]),
            "city": "Gurgaon",
            "locality": random.choice(LOCATIONS["gurgaon"]["localities"]),
            "reserve_price": random.randint(2000000, 50000000),
            "emd_amount": random.randint(100000, 1000000),
            "auction_date": _rand_date_date(90),
            "is_active": True,
        })

    court_auctions = []
    for _ in range(10):
        court_auctions.append({
            "source": "drt",
            "case_number": f"DRT/{random.randint(100,999)}/{random.randint(2020,2026)}",
            "borrower_name": random.choice(FIRST_NAMES_M) + " " + random.choice(LAST_NAMES),
            "property_description": f"Property under DRT auction in {random.choice(['Gurgaon', 'Delhi NCR'])}",
            "city": random.choice(["Gurgaon", "Delhi NCR"]),
            "reserve_price": random.randint(3000000, 20000000),
            "auction_date": _rand_date_date(120),
            "court_name": f"DRT-{random.randint(1,5)} New Delhi",
            "is_active": True,
        })

    gazette = []
    for _ in range(10):
        gazette.append({
            "notification_number": f"HR-{random.randint(100,999)}/{random.randint(2020,2026)}",
            "notification_date": _rand_date_date(365),
            "department": random.choice(["Town & Country Planning", "HUDA", "DTCP", "Revenue Department"]),
            "notification_type": random.choice(["land_acquisition", "rate_revision", "policy", "clu_change"]),
            "title": f"Gazette Notification regarding {random.choice(['circle rate revision', 'land acquisition', 'CLU change', 'policy update'])} in Gurgaon",
            "summary": "Notification regarding changes in property regulations and rates in Gurgaon district.",
        })

    zoning = []
    for sector in sectors[:8]:
        zoning.append({
            "sector": sector,
            "slug": f"gurugram-{sector.lower().replace(' ', '-')}-residential",
            "land_use": "residential",
            "far_limit": round(random.uniform(1.5, 2.75), 2),
            "max_height_m": round(random.uniform(15, 60), 1),
            "max_coverage_pct": round(random.uniform(30, 65), 1),
            "master_plan_year": 2031,
        })

    colony_approvals = []
    for i in range(5):
        colony_approvals.append({
            "colony_name": f"{random.choice(LOCATIONS['gurgaon']['builders'])} Colony {i+1}",
            "developer_name": random.choice(LOCATIONS["gurgaon"]["builders"]),
            "district": "Gurugram",
            "licence_number": f"LIC-{random.randint(100,999)}/{random.randint(2020,2026)}",
            "approval_status": random.choice(["approved", "approved", "pending"]),
            "sector": random.choice(sectors[:8]),
        })

    bank_rates = []
    rate_data = [
        ("SBI", "mclr_1y", 8.50), ("SBI", "home_loan_min", 8.60),
        ("HDFC Ltd", "home_loan_min", 8.45), ("HDFC Ltd", "mclr_1y", 8.70),
        ("ICICI Bank", "home_loan_min", 8.75), ("ICICI Bank", "mclr_1y", 8.80),
        ("Bank of Baroda", "home_loan_min", 8.55), ("Bank of Baroda", "mclr_1y", 8.40),
        ("PNB", "home_loan_min", 8.65), ("PNB", "repo", 6.50),
    ]
    for bank, rtype, rate in rate_data:
        bank_rates.append({
            "bank_name": bank,
            "rate_type": rtype,
            "rate_value": rate,
            "effective_date": "2025-04-01",
            "source": "RBI/Bank website",
        })

    neighbourhoods = []
    for _ in range(50):
        neighbourhoods.append({
            "listing_id_ref": random.choice(HC_DIR_PROPERTY_TITLES),
            "latitude": LOCATIONS["gurgaon"]["lat"] + random.uniform(-0.05, 0.05),
            "longitude": LOCATIONS["gurgaon"]["lng"] + random.uniform(-0.05, 0.05),
            "overall_score": random.randint(60, 95),
            "category_scores": {
                "transit": random.randint(50, 95),
                "schools": random.randint(40, 90),
                "hospitals": random.randint(45, 95),
                "shopping": random.randint(50, 90),
                "safety": random.randint(55, 95),
            },
            "nearby_places": [
                {"name": f"Place {j}", "type": random.choice(["school", "hospital", "mall", "park"]), "distance_km": round(random.uniform(0.5, 5), 1)}
                for j in range(3)
            ],
            "stale_after": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
        })

    rera_complaints = []
    for _ in range(10):
        rera_complaints.append({
            "order_number": f"HRERA/GGM/{random.randint(100,999)}/{random.randint(2020,2026)}",
            "order_date": _rand_date_date(365),
            "complainant_type": "allottee",
            "respondent_builder": random.choice(developers[:5]),
            "complaint_nature": random.choice(["delay", "quality", "refund"]),
            "penalty_amount": random.randint(50000, 5000000) if random.random() < 0.4 else None,
        })

    return {
        "circle_rates": circle_rates,
        "rera_projects": rera_projects,
        "rera_complaints": rera_complaints,
        "bank_auctions": bank_auctions,
        "court_auctions": court_auctions,
        "gazette": gazette,
        "zoning": zoning,
        "colony_approvals": colony_approvals,
        "bank_rates": bank_rates,
        "neighbourhoods": neighbourhoods,
    }


def generate_bug_reports() -> list[dict[str, Any]]:
    return [
        {"source": "mobile", "bug_type": "functionality_bug", "severity": "medium", "title": "Search filters not applying on property list", "description": "When selecting multiple filters, only the first one takes effect.", "status": "open"},
        {"source": "web", "bug_type": "ui_bug", "severity": "low", "title": "Tour viewer button overlaps on small screens", "description": "The hotspot icon overlaps the scene title on screens under 375px wide.", "status": "in_progress"},
        {"source": "api", "bug_type": "performance_issue", "severity": "high", "title": "Slow response on neighborhood scores endpoint", "description": "NeighbourhoodScore API takes 5+ seconds for some properties.", "status": "open"},
    ]


def main() -> None:
    """Generate all Category 2 seed JSON files."""
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating Category 2 seed data...")

    # Users
    users = generate_users()
    _write("01_users.json", users)
    [u["email"] for u in users]

    # Agents
    agents = generate_agents()
    _write("02_agents.json", agents)

    # Properties: synthetic property generation is DISABLED. The catalog is
    # sourced exclusively from the 109 real hardcoded properties (loaded from
    # hardcoded/properties/00xxx/ dirs), each with correct data + its own
    # matching images. We write empty lists so the loader (which no longer
    # creates seed properties — see load_seed_properties) has nothing to ingest
    # and a regenerate can't recreate the misleading synthetic listings.
    _write("03_properties.json", [])
    _write("04_property_images.json", [])

    # Visits + bookings reference the real hardcoded catalog titles so their
    # property refs resolve in the IDMap.
    prop_titles = HC_DIR_PROPERTY_TITLES
    _write("05_visits.json", generate_visits(prop_titles))
    _write("06_bookings.json", generate_bookings(prop_titles))

    # Tours
    tours, scenes, hotspots = generate_tours()
    _write("07_tours.json", tours)
    _write("08_scenes.json", scenes)
    _write("09_hotspots.json", hotspots)

    # Tour locations
    tour_locs = []
    for t in tours:
        loc_key = "gurgaon"
        loc = LOCATIONS[loc_key]
        tour_locs.append({
            "tour_id": t["id"],
            "name": t["title"],
            "address": f"{random.choice(loc['localities'])}, {loc['city']}, {loc['state']}",
            "city": loc["city"],
            "state": loc["state"],
            "country": "India",
            "latitude": loc["lat"] + random.uniform(-0.03, 0.03),
            "longitude": loc["lng"] + random.uniform(-0.03, 0.03),
        })
    _write("10_tour_locations.json", tour_locs)

    # Floor plans
    floor_plans = [{"tour_id": tours[i]["id"], "name": f"Floor {j+1}", "image_url": f"media/floor_plans/floor_plan_{i+1:02d}_{j+1}.webp", "floor_number": j+1} for i in range(min(5, len(tours))) for j in range(random.randint(1, 3))]
    _write("11_floor_plans.json", floor_plans)

    # Tour branding
    tour_branding = [{"tour_id": tours[i]["id"], "settings": {"primaryColor": "#2563eb", "logoUrl": None, "companyName": "360Ghar"}} for i in range(min(3, len(tours)))]
    _write("12_tour_branding.json", tour_branding)

    # Media files
    media_files = []
    for t in tours[:5]:
        media_files.append({"user_id_ref": HARDCODED_USER_EMAILS[0], "tour_id": t["id"], "filename": f"{t['title'].replace(' ', '_')}.webp", "original_filename": "panorama.webp", "file_url": t["thumbnail_url"], "file_size": random.randint(500000, 5000000), "mime_type": "image/webp", "width": 8192, "height": 4096, "folder": "tours", "visibility": "public", "is_processed": True, "upload_status": "complete"})
    _write("13_media_files.json", media_files)

    # AI jobs
    ai_jobs = [{"user_id_ref": HARDCODED_USER_EMAILS[0], "tour_id": tours[0]["id"] if tours else None, "job_type": "scene_analysis", "status": "completed", "progress": 100, "retry_count": 0}]
    _write("14_ai_jobs.json", ai_jobs)

    # PM data
    pm = generate_pm_data()
    _write("15_leases.json", pm["leases"])
    _write("17_rent_charges.json", pm["rent_charges"])
    _write("18_rent_payments.json", pm["rent_payments"])
    _write("19_expenses.json", pm["expenses"])
    _write("20_maintenance_requests.json", pm["maintenance"])
    _write("21_documents.json", pm["documents"])
    _write("22_inspections.json", pm["inspections"])
    _write("16_rental_applications.json", pm["rental_applications"])

    # Blog posts
    _write("23_blog_posts.json", generate_blog_posts())

    # Data hub
    dh = generate_data_hub()
    _write("24_data_hub_circle_rates.json", dh["circle_rates"])
    _write("25_data_hub_rera.json", dh["rera_projects"] + [{"_type": "rera_complaint", **c} for c in dh["rera_complaints"]])
    _write("26_data_hub_auctions.json", [{"_type": "bank_auction", **a} for a in dh["bank_auctions"]] + [{"_type": "court_auction", **a} for a in dh["court_auctions"]])
    _write("27_data_hub_gazette.json", dh["gazette"])
    _write("28_data_hub_zoning.json", [{"_type": "zoning", **z} for z in dh["zoning"]] + [{"_type": "colony_approval", **c} for c in dh["colony_approvals"]])
    _write("29_data_hub_bank_rates.json", dh["bank_rates"])
    _write("30_data_hub_neighbourhoods.json", dh["neighbourhoods"])

    # Bug reports
    _write("31_bug_reports.json", generate_bug_reports())

    print(f"Done! Generated seed data in {SEED_DIR}")


def _write(filename: str, data: list[dict[str, Any]]) -> None:
    path = SEED_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Written: {filename} ({len(data)} records)")


if __name__ == "__main__":
    main()
