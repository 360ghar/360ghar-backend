"""
SeedLoader — loads Category 2 (deterministic generated) data.

Reads JSON from seed_data/seed/ and inserts into DB.
Covers: users, agents, properties, images, visits, bookings,
tours, PM, blog, data hub, bug reports, AI conversations.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import date

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.blogs import BlogCategory, BlogPost, BlogPostCategory, BlogPostTag, BlogTag
from app.models.bookings import Booking
from app.models.core import BugReport
from app.models.data_hub import (
    BankAuction,
    BankRate,
    CircleRate,
    ColonyApproval,
    CourtAuction,
    GazetteNotification,
    NeighbourhoodScore,
    ReraComplaint,
    ReraProject,
    ZoningData,
)
from app.models.pm_documents import Document
from app.models.pm_finance import Expense, RentCharge, RentPayment
from app.models.pm_inspections import InspectionChecklist
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.pm_tenants import RentalApplication, RentalApplicationForm
from app.models.properties import Visit
from app.models.tours import (
    AIJob,
    FloorPlan,
    Hotspot,
    MediaFile,
    Scene,
    Tour,
    TourBranding,
    TourLocation,
)
from app.models.users import User

_base = importlib.import_module("seed_data.loaders.01_base")
SEED_DIR = _base.SEED_DIR
SimpleLoader = _base.SimpleLoader
IDMap = _base.IDMap
load_json = _base.load_json
resolve_refs = _base.resolve_refs

logger = get_logger(__name__)


async def load_seed_users(id_map: IDMap, media_urls: dict[str, str] | None = None) -> dict[str, int]:
    """Load seed users and register them in IDMap."""
    records = load_json(SEED_DIR / "01_users.json")
    created = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        for data in records:
            email = data.get("email")
            phone = data.get("phone")
            stmt = select(User).where(User.email == email)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                id_map.put("user", email, existing.id)
                if phone:
                    id_map.put("user", phone, existing.id)
                skipped += 1
                continue

            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            clean["is_seed_data"] = True
            if clean.get("supabase_user_id") and clean["supabase_user_id"].startswith("PLACEHOLDER"):
                clean["supabase_user_id"] = f"seed-{email}"
            clean = resolve_refs(clean, id_map, media_urls, model=User)
            record = User(**clean)
            session.add(record)
            await session.flush()
            id_map.put("user", email, record.id)
            if phone:
                id_map.put("user", phone, record.id)
            created += 1

        await session.commit()

    logger.info("Seed users: %d created, %d skipped", created, skipped)
    return {"created": created, "skipped": skipped}


async def load_seed_agents(id_map: IDMap) -> dict[str, int]:
    """Load seed agents and register in IDMap."""
    records = load_json(SEED_DIR / "02_agents.json")
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

    logger.info("Seed agents: %d created, %d skipped", created, skipped)
    return {"created": created, "skipped": skipped}


async def load_seed_properties(id_map: IDMap, media_urls: dict[str, str]) -> dict[str, int]:
    """Synthetic property creation is intentionally DISABLED.

    The generated ``seed/03_properties.json`` records are fabricated listings
    ("2BHK Apartment in Sector 43") with no real images of their own — they
    previously borrowed hardcoded image sets, producing listings whose photos
    didn't match the property. The catalog is now sourced **exclusively** from
    the 109 real hardcoded properties (loaded by ``load_hc_properties_from_dirs``
    in 02_hardcoded_loader.py), each with correct data and its own matching
    images. So this loader creates no properties.

    Generated activity (visits/bookings/swipes) is pointed at the hardcoded
    property titles in the generators, so nothing here needs to register seed
    property refs in the IDMap.
    """
    logger.info(
        "Seed properties: synthetic property creation disabled — catalog is "
        "hardcoded-only (see load_hc_properties_from_dirs). 0 created."
    )
    return {"created": 0, "skipped": 0}


async def load_all_seed(id_map: IDMap, media_urls: dict[str, str]) -> dict[str, dict[str, int]]:
    """Load all Category 2 seed data in dependency order."""
    results: dict[str, dict[str, int]] = {}

    # ── Users & Agents ──────────────────────────────────────────
    results["seed_users"] = await load_seed_users(id_map, media_urls)
    results["seed_agents"] = await load_seed_agents(id_map)

    # ── Properties ───────────────────────────────────────────────
    results["seed_properties"] = await load_seed_properties(id_map, media_urls)

    # ── Visits + Bookings (parallel — independent of each other) ──
    visit_records = load_json(SEED_DIR / "05_visits.json")
    resolved_visits = [resolve_refs(r, id_map, media_urls, model=Visit) for r in visit_records]
    booking_records = load_json(SEED_DIR / "06_bookings.json")
    resolved_bookings = [resolve_refs(r, id_map, media_urls, model=Booking) for r in booking_records]

    async def _safe_load_vb(key: str, coro):
        try:
            return key, await coro
        except Exception as exc:
            logger.warning("Skipping %s: %s", key, exc)
            return key, {"created": 0, "skipped": 0}

    vb_results = await asyncio.gather(
        _safe_load_vb("seed_visits", SimpleLoader(Visit, []).load(resolved_visits)),
        _safe_load_vb("seed_bookings", SimpleLoader(Booking, ["booking_reference"]).load(resolved_bookings)),
    )
    for key, res in vb_results:
        results[key] = res

    # ── Tours ────────────────────────────────────────────────────
    try:
        tour_records = load_json(SEED_DIR / "07_tours.json")
        created_tours = 0
        async with AsyncSessionLocal() as session:
            for data in tour_records:
                clean = resolve_refs(data, id_map, media_urls, model=Tour)
                title = clean.get("title")
                user_id = clean.get("user_id")
                stmt = select(Tour).where(Tour.title == title, Tour.user_id == user_id)
                existing = (await session.execute(stmt)).scalar_one_or_none()
                if existing:
                    id_map.put("tour", title, existing.id)
                    continue
                record = Tour(**clean)
                session.add(record)
                await session.flush()
                id_map.put("tour", title, record.id)
                created_tours += 1
            await session.commit()
        results["seed_tours"] = {"created": created_tours, "skipped": 0}
    except Exception as exc:
        logger.warning("Skipping tours: %s", exc)
        results["seed_tours"] = {"created": 0, "skipped": 0}

    # ── Scenes ───────────────────────────────────────────────────
    try:
        scene_records = load_json(SEED_DIR / "08_scenes.json")
        created_scenes = 0
        async with AsyncSessionLocal() as session:
            for data in scene_records:
                clean = resolve_refs(data, id_map, media_urls, model=Scene)
                stmt = select(Scene).where(Scene.id == clean.get("id"))
                existing = (await session.execute(stmt)).scalar_one_or_none()
                if existing:
                    continue
                record = Scene(**clean)
                session.add(record)
                created_scenes += 1
            await session.commit()
        results["seed_scenes"] = {"created": created_scenes, "skipped": 0}
    except Exception as exc:
        logger.warning("Skipping scenes: %s", exc)
        results["seed_scenes"] = {"created": 0, "skipped": 0}

    # ── Hotspots ─────────────────────────────────────────────────
    try:
        hotspot_records = load_json(SEED_DIR / "09_hotspots.json")
        resolved_hotspots = [resolve_refs(r, id_map, media_urls, model=Hotspot) for r in hotspot_records]
        hl = SimpleLoader(Hotspot, [])
        results["seed_hotspots"] = await hl.load(resolved_hotspots)
    except Exception as exc:
        logger.warning("Skipping hotspots: %s", exc)
        results["seed_hotspots"] = {"created": 0, "skipped": 0}

    # ── Tour extras (locations, floor plans, branding, media, AI jobs) ──
    for label, fname, model_cls in [
        ("seed_tour_locations", "10_tour_locations.json", TourLocation),
        ("seed_floor_plans", "11_floor_plans.json", FloorPlan),
        ("seed_tour_branding", "12_tour_branding.json", TourBranding),
        ("seed_media_files", "13_media_files.json", MediaFile),
        ("seed_ai_jobs", "14_ai_jobs.json", AIJob),
    ]:
        try:
            recs = load_json(SEED_DIR / fname)
            resolved = [resolve_refs(r, id_map, media_urls, model=model_cls) for r in recs]
            results[label] = await SimpleLoader(model_cls, []).load(resolved)
        except Exception as exc:
            logger.warning("Skipping %s: %s", label, exc)
            results[label] = {"created": 0, "skipped": 0}

    # ── PM: Rental application forms ─────────────────────────────
    try:
        raf_records = load_json(SEED_DIR / "16_rental_applications.json")
        # Split into forms and applications
        forms = [r for r in raf_records if r.get("_type") == "form"]
        apps = [r for r in raf_records if r.get("_type") == "application"]
        resolved_forms = [resolve_refs(r, id_map, media_urls, model=RentalApplicationForm) for r in forms]
        results["seed_rental_forms"] = await SimpleLoader(RentalApplicationForm, ["slug"]).load(resolved_forms)
        # Populate IDMap with form slug → DB ID so applications can resolve form_id_ref
        async with AsyncSessionLocal() as session:
            all_forms = (await session.execute(select(RentalApplicationForm))).scalars().all()
            for form in all_forms:
                if form.slug:
                    id_map.put("rental_form", form.slug, form.id)
        # Resolve apps AFTER forms are in IDMap (form_id_ref → form_id needs rental_form entries)
        resolved_apps = [resolve_refs(r, id_map, media_urls, model=RentalApplication) for r in apps]
        results["seed_rental_apps"] = await SimpleLoader(RentalApplication, []).load(resolved_apps)
    except Exception as exc:
        logger.warning("Skipping rental applications: %s", exc)
        results["seed_rental_forms"] = {"created": 0, "skipped": 0}
        results["seed_rental_apps"] = {"created": 0, "skipped": 0}

    # ── PM: Leases ───────────────────────────────────────────────
    try:
        lease_records = load_json(SEED_DIR / "15_leases.json")
        created_leases = 0
        async with AsyncSessionLocal() as session:
            for data in lease_records:
                lease_ref = data.pop("_lease_ref", None)
                clean = resolve_refs(data, id_map, media_urls, model=Lease)
                # Primary dedupe: if lease_ref already registered, skip
                if lease_ref and id_map.has("lease", lease_ref):
                    continue
                # Fallback dedupe: (property_id, tenant_user_id, start_date)
                prop_id = clean.get("property_id")
                tenant_id = clean.get("tenant_user_id")
                start_date_raw = clean.get("start_date")
                if prop_id and tenant_id:
                    stmt = select(Lease).where(
                        Lease.property_id == prop_id,
                        Lease.tenant_user_id == tenant_id,
                    )
                    if start_date_raw:
                        start_date_val = date.fromisoformat(start_date_raw) if isinstance(start_date_raw, str) else start_date_raw
                        stmt = stmt.where(Lease.start_date == start_date_val)
                    existing = (await session.execute(stmt)).first()
                    if existing:
                        if lease_ref:
                            id_map.put("lease", lease_ref, existing[0].id)
                        continue
                # Partial unique index uq_leases_property_active only allows
                # one active lease per property.  If an active lease already
                # exists for this property, mark the new one as "expired".
                if prop_id and clean.get("status", "draft") == "active":
                    active_check = await session.execute(
                        select(Lease.id).where(
                            Lease.property_id == prop_id,
                            Lease.status == "active",
                        ).limit(1)
                    )
                    if active_check.first():
                        clean["status"] = "expired"
                record = Lease(**clean)
                session.add(record)
                await session.flush()
                if lease_ref:
                    id_map.put("lease", lease_ref, record.id)
                created_leases += 1
            await session.commit()
        results["seed_leases"] = {"created": created_leases, "skipped": 0}
    except Exception as exc:
        logger.warning("Skipping leases: %s", exc)
        results["seed_leases"] = {"created": 0, "skipped": 0}

    # ── PM: Rent charges (depends on leases in IDMap) ─────────────
    try:
        rc_records = load_json(SEED_DIR / "17_rent_charges.json")
        created_rc = 0
        async with AsyncSessionLocal() as session:
            for data in rc_records:
                charge_ref = data.pop("_charge_ref", None)
                if charge_ref and id_map.has("rent_charge", charge_ref):
                    continue
                try:
                    clean = resolve_refs(data, id_map, media_urls, model=RentCharge)
                    lease_id = clean.get("lease_id")
                    billing_month_raw = clean.get("billing_month")
                    if lease_id and billing_month_raw:
                        billing_month_val = date.fromisoformat(billing_month_raw) if isinstance(billing_month_raw, str) else billing_month_raw
                        existing = (await session.execute(
                            select(RentCharge).where(
                                RentCharge.lease_id == lease_id,
                                RentCharge.billing_month == billing_month_val,
                            )
                        )).first()
                        if existing:
                            if charge_ref:
                                id_map.put("rent_charge", charge_ref, existing[0].id)
                            continue
                    record = RentCharge(**clean)
                    session.add(record)
                    await session.flush()
                    if charge_ref:
                        id_map.put("rent_charge", charge_ref, record.id)
                    created_rc += 1
                    if created_rc % 20 == 0:
                        await session.commit()
                except Exception as rc_exc:
                    # Unique constraint (lease_id, billing_month) — look up existing
                    if "uq_rent_charges_lease_month" in str(rc_exc) and lease_id and billing_month_raw:
                        billing_month_val = date.fromisoformat(billing_month_raw) if isinstance(billing_month_raw, str) else billing_month_raw
                        existing = (await session.execute(
                            select(RentCharge).where(
                                RentCharge.lease_id == lease_id,
                                RentCharge.billing_month == billing_month_val,
                            )
                        )).first()
                        if existing and charge_ref:
                            id_map.put("rent_charge", charge_ref, existing[0].id)
                    else:
                        logger.warning("Skipping rent charge (ref=%s): %s", charge_ref, rc_exc)
                    await session.rollback()
                    continue
            await session.commit()
        results["seed_rent_charges"] = {"created": created_rc, "skipped": 0}
    except Exception as exc:
        logger.warning("Skipping rent charges: %s", exc)
        results["seed_rent_charges"] = {"created": 0, "skipped": 0}

    # ── PM: Rent payments (depends on charges in IDMap) ───────────
    try:
        rp_records = load_json(SEED_DIR / "18_rent_payments.json")
        resolved_rp = [resolve_refs(r, id_map, media_urls, model=RentPayment) for r in rp_records]
        results["seed_rent_payments"] = await SimpleLoader(RentPayment, []).load(resolved_rp)
    except Exception as exc:
        logger.warning("Skipping rent payments: %s", exc)
        results["seed_rent_payments"] = {"created": 0, "skipped": 0}

    # ── PM: Expenses ─────────────────────────────────────────────
    try:
        ex_records = load_json(SEED_DIR / "19_expenses.json")
        resolved_ex = [resolve_refs(r, id_map, media_urls, model=Expense) for r in ex_records]
        results["seed_expenses"] = await SimpleLoader(Expense, []).load(resolved_ex)
    except Exception as exc:
        logger.warning("Skipping expenses: %s", exc)
        results["seed_expenses"] = {"created": 0, "skipped": 0}

    # ── PM: Maintenance ──────────────────────────────────────────
    try:
        mr_records = load_json(SEED_DIR / "20_maintenance_requests.json")
        resolved_mr = [resolve_refs(r, id_map, media_urls, model=MaintenanceRequest) for r in mr_records]
        results["seed_maintenance"] = await SimpleLoader(MaintenanceRequest, []).load(resolved_mr)
    except Exception as exc:
        logger.warning("Skipping maintenance: %s", exc)
        results["seed_maintenance"] = {"created": 0, "skipped": 0}

    # ── PM: Documents ────────────────────────────────────────────
    try:
        doc_records = load_json(SEED_DIR / "21_documents.json")
        resolved_doc = [resolve_refs(r, id_map, media_urls, model=Document) for r in doc_records]
        results["seed_documents"] = await SimpleLoader(Document, []).load(resolved_doc)
    except Exception as exc:
        logger.warning("Skipping documents: %s", exc)
        results["seed_documents"] = {"created": 0, "skipped": 0}

    # ── PM: Inspections ──────────────────────────────────────────
    try:
        ic_records = load_json(SEED_DIR / "22_inspections.json")
        resolved_ic = [resolve_refs(r, id_map, media_urls, model=InspectionChecklist) for r in ic_records]
        results["seed_inspections"] = await SimpleLoader(InspectionChecklist, []).load(resolved_ic)
    except Exception as exc:
        logger.warning("Skipping inspections: %s", exc)
        results["seed_inspections"] = {"created": 0, "skipped": 0}

    # ── Blog posts ────────────────────────────────────────────────
    try:
        bp_records = load_json(SEED_DIR / "23_blog_posts.json")
        created_bps = 0
        async with AsyncSessionLocal() as session:
            for data in bp_records:
                category_slugs = data.pop("_category_slugs", [])
                tag_slugs = data.pop("_tag_slugs", [])
                clean = resolve_refs(data, id_map, media_urls, model=BlogPost)
                slug = clean.get("slug")
                stmt = select(BlogPost).where(BlogPost.slug == slug)
                existing = (await session.execute(stmt)).scalar_one_or_none()
                if existing:
                    continue
                record = BlogPost(**clean)
                session.add(record)
                await session.flush()
                # Link categories and tags
                for cslug in category_slugs:
                    c = (await session.execute(select(BlogCategory).where(BlogCategory.slug == cslug))).scalar_one_or_none()
                    if c:
                        session.add(BlogPostCategory(post_id=record.id, category_id=c.id))
                for tslug in tag_slugs:
                    t = (await session.execute(select(BlogTag).where(BlogTag.slug == tslug))).scalar_one_or_none()
                    if t:
                        session.add(BlogPostTag(post_id=record.id, tag_id=t.id))
                created_bps += 1
            await session.commit()
        results["seed_blog_posts"] = {"created": created_bps, "skipped": 0}
    except Exception as exc:
        logger.warning("Skipping blog posts: %s", exc)
        results["seed_blog_posts"] = {"created": 0, "skipped": 0}

    # ── Data Hub (parallel — all independent) ─────────────────────
    # Pre-load and split JSON data
    all_rera = load_json(SEED_DIR / "25_data_hub_rera.json")
    rera_projects = [r for r in all_rera if r.get("_type", "rera_project") == "rera_project" or "_type" not in r]
    rera_complaints = [r for r in all_rera if r.get("_type") == "rera_complaint"]

    all_auctions = load_json(SEED_DIR / "26_data_hub_auctions.json")
    bank_auctions = [r for r in all_auctions if r.get("_type", "bank_auction") == "bank_auction" or "_type" not in r]
    court_auctions = [r for r in all_auctions if r.get("_type") == "court_auction"]

    all_zoning = load_json(SEED_DIR / "28_data_hub_zoning.json")
    zoning_data = [r for r in all_zoning if r.get("_type", "zoning") == "zoning" or "_type" not in r]
    colony_approvals = [r for r in all_zoning if r.get("_type") == "colony_approval"]

    nb_records = load_json(SEED_DIR / "30_data_hub_neighbourhoods.json")
    for rec in nb_records:
        if "property_id_ref" in rec:
            rec["listing_id_ref"] = rec.pop("property_id_ref")
    resolved_nb = [resolve_refs(r, id_map, media_urls, model=NeighbourhoodScore) for r in nb_records]
    for rec in resolved_nb:
        if "property_id" in rec:
            rec["listing_id"] = rec.pop("property_id")

    br_records = load_json(SEED_DIR / "31_bug_reports.json")
    resolved_br = [resolve_refs(r, id_map, media_urls, model=BugReport) for r in br_records]

    async def _safe_load(key: str, coro):
        """Run a loader coroutine, catching any DB schema mismatch errors."""
        try:
            return key, await coro
        except Exception as exc:
            logger.warning("Skipping %s: %s", key, exc)
            return key, {"created": 0, "skipped": 0}

    dh_tasks = [
        _safe_load("seed_circle_rates", SimpleLoader(CircleRate, []).load(load_json(SEED_DIR / "24_data_hub_circle_rates.json"))),
        _safe_load("seed_rera", SimpleLoader(ReraProject, ["rera_number"]).load(rera_projects)),
        _safe_load("seed_rera_complaints", SimpleLoader(ReraComplaint, ["order_number"]).load(rera_complaints)),
        _safe_load("seed_bank_auctions", SimpleLoader(BankAuction, []).load(bank_auctions)),
        _safe_load("seed_court_auctions", SimpleLoader(CourtAuction, []).load(court_auctions)),
        _safe_load("seed_gazette", SimpleLoader(GazetteNotification, []).load(load_json(SEED_DIR / "27_data_hub_gazette.json"))),
        _safe_load("seed_zoning", SimpleLoader(ZoningData, []).load(zoning_data)),
        _safe_load("seed_colony_approvals", SimpleLoader(ColonyApproval, []).load(colony_approvals)),
        _safe_load("seed_bank_rates", SimpleLoader(BankRate, []).load(load_json(SEED_DIR / "29_data_hub_bank_rates.json"))),
        _safe_load("seed_neighbourhoods", SimpleLoader(NeighbourhoodScore, []).load(resolved_nb)),
        _safe_load("seed_bug_reports", SimpleLoader(BugReport, []).load(resolved_br)),
    ]
    dh_results = await asyncio.gather(*dh_tasks)
    for key, res in dh_results:
        results[key] = res

    return results
