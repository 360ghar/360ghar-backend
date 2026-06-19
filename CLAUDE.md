# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Platform Overview

360 Ghar is a unified real estate platform with six integrated modules:

- **360 Ghar Core**: Real estate marketplace for buying and renting properties with swipe-based discovery, property visits, and agent coordination (`/api/v1/properties`, `/swipes`, `/visits`, `/agents`)
- **360 Stays**: Short-stay booking platform for hotels, vacation rentals, and temporary accommodations (`/api/v1/bookings`)
- **360 Flatmates**: Flatmate/PG discovery with swipe-based matching, conversations, moderation, QnA, and visit scheduling (`/api/v1/flatmates`)
- **Property Management**: Comprehensive property management system for landlords and property managers (`/api/v1/pm/*`)
- **360 Virtual Tours**: Immersive 360° property tour platform with AI-powered hotspot generation and scene management (`/api/v1/tours`)
- **360 Data Hub**: Real estate data aggregation with bank auctions, circle rates, court auctions, gazette, jamabandi, RERA projects/complaints, zoning, and neighbourhood data (`/api/v1/data-hub`)

## Build and Development Commands

### Running the API
```bash
uv run python run.py                                                  # Primary (recommended) — uses uv's managed venv
uv run fastapi dev app/main.py --host 0.0.0.0 --port 3600             # Hot reload via FastAPI CLI
```

> **Note:** This project uses `uv` for dependency management. Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. **Always prefix commands with `uv run`** — running `python run.py` or `fastapi dev` directly uses the system Python which lacks project dependencies (e.g., `pgvector`) and will fail with `ModuleNotFoundError`.

### Testing
```bash
uv run pytest tests/ -v                      # All tests (using uv)
pytest tests/ -v                              # All tests
pytest tests/test_user_service.py -v         # Specific file
pytest tests/ -k "user" -v                   # By keyword
pytest tests/test_file.py::test_func -v      # Single test
pytest tests/ --cov=app --cov-report=html    # With coverage
```

### Data Population
```bash
# Using uv (recommended)
uv run python seed_data/01_load_all.py                          # Load all data (hardcoded + seed + generated)
uv run python seed_data/01_load_all.py --only hardcoded,seed    # Skip generated activity
uv run python seed_data/01_load_all.py --quick                  # Quick mode
uv run python seed_data/01_load_all.py --dry-run                 # Validate without writing

# Generate JSON files (usually done automatically by load_all.py)
uv run python seed_data/generators/01_generate_seed_data.py      # Regenerate Category 2 seed JSON
uv run python seed_data/generators/02_generate_activity.py       # Regenerate Category 3 activity JSON

# Optimize seed images (reduce Docker image size)
uv run python scripts/optimize_seed_images.py                    # Full run
uv run python scripts/optimize_seed_images.py --dry-run          # Preview only

# Clear all data
uv run python seed_data/02_clear_data.py --confirm               # Wipe all seeded data
```

> **⚠️ Data Safety**: `02_clear_data.py` is a **dev-only** script. It uses subquery-based FK mapping to only delete data linked to seed records (`WHERE is_seed_data = true` on users/agents/properties). Never run this or any destructive DB operation against production without explicit user confirmation. Real user data must never be deleted by seed scripts.

### Database
```bash
supabase db reset   # Reset local database
supabase db push    # Apply migrations
supabase db diff    # Check pending changes
```

### Docker
```bash
docker-compose up -d           # Start PostGIS 15, Redis 7, and API (hypercorn)
docker-compose up -d db redis  # Start only database services for local dev
```

### Environment Configuration
Copy `.env.example` to `.env` and configure. Key variable groups:
- **Database/Supabase**: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_*_KEY`
- **Redis/Cache**: `REDIS_URL`
- **AI Providers**: `PERPLEXITY_API_KEY`, `GLM_API_KEY`, `GOOGLE_API_KEY`
- **Notifications**: `EMAIL_*`, `SMS_*`, `ENABLE_NOTIF_SCHEDULER`
- **Vector Search**: `VECTOR_SYNC_ENABLED`, `GEMINI_EMBED_MODEL`
- **Blog Auto-Publish**: `AUTO_BLOG_ENABLED`, `AUTO_BLOG_CRON`
- **Serverless/Scale-to-Zero**: `SERVERLESS_ENABLED`
- **CORS Override**: `CORS_ORIGINS_STR` (comma-separated, overrides default `CORS_ORIGINS` list)

### CI/CD Pipeline
GitHub Actions (`.github/workflows/tests.yml`) runs on push/PR to `main`/`develop`:
1. **test** — PostGIS + Redis services, `pytest` with `--cov-fail-under=90`, Codecov upload
2. **lint** — `ruff check app/` and `mypy app/`

### Deployment
- **Railway**: `railway.toml` with healthcheck on `/health`, `ON_FAILURE` restart policy
- **Docker**: `Dockerfile` uses `python:3.12-slim` with `uv sync` entry point

## Architecture Overview

### Layered Structure
```
app/
├── api/
│   ├── api_v1/endpoints/   # REST endpoints (thin controllers; flatmates_admin.py for moderation)
│   ├── api_v1/dependencies/ # Shared auth dependencies (get_current_user, get_current_agent, etc.)
│   └── share.py            # Social share preview endpoints
├── services/               # Async business logic (main logic layer)
│   ├── ai/                 # AI provider factory (gemini, glm) + vastu analyzer
│   │   ├── providers/      # GeminiProvider, GLMProvider (httpx + tenacity retries)
│   │   └── vastu/          # Vastu analyzer, prompts, schemas
│   ├── ai_agent/           # Pydantic AI agent (agent_service, tool_bridge, conversation_store, system_prompt)
│   ├── blog_service/       # Blog content generation (generator.py)
│   ├── data_hub/           # 15 scraper modules (bank_auctions, circle_rates, rera_projects, etc.)
│   ├── flatmates/          # Flatmates service package (conversations, helpers, interactions, matching, moderation, profiles, visits)
│   ├── push_notification.py # FCM push dispatch for flatmates events
│   ├── notification_config.py # Notification type registry (channel, priority, frequency caps)
│   ├── notifications/     # Notification package (crud, fcm, helpers, push)
│   ├── notification_dispatcher.py # Multi-channel dispatch (push/email/sms/in-app)
│   ├── oauth_token_store.py # OAuth token/code storage via CacheManager
│   ├── storage_paths.py    # Upload path generation + sanitization
│   ├── image_processing.py # Thumbnail generation, EXIF extraction (Pillow)
│   ├── custom_domain.py    # Custom domain DNS verification for tours
│   └── infrastructure/     # Composition root wiring (lifespan, middleware, errors, MCP app construction, routing, request_context, scheduler)
├── repositories/           # Complex database queries (BaseRepository, PropertyRepository, PropertyQueryBuilder)
├── models/                 # SQLAlchemy ORM models
│   └── social.py           # UserMatch, UserConversation, UserMessage, UserBlock, UserReport, AppCatalog
├── schemas/                # Pydantic request/response validation
│   ├── flatmates.py        # FlatmatesProfile, SwipeRequest, ConversationSummary, etc.
│   └── flatmates_admin.py  # Admin flatmates response serialization helpers
├── mcp/                    # MCP servers (user_server, admin package, chatgpt widgets)
│   ├── tool_ops/           # Shared tool business logic (properties, leases, rent, maintenance, bookings, dashboard)
│   └── chatgpt/            # ChatGPT-specific tools (discovery, visits, PM split modules) + response formatter
├── core/                   # Config, auth, database, exceptions, logging, websocket, SSE
│   ├── cache/              # Cache subsystem (memory + Redis backends, decorators, PropertyCacheManager)
│   ├── http.py             # Shared httpx.AsyncClient singletons (scraper, blog, general)
│   ├── constants.py        # Vision provider defaults, valid providers
│   ├── db_resilience.py    # Transient DB error detection + retry-with-rollback
│   ├── sse.py              # SSE event bus (subscribe/emit/keepalive for real-time flatmates events)
│   ├── logging.py          # Structured logging, RequestIDFilter, request-id context vars
│   └── utils.py            # UTC helpers, timezone awareness
├── middleware/             # Rate limiting (sliding window), security headers, request ID, request logging, trailing slash
├── config/                 # Re-export package (settings, constants) — canonical import location
├── modules/                # (Placeholder for future physical domain entrypoints)
├── shared/                 # (Placeholder for future physical shared packages)
├── utils/                  # Shared utilities (distance, validators)
└── vector/                 # Vector embedding store, sync, backfill (pgvector)
```

### Key Patterns

**Async-First**: All database operations and services use `async/await`. Services inject `AsyncSession` via FastAPI dependencies.

**Authentication Flow**: Client authenticates directly with Supabase Auth → bearer access token → `get_current_user` dependency verifies JWT → local user sync

**Geospatial Search**: PostGIS `ST_DWithin` for radius-based property search, `ST_Distance` for sorting by proximity.

**Full-Text Search**: PostgreSQL `ts_vector` column (`__ts_vector__`) on properties table.

**Semantic Search**: Hybrid vector + text scoring via `property_embeddings` table (pgvector).

**Serverless/Scale-to-Zero**: When `SERVERLESS_ENABLED=True`, the app uses `NullPool` for both main and background DB engines (no persistent connections), skips in-process schedulers, and uses in-memory cache fallback. PgBouncer handles server-side pooling. Trade-off: ~10-50ms added latency per request.

**SSE Real-Time Events**: `SSEEventBus` in `app/core/sse.py` provides per-user pub/sub via `subscribe`/`emit`/`unsubscribe`. Service methods call `await sse_bus.emit(user_id, event_dict)` after DB commit. The SSE endpoint (`GET /api/v1/flatmates/sse`) consumes from the queue with 30s keepalive. Non-blocking: drops oldest event on queue full, periodically reaps dead queues. Event types: `new_match`, `new_message`, `conversation_updated`, `visit_updated`, `listing_status_changed`, `new_notification`.

**DB Session Hygiene for Streaming**: SSE and other streaming endpoints release the main-pool DB session before streaming and use a background-pool session (`get_bg_db`) for tool calls.

**Graceful Shutdown**: On app shutdown, `app/infrastructure/lifespan.py` shuts down the shared `AsyncIOScheduler`, closes cached AI provider HTTP clients, shuts down the notification thread pool, closes all shared httpx clients (scraper, blog, general + FCM + SMS), disposes Supabase sync/async HTTP clients, and disposes both DB engines.

**Overlapping Bookings Allowed (business rule)**: The same property can be shown to and booked by multiple people for the same or overlapping dates. Do NOT add date-overlap conflict checks, double-booking guards, or DB exclusion constraints on bookings. `check_availability` in `app/services/booking.py` only validates that the property exists and that the guest count fits `max_occupancy`.

### Service Layer Pattern
```python
class PropertyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_properties(self, filters: dict) -> list[Property]:
        # Business logic here
```

### Dependency Injection
```python
@router.get("/properties/")
async def get_properties(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional)
):
    return await property_service.search(db, current_user)
```

## Key Files

| Purpose | Location |
|---------|----------|
| App factory (thin composition root) | `app/factory.py` |
| Infrastructure wiring | `app/infrastructure/` (lifespan, middleware, errors, mcp, routing, request_context) |
| Shared scheduler | `app/infrastructure/scheduler.py` |
| Shared HTTP clients | `app/core/http.py` |
| Main entry | `app/main.py` |
| API router | `app/api/api_v1/api.py` |
| Database config | `app/core/database.py` |
| Auth logic | `app/core/auth.py` |
| Auth dependencies | `app/api/api_v1/dependencies/auth.py` |
| Custom exceptions | `app/core/exceptions.py` |
| Settings | `app/core/config.py` |
| Config re-exports | `app/config/settings.py`, `app/config/constants.py` |
| App constants | `app/core/constants.py` |
| Core utilities | `app/core/utils.py` |
| SSE event bus | `app/core/sse.py` |
| Logging + request ID | `app/core/logging.py` |
| DB resilience | `app/core/db_resilience.py` |
| WebSocket manager | `app/core/websocket.py` |
| Cache subsystem | `app/core/cache/` |
| Migrations | `supabase/migrations/` |
| Vector embeddings | `app/vector/` |
| Shared utilities | `app/utils/` |
| Data hub scrapers | `app/services/data_hub/` |
| Data hub scheduler | `app/services/data_hub_scheduler.py` |
| AI agent service | `app/services/ai_agent/agent_service.py` |
| AI agent tool bridge | `app/services/ai_agent/tool_bridge.py` |
| AI agent conversation store | `app/services/ai_agent/conversation_store.py` |
| AI agent system prompt | `app/services/ai_agent/system_prompt.py` |
| Blog auto-publish | `app/services/blog_auto_publish.py`, `app/services/blog_auto_publish_scheduler.py` |
| Blog content generator | `app/services/blog_service/generator.py` |
| Notification config | `app/services/notification_config.py` |
| Notification dispatcher | `app/services/notification_dispatcher.py` |
| Full notification service | `app/services/notifications/` (crud, fcm, helpers, push) |
| Notification helpers (shutdown_executor) | `app/services/notifications/helpers.py` |
| Push notification dispatch | `app/services/push_notification.py` |
| Notification scheduler | `app/services/notification_scheduler.py` |
| Vector sync scheduler | `app/services/vector_sync_scheduler.py` |
| Vastu AI analyzer | `app/services/ai/vastu/analyzer.py` |
| AI agent chat endpoint | `app/api/api_v1/endpoints/agent_chat.py` |
| Tour AI processing | `app/services/tour_ai.py` |
| Tour service | `app/services/tour.py` |
| Email service | `app/services/email.py` |
| SMS service | `app/services/sms.py` |
| Storage service | `app/services/storage.py` |
| Storage path generation | `app/services/storage_paths.py` |
| Image processing | `app/services/image_processing.py` |
| Custom domain service | `app/services/custom_domain.py` |
| Flatmates service | `app/services/flatmates/` (conversations, helpers, interactions, matching, moderation, profiles, visits) |
| Flatmates admin endpoint | `app/api/api_v1/endpoints/flatmates_admin.py` |
| Flatmates admin schemas | `app/schemas/flatmates_admin.py` |
| Agent service | `app/services/agent.py` |
| Data seeding system | `seed_data/01_load_all.py`, `seed_data/generators/`, `seed_data/loaders/` |
| OAuth token store | `app/services/oauth_token_store.py` |
| PM authorization | `app/services/pm_authz.py` |
| Social share previews | `app/api/share.py` |
| WebSocket endpoints | `app/api/api_v1/endpoints/websocket.py` |
| Social models | `app/models/social.py` |
| Data hub model | `app/models/data_hub.py` |
| Domain modules (reserved) | `app/modules/` |
| Shared contracts (reserved) | `app/shared/` |

**Background schedulers** (all register jobs on a single shared `AsyncIOScheduler` from `app/infrastructure/scheduler.py`, wired in `app/infrastructure/lifespan.py` startup; graceful shutdown via `shutdown_scheduler()`):
- Blog auto-publish scheduler (`app/services/blog_auto_publish_scheduler.py`)
- Notification scheduler (`app/services/notification_scheduler.py`)
- Vector sync scheduler (`app/services/vector_sync_scheduler.py`)
- Data hub scheduler (`app/services/data_hub_scheduler.py`)

> In serverless mode (`SERVERLESS_ENABLED=True`), all schedulers are skipped to allow scale-to-zero; move cron work to Railway cron jobs.

**Shared HTTP clients** (`app/core/http.py`): Three domain-specific `httpx.AsyncClient` singletons for connection reuse. Do not create ephemeral `async with httpx.AsyncClient()` per request — use the shared clients with per-request `timeout=` overrides:

| Client | Default timeout | Used by |
|--------|----------------|---------|
| `get_scraper_client()` | 30s | Data hub scrapers, jamabandi, gazette, neighbourhood |
| `get_blog_client()` | 120s | Perplexity blog generation, SerpAPI image search |
| `get_general_client()` | 30s | Image downloads, geocoding, OAuth metadata, image gen |

> Per-request `timeout=` overrides the client default (e.g., `client.get(url, timeout=180.0)` for image gen's 180s timeout).

## Coding Conventions

- **Python 3.10+**, FastAPI, SQLAlchemy 2.x async, Pydantic v2
- **snake_case** for modules/functions/variables; **PascalCase** for classes
- Full type hints everywhere
- Custom exceptions from `app/core/exceptions.py` (e.g., `UserNotFoundException`)
- Pydantic schemas with `Config.from_attributes = True` for ORM mode
- Use `X | None` for nullable fields (not `Optional[X]`); `list[X]` and `dict[K, V]` (not `List`, `Dict`); `from __future__ import annotations` at module top
- Validation with `@field_validator` decorators

### Ruff Lint Rules (enforced in CI)

All code must pass `uv run ruff check app/` before commit. The CI pipeline (`lint` job) runs ruff and will fail on any violation. Key rules to follow:

**Import style (I001, UP035, F401, E402):**
- Always add `from __future__ import annotations` as the first import in every `.py` file (after any module docstring). This makes forward references work and is required by ruff.
- Use `list`, `dict`, `set`, `tuple`, `type` instead of `typing.List`, `typing.Dict`, `typing.Set`, `typing.Tuple`, `typing.Type` (ruff UP035/UP006).
- Import `Callable`, `Awaitable`, `AsyncIterator`, `Sequence` from `collections.abc`, not `typing` (ruff UP035).
- Remove unused imports immediately — ruff F401 is enforced. Never leave "just in case" imports.
- All imports must be at the top of the file before any non-import code (E402). If a circular import requires a late import, add `# noqa: E402` with a comment explaining why.

**Type annotations (UP045, UP006, UP007, UP037):**
- Use `X | None` instead of `Optional[X]` everywhere (UP045).
- Use `X | Y` instead of `Union[X, Y]` (UP007).
- Use `list[X]` instead of `List[X]`, `dict[K, V]` instead of `Dict[K, V]`, etc. (UP006).
- Remove unnecessary quotes in type annotations, e.g. `"User"` → `User` (UP037).
- For forward references in models, add `from __future__ import annotations` and import the type under `TYPE_CHECKING`:
  ```python
  from __future__ import annotations
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from app.models.users import User
  ```

**Exception handling (B904):**
- Within `except` blocks, always chain exceptions with `from e` or `from None` (B904). Use `from None` when logging the original exception and raising a new user-facing one (suppresses noisy traceback chaining). Use `from e` when the original exception provides useful debugging context.

**Equality comparisons (E712):**
- Never compare booleans with `== True` or `== False`. Use the column directly: `Model.is_active` instead of `Model.is_active == True`, `~Model.is_active` or `not_(Model.is_active)` instead of `Model.is_active == False`.

**Variable naming (E741):**
- Never use single-letter `l` as a variable name — it is visually indistinguishable from `1`. Use descriptive names like `lease`, `line`, `link`, etc.

**Unused variables (F841):**
- Never assign to a variable and not use it. If you need to ignore a return value, use `_` or `_name`.

**Whitespace (W291, W292, W293):**
- No trailing whitespace on any line (W291).
- No whitespace on blank lines (W293).
- Every file must end with a newline (W292).

**Other enforced rules:**
- `zip()` must use `strict=` parameter (B905): `zip(a, b, strict=True)`.
- Use set comprehensions instead of generator expressions passed to `set()` (C401).
- Remove `f` prefix from f-strings that have no placeholders (F541).
- Do not redefine a name that is already imported (F811).

## Dependency & Documentation Policy

- **Always use latest stable versions**: When adding or upgrading dependencies, AI models, SDKs, API versions, or protocol versions, always research and use the latest stable release. Never pin to outdated versions, model names, API signatures, or protocol versions based on cached/training knowledge — these change frequently and are often wrong if not verified.
- **Research before integrating**: Before implementing any 3rd party integration (APIs, SDKs, libraries, AI models, protocols), look up the current official documentation and latest version. Do not rely on training data alone — docs, APIs, model names, and SDKs change frequently. Always verify from official sources.
- **Use Context7 MCP or web search**: Use the `context7` MCP tools (`resolve-library-id` + `query-docs`) or `WebSearch`/`WebFetch`/`google_search` to retrieve up-to-date documentation, latest version numbers, API references, and code examples for any library, service, model, or SDK being used.
- **Verify everything latest**: When referencing package versions, AI/LLM model names, API endpoints or signatures, SDK methods, protocol versions (e.g., MCP protocol version), or any external service reference, always confirm the latest from official sources (docs sites, GitHub releases, PyPI, npm, official changelogs). Never assume a version or API shape from memory.
- **Verify compatibility**: Confirm that new dependencies are compatible with the project's Python 3.10+ requirement and existing stack (FastAPI, SQLAlchemy 2.x async, Pydantic v2).
- **Check changelogs for breaking changes**: When upgrading a dependency, review its changelog/migration guide to avoid breaking changes.
- **Stay current with ecosystem**: Periodically check for newer versions of key dependencies (FastAPI, SQLAlchemy, Pydantic, Supabase, FastMCP, etc.) and update when safe. Prefer latest docs and examples over outdated tutorials or blog posts.

## Database Models

**Core entities**: User, Property, Agent, AgentInteraction, Booking, Visit, UserSwipe, Amenity, BugReport, Page, AppVersion, FAQ

**Blog entities**: BlogPost (with SEO fields: meta_title, meta_description, focus_keyword, canonical_url, og_image_url, reading_time_minutes, word_count, published_at, sources, seo_metadata), BlogCategory, BlogTag, BlogPostCategory, BlogPostTag

**Social entities**: UserMatch, UserConversation, UserMessage, UserBlock, UserReport, AppCatalog, MatchQnAAnswer (enum-enforced string columns via `EnumStringType` with DB-level `CHECK` constraints)

**360 Virtual Tour entities**: Tour, Scene, Hotspot, TourAnalyticsEvent, AIJob, MediaFile, UserSession, TourLocation, SearchIndex, CacheEntry, FloorPlan, TourBranding, CustomDomain, VideoMetadata

**Property Management entities**: Lease (with termination_date, termination_reason), RentalApplication, RentalApplicationForm, RentCharge, RentPayment, Expense, MaintenanceRequest, Document, InspectionChecklist

**AI entities**: AIConversation, AIConversationMessage

**Data Hub entities**: BankAuction, CircleRate, CourtAuction, GazetteNotification, JamabandiCache, ReraProject, ReraComplaint, ZoningData, ColonyApproval, NeighbourhoodScore, BankRate, AuctionAlert, ScraperRun

**Key relationships**:
- User → Properties (as owner), Swipes, Visits, Bookings, Tours, Matches, Conversations, Messages, Blocks, Reports
- Property → Images, Amenities (M2M via PropertyAmenity), Visits, Bookings
- Agent → Users (1:many), Visits, AgentInteractions
- Property (managed) → Leases, Tenants, Rent, Maintenance, Documents
- UserMatch → User (M:M), Property (context)
- UserConversation → User (M:M), Messages, Property (context)

**Enums** (in `app/models/enums.py`):
- PropertyType: house, apartment, builder_floor, room, villa, plot, condo, penthouse, studio, loft, pg, flatmate, office, shop, warehouse
- PropertyPurpose: buy, rent, short_stay
- PropertyStatus: available, sold, rented, under_offer, maintenance
- PaymentStatus: pending, partial, paid, refunded, failed
- BookingStatus: pending, confirmed, checked_in, checked_out, cancelled, completed
- VisitStatus: scheduled, confirmed, completed, cancelled, rescheduled
- VisitContext: property_tour, flatmate_meet
- FlatmatesMode: room_poster, seeker, co_hunter, open_to_both
- FlatmatesProfileStatus: draft, pending_review, active, paused
- SwipeTargetType: property, user
- SwipeAction: pass, like, super_like
- ConversationSource: listing_interest, profile_match
- ConversationStatus: active, archived, blocked, closed
- UserMatchStatus: active, unmatched, blocked
- MessageType: text, image, system, visit_request
- UserReportReason: spam, fake_profile, abuse, inappropriate, other
- UserReportStatus: open, reviewed, dismissed, actioned
- ListingGenderPreference: any, male, female
- ListingSharingType: private_room, shared_room
- LeaseStatus: draft, pending_signature, active, expiring_soon, expired, terminated, renewed
- ManagedPropertyStatus: draft, active, archived
- TenantStatus: applicant, approved, active, notice_period, vacated, rejected
- RentChargeStatus: pending, partial, paid, overdue, waived
- ExpenseCategory: maintenance, repairs, insurance, property_tax, hoa, utilities, marketing, legal, other
- MaintenanceCategory: plumbing, electrical, hvac, appliance, structural, pest_control, cleaning, other
- MaintenanceUrgency: emergency, high, medium, low
- MaintenanceRequestStatus: open, in_review, work_order_created, resolved, closed
- WorkOrderStatus: created, assigned, in_progress, completed, closed, cancelled
- DocumentType: lease_agreement, id_proof, address_proof, income_proof, inspection_report, receipt, invoice, property_deed, insurance_policy, other
- InspectionType: move_in, move_out, routine
- TourStatus: draft, published, archived
- TourVisibility: private, unlisted, public
- HotspotType: navigation, info, audio, video, link, custom
- BugType: ui_bug, functionality_bug, performance_issue, crash, feature_request, other
- BugSeverity: low, medium, high, critical
- BugStatus: open, in_progress, resolved, closed
- PageFormat: html, markdown, json
- ImageCategory: room, hall, kitchen, bathroom, balcony, terrace, garden, parking, entrance, exterior, interior, others, floor_plan
- ScraperStatus: running, success, partial, failed
- AuctionSource: sarfaesi, ibapi, mstc, drt, ecourts
- GazetteType: land_acquisition, rate_revision, policy, clu_change
- ComplaintNature: delay, quality, refund, compensation, other
- UserRole: user, agent, admin
- AgentType: general, specialist, senior
- ExperienceLevel: beginner, intermediate, expert
- `PG_FLATMATE_TYPES` constant: `{PropertyType.pg, PropertyType.flatmate}`
- AIJobStatus: pending, processing, completed, failed, cancelled
- AIJobType: scene_analysis, hotspot_generation, floor_plan_processing
- CustomDomainVerificationStatus: pending, verified, failed
- CustomDomainSSLStatus: none, pending, active, failed
- AgentInteractionType: chat, call, email
- ListingModerationStatus: pending_review, live, rejected
- ModerationAction: approve, reject, request_edit
- ReportAction: dismiss, warn_user, suspend_user, escalate

## Test Structure

```
tests/
├── api/                    # Endpoint integration tests
├── unit/
│   ├── api/                # Endpoint unit tests (agent chat, flatmates admin)
│   ├── app/                # App composition tests (test_app_composition.py)
│   ├── core/               # Auth, config, cache, exceptions, logging, utils, websocket, db_resilience, constants
│   ├── models/             # Model/enum tests (blog, booking, data_hub, property, social, tour, user)
│   ├── schemas/            # Schema validation tests (ai_agent, blog, booking, common, flatmates, property, user, visit)
│   ├── services/           # Service layer unit tests (agent, blog, booking, notification, pm, property, storage, swipe, tour, user, visit)
│   │   ├── ai/             # AI provider tests
│   │   ├── ai_agent/       # AI agent service tests
│   │   └── pm/             # PM service tests
│   ├── mcp/                # MCP server tests (apps_sdk, errors, tool registration, PM tools, user_tools)
│   ├── repositories/       # Repository tests (base, property, query builder)
│   └── utils/              # Utility tests (distance, validators)
├── integration/            # Full-stack DB integration tests (PostGIS, FTS, property search)
│   └── services/           # Integration service tests
├── e2e/                    # End-to-end flow tests (booking, PM lifecycle, property listing, user registration)
├── pm/                     # Property management authz + rent tests
├── middleware/             # Middleware tests (rate limit, security, trailing slash)
└── fixtures/               # Shared fixtures (auth, common, data, factories, mocks)
```

Run with coverage: `pytest tests/ --cov=app --cov-report=html`
Dev dependencies (pytest, ruff, mypy) are in the `dev` optional group: `uv sync --extra dev`

## Security

- Supabase JWT auth via `get_current_user` dependency
- Phone as primary identifier
- Role-based access: user, agent, admin
- Backend does not provide `/api/v1/auth/*` user-session endpoints; clients own login/refresh/logout via Supabase SDK
- Account deletion: `delete_user_account` in `app/services/user.py` hard-deletes the Supabase Auth user, anonymizes all PII, and soft-deletes the local row. Two routes expose it: **`DELETE /api/v1/users/me`** (canonical, returns `MessageResponse`) and **`POST /api/v1/auth/delete-account`** (alternate for mobile clients, returns 204). There is no `/users/me/delete` route.
- Rate limiting: 500 req/min global per IP (sliding window via `app/middleware/rate_limit.py`). Tighter per-route limits applied via `EndpointRateLimiter` on sensitive endpoints (e.g. 60 req/min for the public identifier-status probe). SSE streaming endpoints are exempt (held-open connections would otherwise consume a client's per-IP budget).
- Input validation via Pydantic schemas
- API key validation via `VALID_API_KEYS` setting
- OAuth 2.1 token storage via CacheManager (Redis/memory backends, `app/services/oauth_token_store.py`)
- FCM push notifications via Google service account credentials (`app/services/push_notification.py`)
- Security headers middleware (`app/middleware/security.py`): X-Content-Type-Options, X-Frame-Options, CSP, HSTS
- Request ID middleware for distributed tracing (`app/middleware/security.py`)
- Request logging middleware for all routes including MCP (`app/middleware/security.py`)
- Sentry integration for error tracking and performance monitoring (`send_default_pii=False`)
- Request ID context var properly reset in `finally` block via `reset_request_id(token)` in `RequestIDMiddleware`

## Data Safety

### Destructive Operations Policy

- **Never delete real user data**: All destructive database operations must be reviewed with the user before execution. The `02_clear_data.py` script is the only tool that performs bulk deletions, and it respects `is_seed_data` boundaries.
- **Seed data clearance is selective**: `02_clear_data.py` filters by `WHERE is_seed_data = true` on `users`, `agents`, and `properties`. Child records (PropertyImage, Visit, Booking, BlogPost, Tour, PM entities, social data) are deleted via subquery joins to their seed parents — never via bare `DELETE FROM`.
- **Real data protection**: Tables without `is_seed_data` column are only touched when their FK parent is a confirmed seed record. Real users, properties, agents, and their child records are never deleted by seed scripts.
- **Dev-only scripts**: Scripts in `seed_data/` are designed for local development. Never run them against a production database.

### `is_seed_data` Flag

The `is_seed_data` boolean column (default `false`) exists on:
- `users` — marks seed/demo user accounts
- `agents` — marks seed/demo agent profiles
- `properties` — marks seed/demo property listings

Child entities (PropertyImage, Visit, Booking, Tour, BlogPost, PM entities, social records, data hub records) do **not** have their own `is_seed_data` column — they are identified as "seed" via FK joins to their parent. When adding a new seeded model, either add `is_seed_data` or ensure FK cascade to an existing seeded parent.

### Seed Data Lifecycle

1. **Generate**: `seed_data/generators/` produce deterministic JSON files with `random.seed(42)`
2. **Load**: `seed_data/loaders/` insert data into the database, setting `is_seed_data = true` on User/Agent/Property records
3. **Media**: `seed_data/loaders/05_media_loader.py` uploads images to Cloudinary using `cloudinary_service`
4. **Clear**: `02_clear_data.py` removes seed data via subquery-based FK mapping, preserving real (non-seed) records

### Cloudinary Upload Path Conventions

| Content Type | StorageFolder | Cloudinary Folder |
|-------------|---------------|-------------------|
| User avatars | `AVATAR` | `360ghar/avatars/{user_id}` |
| Property images | `PROPERTY_IMAGE` | `360ghar/properties/{property_id}` |
| Property videos | `PROPERTY_VIDEO` | `360ghar/properties/{property_id}/videos` |
| Blog covers | `BLOG_COVER` | `360ghar/blog-covers` |
| Tour assets | `TOUR_*` / `SCENE_*` | `360ghar/tours/{tour_id}/...` |
| Documents | `DOCUMENT_*` | `360ghar/documents/{type}` |
| Agent avatars | `AGENT_AVATAR` | `360ghar/agents/{agent_id}/avatars` |
| General uploads | `GENERIC_UPLOAD` | `360ghar/uploads/{user_id}` |

All media uploads use the shared `httpx` clients from `app/core/http.py` for outbound HTTP calls. Image files are optimized via `optimize_for_web()` from `app/services/image_processing.py` before upload.

## API Documentation

When running locally:
- Swagger UI: http://localhost:3600/api/v1/docs
- ReDoc: http://localhost:3600/api/v1/redoc
- OpenAPI YAML: http://localhost:3600/api/v1/openapi.yaml
- Health: http://localhost:3600/health
- WebSocket (AI jobs): `ws://localhost:3600/ws/jobs/{job_id}?token=...`
- WebSocket (notifications): `ws://localhost:3600/ws/notifications?token=...`
- AI Agent chat (auth): `POST /api/v1/agent/chat`
- AI Agent chat (guest): `POST /api/v1/agent/chat-public`
- Flatmates SSE: `GET /api/v1/flatmates/sse` (real-time event stream for authenticated users)

## MCP Server

360Ghar exposes Model Context Protocol (MCP) servers compatible with **any MCP client** — ChatGPT Apps, Claude Desktop, Cursor, VS Code Copilot, Gemini, MCPJam, and all MCP-compliant hosts. Authentication uses OAuth 2.1 with PKCE.

### Server Architecture

| Endpoint | Server | Purpose |
|----------|--------|---------|
| `/mcp` | User MCP (`ghar360-user`) | End-user tools for owners, tenants, property seekers, and guests |
| `/mcp-admin` | Admin MCP (`ghar360-admin`) | Administrative tools for agents and platform admins |

Both servers use `AppsSDKFastMCP` (extends FastMCP 3.0.1) with OAuth 2.1 + PKCE and share authorization endpoints at `/mcp/oauth/*`.

### Protocol and Transport

- **MCP protocol version**: `2025-11-25`
- **Transport**: Streamable HTTP (stateless, binary JSON-RPC over HTTP) — not SSE
- **Framework**: FastMCP 3.0.1 via `AppsSDKFastMCP` (`app/mcp/apps_sdk.py`)
- **Experimental capability**: `io.modelcontextprotocol/ui` advertised in initialization options — signals support for interactive HTML widget resources to all MCP hosts

### Universal Client Support

A single server URL serves all MCP clients with no per-client adapters:

- **Dual-metadata strategy**: `build_widget_tool_meta()` in `app/mcp/apps_sdk.py` emits both standard MCP keys (`ui.resourceUri`, `ui.visibility`) and OpenAI-compatible aliases (`openai/outputTemplate`, `openai/widgetAccessible`, `openai/toolInvocation/*`). Widget resources are similarly registered with both standard and OpenAI metadata keys.
- **Bridge runtime detection**: The widget bridge (`chatgpt-widgets/src/utils/bridge.ts`) detects the host at module load — `window.openai` present means OpenAI host; iframe (`window.parent !== window`) means MCP Apps host (JSON-RPC postMessage); else standalone. All widgets work without per-widget changes.
- **OAuth discovery**: Full RFC 9728 / RFC 8414 well-known metadata enables any OAuth 2.1 client to discover the authorization server and register dynamically via `/mcp/oauth/register`.

### User MCP Tools (`/mcp`)

**Discovery Tools** (prefix: `discovery_*`):
- `discovery_search` - Search properties with filters (guest)
- `discovery_property_get` - Get full property details (guest)
- `discovery_feed` - Get discovery feed for swiping (guest)
- `discovery_amenities` - List available amenities (guest)
- `discovery_swipe` - Record like/pass on property (auth)
- `discovery_shortlist` - Get liked properties (auth)
- `discovery_recommendations` - Get AI recommendations (auth)

**Visit Tools** (prefix: `visits_*`):
- `visits_schedule` - Schedule a property visit (auth)
- `visits_list` - List user's visits (auth)
- `visits_get` - Get visit details (auth)
- `visits_cancel` - Cancel a scheduled visit (auth)

**Owner Tools** (prefix: `owner_*`):
- `owner_properties_list` - List owned properties
- `owner_properties_create` - Create new property listing
- `owner_properties_get` - Get property details
- `owner_properties_update` - Update property
- `owner_properties_toggle_availability` - Toggle availability status
- `owner_dashboard_overview` - Get portfolio dashboard with analytics
- `owner_leases_list` - List property leases
- `owner_leases_get` - Get lease details
- `owner_leases_terminate` - Terminate a lease
- `owner_rent_status` - View rent collection status
- `owner_rent_record_payment` - Record a rent payment
- `owner_rent_history` - View payment history
- `owner_maintenance_list` - List maintenance requests
- `owner_maintenance_update` - Update maintenance request status

**Tenant Tools** (prefix: `tenant_*`):
- `tenant_lease_current` - View current lease
- `tenant_rent_dues` - View outstanding rent dues
- `tenant_rent_history` - View rent payment history
- `tenant_maintenance_create` - Submit maintenance request
- `tenant_maintenance_list` - List maintenance requests

**Booking Tools** (prefix: `bookings_*`):
- `bookings_create` - Book a property
- `bookings_list` - List user bookings
- `bookings_get` - Get booking details
- `bookings_cancel` - Cancel a booking
- `bookings_check_availability` - Check property availability
- `bookings_get_pricing` - Get pricing information

**System Tools**:
- `user_system_status` - Check auth status and available features

### Admin MCP Tools (`/mcp-admin`)

**Agent Tools** (prefix: `agent_*`):
- `agent_properties_list` - List properties in agent's portfolio
- `agent_properties_get` - Get detailed property info
- `agent_properties_create_for_owner` - Create property for an owner
- `agent_properties_verify` - Verify/approve property listing
- `agent_leases_list` - List all leases
- `agent_leases_create` - Create new lease agreement
- `agent_leases_terminate` - Terminate a lease
- `agent_rent_list_due` - List overdue rent payments
- `agent_rent_record_payment` - Record rent payment
- `agent_maintenance_list` - List maintenance requests
- `agent_maintenance_update_status` - Update maintenance status
- `agent_bookings_list_all` - List all bookings
- `agent_bookings_update_status` - Update booking status
- `agent_dashboard_overview` - Get dashboard metrics

**Admin Tools** (prefix: `admin_*`):
- `admin_system_status` - System health and statistics

### MCP Client Configuration

All clients connect to the same server URL. Configuration format varies by client:

**Generic Streamable HTTP** (any MCP client):
```json
{
  "mcpServers": {
    "360ghar": {
      "transport": "http",
      "url": "https://api.360ghar.com/mcp"
    }
  }
}
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "360ghar": {
      "type": "streamable-http",
      "url": "https://api.360ghar.com/mcp"
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "360ghar": {
      "url": "https://api.360ghar.com/mcp",
      "transport": "streamable-http"
    }
  }
}
```

**VS Code Copilot** (`.vscode/mcp.json`):
```json
{
  "servers": {
    "360ghar": {
      "url": "https://api.360ghar.com/mcp",
      "type": "http"
    }
  }
}
```

**ChatGPT Apps**: Settings > Apps & Connectors > Advanced, URL: `https://api.360ghar.com/mcp`

> For agent/admin access, use `https://api.360ghar.com/mcp-admin` as the URL. Client config formats change — check your client's documentation for the current format.

### Generative UI (Widgets)

11 React widgets bundled as standalone HTML files in `chatgpt-widgets/dist/`, registered as MCP resources with MIME type `text/html;profile=mcp-app`:

| Widget | Linked Tools |
|--------|-------------|
| PropertySearchWidget | `discovery_search`, `guest_property_search`, `guest_property_recommendations` |
| PropertyDetailsWidget | `discovery_property_get`, `guest_property_details`, `owner_properties_get`, `agent_properties_get` |
| PropertySwipeWidget | `discovery_feed` |
| VisitSchedulerWidget | `visits_schedule`, `bookings_get` |
| VisitListWidget | `visits_list`, `bookings_list`, `agent_bookings_list_all` |
| LeaseDetailsWidget | `tenant_lease_current` |
| MaintenanceWidget | `tenant_maintenance_list`, `tenant_maintenance_create`, `agent_maintenance_list` |
| OwnerDashboardWidget | `owner_properties_list`, `owner_dashboard_overview`, `agent_properties_list`, `agent_dashboard_overview` |
| LeaseManagementWidget | `owner_leases_list`, `owner_leases_get`, `agent_leases_list` |
| RentCollectionWidget | `owner_rent_status`, `owner_rent_record_payment`, `owner_rent_history`, `agent_rent_list_due`, `agent_rent_record_payment` |
| TenantRentWidget | `tenant_rent_dues`, `tenant_rent_history` |

**Bridge protocol**: `chatgpt-widgets/src/utils/bridge.ts` provides unified React hooks (`useToolOutput`, `useCallTool`, `useSendMessage`, `useTheme`, `useWidgetState`) that work identically on OpenAI and MCP Apps hosts. MCP Apps protocol version `2026-01-26` with JSON-RPC 2.0 over postMessage (`ui/initialize`, `ui/notifications/*`, `tools/call`, `ui/message`, auto-resize).

**Theme support**: Light/dark mode propagated from host context on all MCP hosts.

**Content-hash versioning**: Widget URIs include `?v=<content_hash>` for cache busting, computed at registration time.

**Widget-to-tool mapping**: Defined in `WIDGETS` dict in `app/mcp/chatgpt/__init__.py`. `get_widget_for_tool()` resolves tool names to versioned widget URIs.

### Feature Support Matrix

| Feature | Status | Notes |
|---------|--------|-------|
| Tools | Supported | 40+ tools across user and admin servers |
| Resources (Widgets) | Supported | 11 HTML widget resources via `io.modelcontextprotocol/ui` |
| OAuth 2.1 + PKCE | Supported | Full RFC 6749/7636/7591/8414/8707/9728 |
| Generative UI | Supported | Interactive HTML widgets on all MCP hosts |
| Tool annotations | Supported | `readOnlyHint`, `openWorldHint`, `destructiveHint`, `securitySchemes` |
| Structured output | Supported | `structuredContent` in all tool results |
| Elicitation | Not yet | Mid-tool user questions (MCP protocol feature) |
| Sampling | Not yet | LLM callbacks to client |
| Server notifications | Not yet | Proactive server-to-client notifications |
| Progress tokens | Not yet | Long-running tool progress reporting |

### Apps SDK Compliance

The MCP servers are compatible with the OpenAI Apps SDK and the MCP Apps standard (SEP-1865) from a single server:

- **Widget MIME type**: Use `RESOURCE_MIME_TYPE` from `app/mcp/apps_sdk.py` (`text/html;profile=mcp-app`) when registering widget resources
- **Tool annotations**: Every tool must include `readOnlyHint`, `openWorldHint`, and `destructiveHint` in its `annotations` dict
- **Security schemes**: Every tool must include `securitySchemes` (use `MCP_SECURITY_SCHEMES_MIXED` for guest-accessible tools, `MCP_SECURITY_SCHEMES_OAUTH2_ONLY` for auth-required tools)
- **Dual metadata**: Use `build_widget_tool_meta()` to emit both standard `ui.*` keys and OpenAI `openai/*` alias keys — ensures widgets render on all MCP hosts
- **Widget URI in responses**: Pass `widget_uri=get_widget_for_tool("tool_name")` to `format_chatgpt_response()` for widget-linked tools
- **Response format**: Return `AppsSDKToolResult` with `content` (text summary), `structuredContent` (JSON data), and `_meta` (widget metadata) — compatible with all MCP hosts
- **Auth challenges**: Use `raise_auth_required()` (not raw `AuthRequiredError`) to ensure the challenge includes `resource_metadata` URL and triggers the host's OAuth UI
- **Widget versioning**: Widget URIs include content hash (`?v=...`) for cache busting, computed at registration time

### Key MCP Files

| Purpose | Location |
|---------|----------|
| User MCP server | `app/mcp/user_server.py` |
| Admin MCP server | `app/mcp/admin/server.py` |
| Apps SDK helpers | `app/mcp/apps_sdk.py` |
| Shared tool business logic | `app/mcp/tool_ops/` |
| Multi-client tools | `app/mcp/chatgpt/` |
| PM tool modules (ChatGPT) | `app/mcp/chatgpt/pm_shared.py`, `pm_dashboard_tools.py`, `pm_lease_tools.py`, `pm_maintenance_tools.py`, `pm_owner_tools.py`, `pm_rent_tools.py`, `pm_tenant_tools.py` |
| Response formatters | `app/mcp/chatgpt/response_formatter.py` |
| Widget registry | `app/mcp/chatgpt/__init__.py` |
| Widget bridge (multi-host) | `chatgpt-widgets/src/utils/bridge.ts` |
| Widget theme support | `chatgpt-widgets/src/utils/theme.ts` |
| Built widget HTML | `chatgpt-widgets/dist/` |
| Shared utilities | `app/mcp/utils.py` |
| MCP error helpers | `app/mcp/errors.py` |
| Auth provider | `app/mcp/auth_provider.py` |
| OAuth endpoints | `app/api/api_v1/endpoints/oauth.py` |
| Authorization | `app/services/pm_authz.py` |

> **Note on `tool_ops/`**: These modules contain the shared business logic (service calls, DB queries, authorization, serialization) used by both MCP servers and the AI agent tool bridge. When adding new MCP tools, implement the logic in `app/mcp/tool_ops/` first, then wire it through both `user_server.py`/`admin/` and `tool_bridge.py`.

> **Note on PM tools split**: The former `app/mcp/chatgpt/pm_tools.py` has been decomposed into domain-specific modules (`pm_shared.py`, `pm_dashboard_tools.py`, `pm_lease_tools.py`, `pm_maintenance_tools.py`, `pm_owner_tools.py`, `pm_rent_tools.py`, `pm_tenant_tools.py`). Shared serialization helpers are in `pm_shared.py`.

## Documentation Maintenance Policy

The `.wiki/` directory is the canonical project wiki and must stay in sync with the codebase. After any change that affects the following, update the corresponding wiki page(s) in the same commit or PR:

| Change type | Wiki page to update |
|-------------|---------------------|
| New/modified REST endpoint or router | `.wiki/api/index.md`, relevant `.wiki/features/*.md` |
| New/modified service module | `.wiki/systems/services-layer.md`, relevant `.wiki/features/*.md` |
| New MCP tool or widget | `.wiki/features/mcp-servers.md` |
| New/modified SQLAlchemy model or enum | `.wiki/systems/models.md`, `.wiki/reference/data-models.md` |
| New scheduler or background job | `.wiki/systems/infrastructure.md` |
| New shared httpx client domain | `.wiki/systems/core-cross-cutting.md` |
| New notification type | `.wiki/features/notifications.md` |
| New SSE event type | `.wiki/systems/core-cross-cutting.md` |
| New environment variable | `.wiki/reference/configuration.md` |
| New dependency | `.wiki/reference/dependencies.md` |
| Architectural decision | `.wiki/background/design-decisions.md` |
| Seed data changes | relevant `.wiki/features/*.md` |

When updating the video, edit `.wiki/video/src/scenes/`, run `./.wiki/video/render.sh`, and commit the new `overview.mp4` (Git LFS handles storage).

The GitHub Actions workflow at `.github/workflows/wiki.yml` auto-publishes `.wiki/` to the GitHub wiki tab on every push to `main`. No manual wiki editing is needed.
