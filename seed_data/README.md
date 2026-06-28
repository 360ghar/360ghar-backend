# 360Ghar Data Seeding System

Three-category architecture for populating the 360Ghar database with realistic data across all modules (Real Estate, 360 Tours, Stays, Property Management, Flatmates, Data Hub, Blog, AI Agent).

## Categories

| Category | Directory | Source | Committed | Editable |
|----------|-----------|--------|-----------|----------|
| **1. Hardcoded** | `hardcoded/` | Team-curated (you) | Yes | Yes — JSON |
| **2. Seed** | `seed/` | Deterministic generated | Yes | Yes — JSON |
| **3. Generated** | `generated/` | Simulated activity | No (gitignored) | No |

### Category 1: Hardcoded
Team accounts, real property listings, amenity catalog, FAQs, pages, blog taxonomy, lifestyle catalogs. **Never overwritten by generators.**

### Category 2: Seed
Synthetic but realistic data across ALL modules: users, properties, tours, PM leases/rent/maintenance, bookings, blog posts, data hub (circle rates, RERA, auctions, zoning, bank rates), and more. Generated once, committed, editable.

### Category 3: Generated
Simulated user activity: swipes, matches, conversations, messages, visits, analytics, AI conversations, search history. Generated fresh each run from IDs in categories 1 & 2.

## Quick Start

```bash
# 1. Load all data (uses committed JSON — deterministic, recommended)
uv run python seed_data/01_load_all.py

# 2. Or load selectively
uv run python seed_data/01_load_all.py --only hardcoded,seed
uv run python seed_data/01_load_all.py --only hardcoded
uv run python seed_data/01_load_all.py --skip-media
uv run python seed_data/01_load_all.py --dry-run         # Validate schemas without DB writes

# 3. Only if needed: regenerate JSON from generators (overwrites committed files)
uv run python seed_data/01_load_all.py --regenerate
```

## Adding Your Data

### Team Accounts (hardcoded/users.json)
Edit the file to add your team members. Fill `supabase_user_id` after creating Supabase Auth users. The loader auto-generates placeholder IDs if needed.

### Real Properties (hardcoded/properties.json)
Add your actual property listings with real descriptions, addresses, and pricing. Reference the owner by email using `owner_ref`.

### Media Files
Place images in `seed/media/` following the folder structure:
```
seed/media/
├── avatars/          # user_01.webp, user_02.webp, ...
├── properties/       # prop_001/exterior.webp, prop_001/living_room.webp, ...
├── tours/            # tour_001_scene_01.webp, ...
├── blogs/            # blog_cover_01.webp, ...
├── documents/        # lease_agreement_sample.pdf, ...
└── floor_plans/      # floor_plan_01.webp, ...
```

The media loader uploads these to Cloudinary and resolves `media/` references in JSON to real Cloudinary URLs.

## Commands

| Command | Description |
|---------|-------------|
| `uv run python seed_data/01_load_all.py` | Load all data (uses committed JSON) |
| `uv run python seed_data/01_load_all.py --regenerate` | Re-generate JSON from generators, then load |
| `uv run python seed_data/01_load_all.py --only hardcoded` | Only team-curated data |
| `uv run python seed_data/01_load_all.py --only hardcoded,seed` | Skip generated activity |
| `uv run python seed_data/01_load_all.py --only media` | Upload media files only |
| `uv run python seed_data/01_load_all.py --dry-run` | Validate schemas without DB writes (exits non-zero on errors) |
| `uv run python seed_data/01_load_all.py --skip-media` | Skip media upload |
| `uv run python seed_data/02_clear_data.py --confirm` | Wipe seed data |
| `uv run python seed_data/02_clear_data.py --confirm --force` | Wipe seed data, skip Cloudinary cleanup |

## Module Coverage

| Module | Models | Hardcoded | Seed | Generated |
|--------|--------|-----------|------|-----------|
| Core (Real Estate) | User, Agent, Property, Amenity, Visit, Swipe | Users, Agents, Properties, Amenities | Users, Agents, Properties, Images, Visits | Swipes, Visits, Agent Interactions, Search History |
| 360 Stays | Booking | — | Bookings | — |
| 360 Tours | Tour, Scene, Hotspot, AIJob, MediaFile, FloorPlan, TourBranding, TourLocation | — | Tours, Scenes, Hotspots, FloorPlans, Branding, MediaFiles, AIJobs | Tour Analytics |
| Property Management | Lease, RentCharge, RentPayment, Expense, Maintenance, Document, Inspection, RentalApplication | — | All PM entities | — |
| Flatmates | UserMatch, Conversation, Message, Block, Report, ProfileView, SuperLike, MatchQnA | Lifestyle Catalogs | — | Matches, Conversations, Messages, Blocks, Reports, Profile Views, Super Likes, QnA |
| Blog | BlogPost, BlogCategory, BlogTag | Categories, Tags | Blog Posts | — |
| Data Hub | CircleRate, ReraProject, BankAuction, CourtAuction, Gazette, Zoning, Colony, BankRate, NeighbourhoodScore, etc. | — | All Data Hub entities | Auction Alerts |
| AI Agent | AIConversation, AIConversationMessage | — | — | AI Conversations |
| CMS | FAQ, Page, AppVersion, BugReport | FAQs, Pages, AppVersions | Bug Reports | — |

## ID Resolution

JSON files use natural keys (email, phone, name, title) as references. The loader resolves these to actual DB IDs at insert time via the shared `IDMap`.

Example: `owner_ref: "saksham1991999@gmail.com"` → resolved to `owner_id: 1` at load time.

## Regenerating Data

```bash
# Regenerate Category 2 (overwrites seed/*.json)
uv run python seed_data/generators/01_generate_seed_data.py

# Regenerate Category 3 (overwrites generated/*.json)
uv run python seed_data/generators/02_generate_activity.py

# With different random seed
uv run python -c "import importlib; importlib.import_module('seed_data.generators.02_generate_activity').main(seed=123)"
```

## Backward Compatibility

The existing `populate_data/` system is preserved and still works. This new system is a separate, more comprehensive replacement.
