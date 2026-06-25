"""
Shared constants for seed data generators.

Reads team-curated data from hardcoded/ JSON files and exposes them
as Python constants — single source of truth. Both generators import
from here instead of duplicating values.
"""

from __future__ import annotations

import json
from pathlib import Path

SEED_DATA_DIR = Path(__file__).resolve().parent
HARDCODED_DIR = SEED_DATA_DIR / "hardcoded"
SEED_DIR = SEED_DATA_DIR / "seed"


def _load(name: str) -> list[dict]:
    with open(HARDCODED_DIR / name) as f:
        return json.load(f)


def _load_seed(name: str) -> list[dict]:
    path = SEED_DIR / name
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


# ── Hardcoded users ────────────────────────────────────────────
HARDCODED_USERS = _load("01_users.json")
HARDCODED_USER_EMAILS = [u["email"] for u in HARDCODED_USERS]
HARDCODED_USER_NAMES = {u["email"]: u["full_name"] for u in HARDCODED_USERS}

# ── Hardcoded agents ───────────────────────────────────────────
HARDCODED_AGENTS = _load("02_agents.json")
HARDCODED_AGENT_NAMES = [a["name"] for a in HARDCODED_AGENTS]

# ── Seed agents (generated, but needed for activity gen) ───────
SEED_AGENT_NAMES = [a["name"] for a in _load_seed("02_agents.json")]
ALL_AGENT_NAMES = HARDCODED_AGENT_NAMES + SEED_AGENT_NAMES

# ── Hardcoded amenities ────────────────────────────────────────
HARDCODED_AMENITY_TITLES = [a["title"] for a in _load("03_amenities.json")]

# ── Hardcoded properties ───────────────────────────────────────
HARDCODED_PROPERTIES = _load("04_properties.json")
HARDCODED_PROPERTY_TITLES = [p["title"] for p in HARDCODED_PROPERTIES]


def _load_hc_dir_property_titles() -> list[str]:
    """Titles of the 109 real properties under hardcoded/properties/00xxx/.

    These directory-based listings (loaded by ``load_hc_properties_from_dirs``)
    are the ENTIRE property catalog — synthetic seed-property creation is
    disabled. Generated activity (visits/bookings/swipes/flatmate-visits) must
    reference these titles so the refs resolve in the IDMap (the loader
    registers each property under its ``title``). ``04_properties.json`` holds
    only 2 example rows, so ``HARDCODED_PROPERTY_TITLES`` alone is insufficient.
    """
    titles: list[str] = []
    props_dir = HARDCODED_DIR / "properties"
    if not props_dir.exists():
        return titles
    for prop_dir in sorted(props_dir.iterdir()):
        if not prop_dir.is_dir() or not prop_dir.name.startswith("00"):
            continue
        pj = prop_dir / "property.json"
        if not pj.exists():
            continue
        with open(pj, encoding="utf-8") as f:
            raw = json.load(f)
        prop = raw.get("property", raw)
        title = prop.get("title")
        if title:
            titles.append(title)
    return titles


# All real catalog property titles (the 109 directory listings). Falls back to
# the 2-row example list only if the directories are somehow absent.
HC_DIR_PROPERTY_TITLES = _load_hc_dir_property_titles() or HARDCODED_PROPERTY_TITLES

# ── Location data ──────────────────────────────────────────────
LOCATIONS = {
    "gurgaon": {
        "city": "Gurgaon", "state": "Haryana", "country": "India",
        "lat": 28.4595, "lng": 77.0266,
        "pincodes": [
            "122001", "122002", "122003", "122004", "122005", "122006",
            "122007", "122008", "122009", "122010", "122011",
            "122015", "122016", "122017", "122018",
            "122050", "122051", "122052", "122101", "122103",
        ],
        "localities": [
            # DLF micro-market
            "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4", "DLF Phase 5",
            "DLF Cyber City", "DLF City", "DLF Garden Estate",
            # Sectors — Old Gurgaon (west of NH-48)
            "Sector 1", "Sector 3", "Sector 4", "Sector 5",
            "Sector 7", "Sector 7 Extension", "Sector 9", "Sector 9A",
            "Sector 10", "Sector 10A", "Sector 12", "Sector 12A",
            "Sector 14", "Sector 15", "Sector 15 Part 1", "Sector 15 Part 2",
            # Sectors — Central Gurgaon
            "Sector 17", "Sector 17A", "Sector 18",
            "Sector 21", "Sector 22", "Sector 23",
            "Sector 24", "Sector 25", "Sector 27", "Sector 28", "Sector 29",
            # Sectors — South City / Sushant Lok belt
            "Sushant Lok 1", "Sushant Lok 2", "Sushant Lok 3",
            "South City 1", "South City 2", "Ardee City",
            # Sectors — Golf Course Road corridor
            "Sector 31", "Sector 33", "Sector 34", "Sector 35",
            "Sector 36", "Sector 37", "Sector 38", "Sector 39", "Sector 40",
            "Sector 41", "Sector 42", "Sector 43", "Sector 44", "Sector 45",
            "Sector 46", "Sector 47", "Sector 48", "Sector 49",
            # Sectors — Golf Course Extension / Sohna Road
            "Sector 50", "Sector 51", "Sector 52", "Sector 53",
            "Sector 54", "Sector 55", "Sector 56", "Sector 57",
            "Sector 58", "Sector 59", "Sector 60", "Sector 61",
            "Sector 62", "Sector 63", "Sector 64", "Sector 65",
            "Sector 66", "Sector 67", "Sector 68", "Sector 69", "Sector 70",
            # Sectors — New Gurgaon (Dwarka Expressway / NH-8 south)
            "Sector 71", "Sector 72", "Sector 73", "Sector 74", "Sector 75",
            "Sector 76", "Sector 77", "Sector 78", "Sector 79",
            "Sector 81", "Sector 82", "Sector 83", "Sector 84",
            "Sector 85", "Sector 86", "Sector 87", "Sector 88",
            "Sector 89", "Sector 90", "Sector 91", "Sector 92",
            "Sector 93", "Sector 94", "Sector 95", "Sector 95A",
            "Sector 98", "Sector 99", "Sector 99A",
            "Sector 100", "Sector 102", "Sector 103", "Sector 104",
            "Sector 105", "Sector 106", "Sector 108", "Sector 109",
            "Sector 110", "Sector 111", "Sector 112", "Sector 113",
            "Sector 114", "Sector 115",
            # Key corridors and areas
            "Golf Course Road", "Golf Course Extension Road",
            "Sohna Road", "MG Road", "Cyber City",
            "Dwarka Expressway", "NH-8",
            "Nirvana Country", "Palam Vihar", "Mayfield Gardens",
            "Udyog Vihar", "IMT Manesar", "Manesar",
            "Farrukhnagar", "Badshahpur", "Sohna",
            "Dhundahera", "Sector 23A", "Vatika City",
            # Premium / township areas
            "Emaar Palm Hills", "Emaar Palm Drive",
            "DLF New Town Heights", "DLF Skycourt",
            "M3M Woodshire", "M3M Golf Estate",
            "Sobha City", "Godrej Summit",
            "Tata Primanti", "Vatika India Next",
            "Experion Wind Song", "Ansal API Esencia",
            "Raheja Revanta", "Mahindra Aura",
            "BPTP Parklands", "Signature Global Orchard",
            "Smart World Gems", "AIPL Joy Street",
        ],
        "landmarks": [
            # Metro / transit
            "Near Metro Station", "Near HUDA City Centre Metro", "Near IFFCO Chowk Metro",
            "Near MG Road Metro", "Near Sikanderpur Metro", "Near Rapid Metro",
            "Near Dwarka Expressway", "Near NH-8",
            # Malls and commercial
            "Near DLF CyberHub", "Near Ambience Mall", "Near MGF Metropolitan Mall",
            "Near Sahara Mall", "Near Sector 29 Market", "Near Galleria Market",
            "Near Good Earth City Centre", "Near Omaxe Connaught Place",
            "Near AIPL Joy Street", "Near M3M Cosmopolitan",
            # Hospitals
            "Near Medanta Hospital", "Near Fortis Memorial Hospital",
            "Near Artemis Hospital", "Near Max Hospital",
            "Near Paras Hospital", "Near Cloudnine Hospital",
            # Schools and institutions
            "Near DPS Sector 45", "Near Amity International School",
            "Near Scottish High School", "Near GD Goenka School",
            "Near Shri Ram School", "Near Heritage School",
            # Parks, recreation, religious
            "Near Golf Course", "Near Tau Devi Lal Bio Diversity Park",
            "Near Sheetla Mata Mandir", "Near Kingdom of Dreams",
            "Near Leisure Valley Park", "Near Oyster Beach Water Park",
            # HUDA and civic
            "Near HUDA Market", "Near Subhash Chowk",
            "Near Rajiv Chowk", "Near Hero Honda Chowk",
            "Near Atul Kataria Chowk", "Near Sector 29 Bus Stand",
        ],
        "builders": [
            # Tier 1 — DLF, M3M, Godrej
            "DLF Limited", "M3M India", "Godrej Properties", "Sobha Limited",
            # Tier 2 — major national
            "Emaar India", "Vatika Group", "Experion Developers", "Ansal API",
            "Unitech Group", "Raheja Developers", "Tata Housing", "Mahindra Lifespaces",
            # Tier 3 — Gurgaon-focused
            "Signature Global", "Supertech Limited", "BPTP Limited", "Paras Buildtech",
            "AIPL", "Smart World", "Puri Construction", "Microtek Infrastructure",
            "GLS Infratech", "JMD Group", "Sare Group", "Orris Group",
            "Bestech Group", "IREO", "Hero Realty", "Mapsko Group",
            "Ashiana Homes", "Krish Group", "Ninex Group", "Vardhman Group",
        ],
        "rent_range": {
            "1bhk": (10000, 20000), "2bhk": (20000, 45000),
            "3bhk": (35000, 95000), "4bhk": (60000, 200000),
        },
        "buy_range": {
            "1bhk": (3500000, 6000000), "2bhk": (5500000, 15000000),
            "3bhk": (10000000, 30000000), "4bhk": (20000000, 60000000),
        },
        "daily_rate_range": (2000, 12000),
    },
}

# ── Cities used across generators ──────────────────────────────
CITIES = ["Gurgaon", "Delhi NCR"]

# ── Banks used across generators ───────────────────────────────
BANKS = ["SBI", "PNB", "Bank of Baroda", "Canara Bank", "HDFC Ltd", "ICICI Bank", "Union Bank", "Yes Bank"]

# ── Name pools ─────────────────────────────────────────────────
FIRST_NAMES_M = ["Arjun", "Vikram", "Rohit", "Amit", "Suresh", "Manish", "Deepak", "Rajesh", "Nikhil", "Karan", "Pranav", "Ankit", "Rahul", "Sanjay", "Pankaj"]
FIRST_NAMES_F = ["Priya", "Neha", "Anjali", "Pooja", "Shruti", "Swati", "Ritu", "Meera", "Divya", "Kavita", "Suman", "Rekha", "Nisha", "Arti", "Sneha"]
LAST_NAMES = ["Sharma", "Patel", "Kumar", "Singh", "Gupta", "Agarwal", "Joshi", "Reddy", "Verma", "Mishra", "Tiwari", "Yadav", "Chauhan", "Pandey", "Saxena", "Bhat", "Rao", "Nair", "Menon", "Iyer"]

# ── Professions ────────────────────────────────────────────────
PROFESSIONS = ["Software Engineer", "Product Manager", "Data Scientist", "Marketing Executive", "CA", "Doctor", "Lawyer", "Teacher", "Consultant", "Freelancer", "Business Owner", "Banker", "Architect", "Designer", "Content Writer"]

# ── Flatmates enums ────────────────────────────────────────────
FLATMATES_MODES = ["seeker", "room_poster", "co_hunter", "open_to_both"]
SLEEP_SCHEDULES = ["early_bird", "night_owl", "flexible"]
CLEANLINESS = ["minimal", "tidy", "spotless"]
FOOD_HABITS = ["vegetarian", "vegan", "non_vegetarian", "eggetarian", "no_preference"]
SMOKING_DRINKING = ["neither", "smoke_outside", "drink_occasionally", "both_fine"]
GUESTS_POLICIES = ["no_overnight_guests", "occasional_ok", "open_house"]
WORK_STYLES = ["wfh", "office", "hybrid"]

# ── Blog topics ─────────────────────────────────────────────────
BLOG_TOPICS = [
    {"title": "Top 10 Gated Communities in Gurgaon for Families", "slug": "top-gated-communities-gurgaon-families", "category": "neighborhoods", "tags": ["gurgaon", "apartment", "investment"]},
    {"title": "Understanding RERA: A First-Time Buyer's Guide", "slug": "understanding-rera-first-time-buyer-guide", "category": "legal-rera", "tags": ["rera", "first-time-buyer", "home-loan"]},
    {"title": "Golf Course Road vs Sohna Road: Where to Invest in 2026", "slug": "golf-course-road-vs-sohna-road-investment-2026", "category": "market-insights", "tags": ["gurgaon", "investment", "golf-course-road"]},
    {"title": "Vastu Tips for Your New Apartment", "slug": "vastu-tips-new-apartment", "category": "vastu-design", "tags": ["vastu", "apartment", "interior-design"]},
    {"title": "How to Negotiate Rent in Gurgaon: 7 Pro Tips", "slug": "negotiate-rent-gurgaon-pro-tips", "category": "rental-tips", "tags": ["rent-agreement", "gurgaon", "rental-tips"]},
    {"title": "The Complete Guide to PG Life in Gurgaon", "slug": "complete-guide-pg-life-gurgaon", "category": "rental-tips", "tags": ["gurgaon", "pg-flatmates", "rent-agreement"]},
    {"title": "Short Stays vs Hotels: Why 360 Stays is Changing Travel", "slug": "short-stays-vs-hotels-360-stays", "category": "market-insights", "tags": ["short-stay", "gurgaon", "investment"]},
    {"title": "What to Check Before Signing a Lease Agreement", "slug": "check-before-signing-lease-agreement", "category": "rental-tips", "tags": ["rent-agreement", "property-management", "legal-rera"]},
    {"title": "5 Emerging Sectors in Gurgaon for Budget Buyers", "slug": "emerging-sectors-gurgaon-budget-buyers", "category": "neighborhoods", "tags": ["gurgaon", "apartment", "first-time-buyer"]},
    {"title": "How 360 Virtual Tours Are Transforming Property Discovery", "slug": "360-virtual-tours-transforming-property-discovery", "category": "market-insights", "tags": ["gurgaon", "investment", "interior-design"]},
    {"title": "Dwarka Expressway: The Next Big Real Estate Corridor", "slug": "dwarka-expressway-next-big-corridor", "category": "market-insights", "tags": ["gurgaon", "dwarka-expressway", "investment"]},
    {"title": "Best Schools Near Golf Course Road for Your Kids", "slug": "best-schools-near-golf-course-road", "category": "neighborhoods", "tags": ["gurgaon", "golf-course-road", "families"]},
    {"title": "New Gurgaon vs Old Gurgaon: Where Should You Buy?", "slug": "new-gurgaon-vs-old-gurgaon", "category": "market-insights", "tags": ["gurgaon", "investment", "sector-81"]},
    {"title": "Flatmate vs PG: Which is Right for You in Gurgaon?", "slug": "flatmate-vs-pg-gurgaon-guide", "category": "rental-tips", "tags": ["gurgaon", "pg-flatmates", "flatmates"]},
    {"title": "Top 5 Affordable Sectors Under 50 Lakhs in Gurgaon", "slug": "affordable-sectors-under-50-lakhs-gurgaon", "category": "neighborhoods", "tags": ["gurgaon", "affordable", "first-time-buyer"]},
    {"title": "Cyber City to Sohna Road: A Commuter's Guide to Gurgaon", "slug": "cyber-city-to-sohna-road-commuter-guide", "category": "neighborhoods", "tags": ["gurgaon", "commute", "cyber-city"]},
    {"title": "Understanding Circle Rates in Gurugram 2025-26", "slug": "understanding-circle-rates-gurugram", "category": "legal-rera", "tags": ["gurgaon", "circle-rates", "legal-rera"]},
    {"title": "Rental Yield Comparison: Sector 49 vs Sector 65 vs Sector 82", "slug": "rental-yield-comparison-gurgaon-sectors", "category": "market-insights", "tags": ["gurgaon", "rental-yield", "investment"]},
    {"title": "Manesar Industrial Hub: Property Investment Opportunities", "slug": "manesar-property-investment-opportunities", "category": "market-insights", "tags": ["gurgaon", "manesar", "investment"]},
    {"title": "Vastu-Compliant Homes on Sohna Road: What to Look For", "slug": "vastu-compliant-homes-sohna-road", "category": "vastu-design", "tags": ["gurgaon", "sohna-road", "vastu"]},
]
