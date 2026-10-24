# 360Ghar Backend Operating Contract

This repository uses repo-local docs as the source of truth for contributors and agents. The goal is to keep architecture, contribution rules, and test expectations explicit and lightly enforced.

## Platform Overview

360 Ghar is a unified real estate platform with six integrated modules:

- **360 Ghar Core**: Real estate marketplace for buying and renting properties with swipe-based discovery, property visits, and agent coordination (`/api/v1/properties`, `/swipes`, `/visits`, `/agents`)
- **360 Stays**: Short-stay booking platform for hotels, vacation rentals, and temporary accommodations (`/api/v1/bookings`)
- **360 Flatmates**: Flatmate/PG discovery with swipe-based matching, conversations, moderation, QnA, and visit scheduling (`/api/v1/flatmates`)
- **Property Management**: Comprehensive property management system for landlords and property managers (`/api/v1/pm/*`)
- **360 Virtual Tours**: Immersive 360° property tour platform with AI-powered hotspot generation and scene management (`/api/v1/tours`)
- **360 Data Hub**: Real estate data aggregation with bank auctions, circle rates, court auctions, gazette, jamabandi, RERA projects/complaints, zoning, and neighbourhood data (`/api/v1/data-hub`)

## Operating Docs
- [Architecture Contract](docs/architecture-contract.md)
- [Contribution Contract](docs/contribution-contract.md)
- [Testing Contract](docs/testing-contract.md)
- [Terminology And Ownership](docs/terminology-and-ownership.md)
- [Machine Contract Inventory](docs/repo-contract.json)

## Build And Validation

**Default: run the server directly against the dev env — no Docker.** See *Testing without Docker* below.

```bash
uv run python run.py            # dev env (.env.dev → hosted Supabase), API on :3600
uv run pytest tests/ -v         # needs a local Postgres+PostGIS+pgvector at TEST_DATABASE_URL — NEVER the Supabase URL
```

`docker-compose up -d db redis` only provisions a throwaway Postgres+Redis for local `pytest` — it is not needed for server-run testing.

> **Note:** Dev dependencies (pytest, ruff, mypy) are in the `dev` optional group. Install with `uv sync --extra dev`.

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

HRERA-rights regression tests are strictly mock-only. Run them with dotenv disabled and `--noconftest` so they cannot load project DB configuration or destructive fixtures:

```bash
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='postgresql://test:test@127.0.0.1:1/test' \
  uv run pytest --noconftest -q tests/unit/services/test_hrera_rights.py tests/unit/api/test_hrera_rights.py
```

Written source permission for HRERA data is confirmed, so `HRERA_DATA_ENABLED` defaults to `true`. Set it to `false` to withhold every HRERA surface at once. The HRERA-rights tests above stay mock-only: they must not access the source portal or connect to a database.

### Testing without Docker (default approach)

**The default way to test the backend is to run the server directly against the dev environment — do not use `docker-compose` for testing.** The dev env (`.env.dev`) already points `DATABASE_URL` at the hosted Supabase dev project, so no local database container is required.

```bash
uv run python run.py                          # boots the API on :3600; loads dev env automatically
ENVIRONMENT=development uv run python run.py  # explicitly select .env.dev
```

- The env file is auto-selected by the `ENVIRONMENT` variable in `app/core/config.py` (`development`→`.env.dev`, `test`→`.env.test`, `production`→`.env.prod`). You do **not** need to `source` the env file manually — pydantic-settings loads it on import.
- Exercise endpoints via Swagger (`/api/v1/docs`), ReDoc, or `curl` against `http://localhost:3600`.

**Automated tests (`pytest`) follow a separate, hard rule — do not confuse the two:**

- `tests/conftest.py` issues `DROP TABLE ... CASCADE` on every non-extension table in `public` against `TEST_DATABASE_URL` at session start/end. **Never point `TEST_DATABASE_URL` at the hosted Supabase dev/staging URL** — it will wipe the shared database.
- To run `pytest` locally without Docker you need a local Postgres with both `postgis` **and** `pgvector` extensions, then set `TEST_DATABASE_URL` to it (e.g. `postgresql+psycopg://test_user:test_password@localhost:5432/test_db`). Install dev deps first (`uv sync --extra dev`), then `uv run pytest tests/ -v`.
- `docker-compose up -d db redis` only provisions a throwaway Postgres+Redis for local `pytest` runs — it is **not** needed for day-to-day server-run testing against the dev Supabase DB.

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
supabase db push    # Apply migrations (local dev)
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
- **AI Providers**: `AGNES_AI_API_KEY`, `PERPLEXITY_API_KEY`, `GOOGLE_API_KEY` (embeddings only)
- **Notifications**: `EMAIL_*`, `SMS_*`, `ENABLE_NOTIF_SCHEDULER`
- **Vector Search**: `VECTOR_SYNC_ENABLED`, `GEMINI_EMBED_MODEL`
- **Blog Auto-Publish**: `AUTO_BLOG_ENABLED`, `AUTO_BLOG_CRON`
- **Serverless/Scale-to-Zero**: `SERVERLESS_ENABLED`
- **CORS Override**: `CORS_ORIGINS_STR` (comma-separated, overrides default `CORS_ORIGINS` list)

### CI/CD Pipeline
GitHub Actions (`.github/workflows/tests.yml`) runs on push/PR to `main`/`develop`:
1. **test** — PostGIS + Redis services, `pytest` per shard, then a `coverage-check` job that combines the shard data and fails under 60% (a temporary floor, the target is 90), Codecov upload
2. **lint** — `ruff check app/` and `mypy app/`

### Deployment
- **Railway**: `railway.toml` with healthcheck on `/health`, `ON_FAILURE` restart policy
- **Docker**: `Dockerfile` uses `python:3.12-slim` with `uv sync` entry point

## Database Migrations

Use `scripts/run_supabase_migrations.py` to apply SQL migrations against the remote Supabase database. It connects directly via `DATABASE_URL`, tracks applied versions in a `schema_migrations` table, and is idempotent — safe to run repeatedly. Do **not** use `supabase db push` for remote databases — that command is for local development.

```bash
uv run python scripts/run_supabase_migrations.py              # apply all pending
uv run python scripts/run_supabase_migrations.py --dry-run    # preview only
uv run python scripts/run_supabase_migrations.py --file <filename>.sql  # single file
uv run python scripts/run_supabase_migrations.py --env .env.prod  # use a different env file
```

Always use this script when running migrations on the hosted Supabase database. The `supabase db push` / `supabase db reset` commands are for local development only. Single-file example: `--file 20260621000008_flatmates_social.sql`.

## Database Safety Rules

- **Never delete real user data**: Destructive database operations (`DELETE`, `TRUNCATE`, `DROP`) on tables that may contain real user data must be reviewed with the user before execution. Never run `02_clear_data.py` against production.
- **Seed data clearance is selective**: The `02_clear_data.py` script uses `WHERE is_seed_data = true` on `users`, `agents`, and `properties` tables, and deletes child records via subquery joins to seed parents. This ensures real (non-seed) data is never touched.
- **Child tables are protected via FK joins**: Tables without an `is_seed_data` column (PropertyImage, Visit, Booking, BlogPost, etc.) are deleted only when their parent seed record is identified via `WHERE fk_col IN (SELECT id FROM parent WHERE is_seed_data = true)`. Never issue bare `DELETE FROM <table>` on tables that could contain real data.
- **Bulk deletion tool**: `02_clear_data.py` is the only tool that performs bulk deletions, and it respects `is_seed_data` boundaries. Child records include PropertyImage, Visit, Booking, BlogPost, Tour, PM entities, and social data.
- **Real data protection**: Real users, properties, agents, and their child records are never deleted by seed scripts.
- **Dev-only scripts**: Scripts in `seed_data/` are designed for local development. Never run them against a production database.
- **Before destructive operations**: Always confirm the target database is a development environment, not production. Use `--dry-run` flags where available to preview changes.
- **New seeded models**: When adding a new model that is populated by seed scripts, either add an `is_seed_data` boolean column (with `server_default=text("false")`) or ensure a FK cascade chain links it back to a parent with `is_seed_data`.

## Hosted Supabase Test Runs

- Use Supabase itself for integration/QA tests when local Postgres cannot reproduce hosted behavior, but only against a clearly identified development or staging Supabase project. Never point tests, seeders, cleanup scripts, or ad-hoc SQL at the production/live Supabase database unless the user explicitly asks and approves the exact operation.
- Before running tests against hosted Supabase, verify the active env file and database URL. Do not use `.env.prod` for test runs. Prefer a dedicated `TEST_DATABASE_URL` or non-production env file whose project name makes the target obvious.
- Test data written to Supabase must be scoped for cleanup: set `is_seed_data = true` where the model supports it, add a unique test marker such as `test_run_id`, slug/email/phone prefixes like `agent_test_`, or use dedicated test users. Do not update rows that lack a test marker or seed flag.
- Prefer transaction rollback for automated tests. If committed writes are needed to test real Supabase behavior, record the inserted IDs/markers and clean them up at the end of the run using exact `WHERE` predicates. Run a count/select preview before cleanup and never use bare `DELETE`, `TRUNCATE`, or `DROP`.
- After hosted Supabase testing, clean test data before reporting completion. If cleanup fails or cannot be verified, report the remaining marker/IDs and stop rather than attempting broad destructive cleanup.

## Layering Rules
- HTTP endpoints in `app/api/api_v1/endpoints/` validate input, enforce auth through dependencies, and delegate business logic to `app/services/`.
- REST route composition lives in `app/api/api_v1/api.py`; `app/factory.py` is the composition root, while app wiring, middleware, lifespan, and MCP mounts live in `app/infrastructure/`.
- Business rules belong in `app/services/`. Reuse service functions from REST, MCP, and AI-agent surfaces instead of re-implementing them.
- Persistence models live in `app/models/`; request and response shapes live in `app/schemas/`.
- Social and flatmates models (matches, conversations, blocks, reports) live in `app/models/social.py`; flatmates service logic lives in `app/services/flatmates/` package (conversations, helpers, interactions, matching, moderation, profiles, visits) with REST endpoints in `app/api/api_v1/endpoints/flatmates.py` and admin moderation endpoints in `app/api/api_v1/endpoints/flatmates_admin.py`.
- MCP servers and ChatGPT-specific tool wrappers live in `app/mcp/`. They may format tool responses, but authorization and state changes should still flow through shared services where possible.
- Shared MCP tool business logic lives in `app/mcp/tool_ops/`. These functions are called by both MCP servers (`app/mcp/user/server.py`, `app/mcp/admin/`) and the AI agent tools (`app/services/ai_agent/tools/`) — do not duplicate this logic.
- AI-agent orchestration lives in `app/services/ai_agent/`. Tool registration and model streaming belong there, but tool behavior should still call shared service-layer code.
- Notification dispatch flows through `app/services/notification_config.py` (type registry with channel, priority, frequency caps) → `app/services/notification_dispatcher.py` (multi-channel send) → `app/services/notifications/` (CRUD + Supabase push, sub-modules: crud, fcm, helpers, push) → `app/services/push_notification.py` (FCM). New notification types must be registered in the `NOTIFICATION_TYPES` dict.
- Flatmates app-wide real-time events flow through Supabase Realtime private Broadcast channels via `app/services/flatmates/realtime.py`. Service methods queue events on the SQLAlchemy session and publish only after commit. Clients subscribe to `flatmates:user:{local_user_id}` with Realtime Authorization policies on `realtime.messages`. Event types: `new_match`, `new_message`, `conversation_updated`, `visit_updated`, `listing_status_changed`, `new_notification`. New flatmates realtime event types or subscriptions must update AGENTS.md.
- OAuth token/code persistence uses `app/services/oauth_token_store.py` backed by CacheManager. Token stores require a real (non-null) cache backend in production.
- `app/modules/` is reserved for future physical domain entrypoints. Do not recreate shim-only re-export packages; use the current concrete homes (`app/api`, `app/services`, `app/models`, `app/schemas`, `app/repositories`, `app/mcp`) until a domain is migrated.
- Cross-cutting infrastructure belongs in `app/infrastructure/`, `app/core/`, `app/middleware/`, and `app/vector/`.
- `app/infrastructure/` owns lifespan wiring (startup/shutdown orchestration), middleware registration, exception handlers, MCP HTTP app construction, and route mounting. `app/factory.py` is a thin composition root that delegates to `app/infrastructure/`.
- `app/infrastructure/scheduler.py` provides a shared `AsyncIOScheduler` singleton. All background cron jobs (blog, notifications, vector sync, data hub) register on this single instance via `get_scheduler()`. Do not create per-module `AsyncIOScheduler` instances.
- `app/core/http.py` provides shared `httpx.AsyncClient` singletons (`get_scraper_client()`, `get_blog_client()`, `get_general_client()`, `get_supabase_auth_http_client()`) for connection reuse. Do not create ephemeral `async with httpx.AsyncClient()` per request — use the shared clients with per-request `timeout=` overrides instead.
- `app/shared/` is reserved for future physical shared packages. Current shared contracts and helpers remain in `app/core`, `app/schemas`, `app/utils`, and endpoint dependencies.
- `app/config/` is a re-export package; `from app.config import settings` is the canonical import location (delegates to `app/core/config.py`).
- AI provider abstraction lives in `app/services/ai/` with a factory (`get_ai_provider`) backed by Agnes AI only. Vastu and tour AI go through this layer with automatic exponential-backoff retries, except the Daytona sandbox tour planner (`USE_DAYTONA_SANDBOX`, off by default), which calls Gemini directly inside the sandbox (`app/services/tour_ai/daytona_service.py`) until the Agnes-only decision covers it. There is no provider fallback. Image generation (`app/services/ai/image_gen/`) and the AI agent call Agnes AI directly.
- Blog SEO fields (meta_title, meta_description, focus_keyword, canonical_url, og_image_url, reading_time_minutes, word_count) are auto-computed from the post title/body when not explicitly provided, via helpers in `app/services/blog.py`.

## Architecture Overview

### Layered Structure
```
app/
├── api/
│   ├── api_v1/endpoints/   # REST endpoints (thin controllers; flatmates_admin.py for moderation)
│   ├── api_v1/dependencies/ # Shared auth dependencies (get_current_user, get_current_agent, etc.)
│   └── share.py            # Social share preview endpoints
├── services/               # Async business logic (main logic layer)
│   ├── ai/                 # AI provider factory (Agnes AI) + vastu analyzer
│   │   ├── providers/      # AgnesProvider (httpx + tenacity retries)
│   │   └── vastu/          # Vastu analyzer, prompts, schemas
│   ├── ai_agent/           # Pydantic AI agent (agent_service, tools/, conversation_store, system_prompt)
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
│   ├── sse.py              # Legacy SSE event bus for non-flatmates streaming surfaces
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

**Flatmates Realtime Events**: Flatmates app-wide realtime uses Supabase Realtime private Broadcast channels through `app/services/flatmates/realtime.py`. Service methods queue events on the SQLAlchemy session and publish only after DB commit to `flatmates:user:{local_user_id}`. Supabase Realtime Authorization on `realtime.messages` restricts each authenticated user to their own channel. Event types: `new_match`, `new_message`, `conversation_updated`, `visit_updated`, `listing_status_changed`, `new_notification`.

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
| App constants | `app/core/constants/` |
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
| AI agent tools | `app/services/ai_agent/tools/` |
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
| Tour AI processing | `app/services/tour_ai/` |
| Tour service | `app/services/tour/` |
| Email service | `app/services/email.py` |
| SMS service | `app/services/sms.py` |
| Storage service | `app/services/storage/` |
| Storage path generation | `app/services/storage_paths.py` |
| Image processing | `app/services/image_processing.py` |
| Custom domain service | `app/services/custom_domain.py` |
| Flatmates service | `app/services/flatmates/` (conversations, helpers, interactions, matching, moderation, profiles, visits) |
| Flatmates admin endpoint | `app/api/api_v1/endpoints/flatmates_admin.py` |
| Flatmates admin schemas | `app/schemas/flatmates_admin.py` |
| Agent service | `app/services/agent/` |
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

## Contributor Requirements
- New REST endpoint modules must be routed through `app/api/api_v1/api.py`, covered by tests, and registered in `docs/repo-contract.json`.
- New service modules must follow existing naming conventions, keep I/O async when touching the database, and be registered in `docs/repo-contract.json`.
- New MCP tools, widget bindings, or AI-agent tool bridges must update the architecture and terminology docs when they add a new public surface or execution pattern.
- New background jobs or schedulers must be wired through `app/infrastructure/lifespan.py` startup, register their jobs on the shared scheduler from `app/infrastructure/scheduler.py`, and be documented in the architecture contract. Do not create new `AsyncIOScheduler` instances — use `get_scheduler()` to add jobs.
- Do not add new dependencies without checking current upstream documentation and compatibility with Python 3.12+, FastAPI, SQLAlchemy 2.x, and Pydantic v2.
- New outbound HTTP call sites must use the shared httpx clients from `app/core/http.py` (`get_scraper_client()`, `get_blog_client()`, `get_general_client()`, `get_supabase_auth_http_client()`) instead of creating ephemeral `async with httpx.AsyncClient()` per request. Use per-request `timeout=` overrides when the call needs a different timeout than the client default.

## Use Latest Versions & References
- **Always use the latest stable versions** of packages, SDKs, AI models, API versions, protocol versions, and any external references. Never rely on cached or training-knowledge version numbers, model names, API signatures, or SDK methods — these change frequently and are often outdated.
- **Research current docs before implementing**: Before using any 3rd party library, API, SDK, AI model, or protocol, look up the latest official documentation. Use web search, Context7 MCP tools, `WebFetch`, or `google_search` to retrieve up-to-date docs, version numbers, API references, and code examples.
- **Verify from official sources**: When referencing package versions, model names, API endpoints or signatures, SDK methods, protocol versions (e.g., MCP protocol version), or any external service, always confirm the latest from official sources (docs sites, GitHub releases, PyPI, npm, official changelogs). Never assume from memory.
- **Check changelogs and migration guides**: When upgrading any dependency or integrating a new service, review the official changelog/migration guide for breaking changes and new features.
- **Use Context7 MCP or web search**: Use the `context7` MCP tools (`resolve-library-id` + `query-docs`) or `WebSearch`/`WebFetch`/`google_search` to retrieve up-to-date documentation, latest version numbers, API references, and code examples for any library, service, model, or SDK being used.
- **Verify compatibility**: Confirm that new dependencies are compatible with the project's Python 3.12+ requirement and existing stack (FastAPI, SQLAlchemy 2.x async, Pydantic v2).
- **Stay current with the ecosystem**: Periodically check for newer versions of key dependencies (FastAPI, SQLAlchemy, Pydantic, Supabase, FastMCP, etc.) and update when safe. Prefer latest official docs and examples over outdated tutorials or blog posts.

## Coding Conventions

- **Python 3.12+**, FastAPI, SQLAlchemy 2.x async, Pydantic v2
- **snake_case** for modules/functions/variables; **PascalCase** for classes
- Full type hints everywhere
- Custom exceptions from `app/core/exceptions.py` (e.g., `UserNotFoundException`)
- Pydantic v2 schemas with `model_config = ConfigDict(from_attributes=True)` for ORM mode
- Use `X | None` for nullable fields (not `Optional[X]`); `list[X]` and `dict[K, V]` (not `List`, `Dict`); `from __future__ import annotations` at module top
- Validation with `@field_validator` decorators

### Ruff Lint Rules (enforced in CI)

All code must pass `uv run ruff check app/` before commit. The CI pipeline (`lint` job) runs ruff and will fail on any violation. Key rules to follow:

**Import style (I001, UP035, F401, E402):**
- Always add `from __future__ import annotations` as the first import in every `.py` file (after any module docstring). This makes forward references work. It is a project convention; ruff does not enforce it.
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

## Database Models

**Core entities**: User, Property, Agent, AgentInteraction, Booking, Visit, UserSwipe, Amenity, BugReport, Page, AppVersion, FAQ

**Blog entities**: BlogPost (with SEO fields: meta_title, meta_description, focus_keyword, canonical_url, og_image_url, reading_time_minutes, word_count, published_at, sources, seo_metadata), BlogCategory, BlogTag, BlogPostCategory, BlogPostTag

**Social entities**: UserMatch, UserConversation, UserMessage, UserBlock, UserReport, AppCatalog, MatchQnAAnswer (enum-enforced string columns via `EnumStringType` with DB-level `CHECK` constraints)

**360 Virtual Tour entities**: Tour, Scene, Hotspot, TourAnalyticsEvent, AIJob, MediaFile, UserSession, TourLocation, SearchIndex, CacheEntry, FloorPlan, TourBranding, CustomDomain, VideoMetadata

**Property Management entities**: Lease (with termination_date, termination_reason), RentalApplication, RentalApplicationForm, RentCharge, RentPayment, Expense, MaintenanceRequest, Document, InspectionChecklist

**AI entities**: AIConversation, AIConversationMessage

**Data Hub entities**: BankAuction, CircleRate, CourtAuction, GazetteNotification, JamabandiCache, ReraProject, ReraComplaint, ZoningData, ColonyApproval, NeighbourhoodScore, BankRate, AuctionAlert, ScraperRun, SourceDocument, DataHubEvidenceAssertion, DataHubEntityRevision

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
- VisitStatus: requested, confirmed, completed, cancelled, reschedule_suggested
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
- RentalApplicationStatus: applicant, approved, rejected
- ApplicationFieldType: text, textarea, number, date, boolean, select (custom form questions, JSON, not a DB enum)
- TenantStatus: active, vacated (computed tenancy state)
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

## Security

- Supabase JWT auth via `get_current_user` dependency
- Phone as primary identifier
- Role-based access: user, agent, admin
- Backend does not provide `/api/v1/auth/*` user-session endpoints; clients own login/refresh/logout via Supabase SDK
- Account deletion: `delete_user_account` in `app/services/user.py` hard-deletes the Supabase Auth user, anonymizes all PII, and soft-deletes the local row. Two routes expose it: **`DELETE /api/v1/users/me`** (canonical, returns 204 No Content) and **`POST /api/v1/auth/delete-account`** (alternate for mobile clients, returns 204). There is no `/users/me/delete` route.
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

See also *Database Safety Rules* above.

### `is_seed_data` Flag

The `is_seed_data` boolean column (default `false`) exists on:
- `users` — marks seed/demo user accounts
- `agents` — marks seed/demo agent profiles
- `properties` — marks seed/demo property listings

Child entities (PropertyImage, Visit, Booking, Tour, BlogPost, PM entities, social records, data hub records) do **not** have their own `is_seed_data` column — they are identified as "seed" via FK joins to their parent. When adding a new seeded model, either add `is_seed_data` or ensure FK cascade to an existing seeded parent.

Exception: the standalone tables in `seed_data/02_clear_data.py` (`STANDALONE_TABLES`, which includes data-hub tables such as `rera_projects`, `bank_auctions` and `circle_rates`) have no seed marker and are cleared wholesale. Do not run the clear script against a database whose data-hub rows are real.

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
| AI art | `AI_ART` | `360ghar/generated/art` |
| OG cards | `OG_CARD` | `360ghar/generated/og` |
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
- WebSocket (AI jobs): `ws://localhost:3600/ws/jobs/{job_id}`
- WebSocket (notifications): `ws://localhost:3600/ws/user`
- WebSocket auth: the token is never in the URL. The client sends `{"type": "auth", "token": "<JWT>"}` as the first text frame. A missing or invalid token closes the socket with 4001. An unknown job closes with 4004.
- AI Agent chat (auth): `POST /api/v1/agent/chat`
- AI Agent chat (guest): `POST /api/v1/agent/chat-public`

## AI Agent (in-app assistant)

The in-app assistants (Flutter `360-ghar-app`, web `360ghar-web-ui`) do **not** speak
MCP. They POST to `/api/v1/agent/chat` and consume an SSE stream of
`conversation_info`, `text_chunk`, `tool_call_start`, `tool_call_end`, `widget`,
`done`, `error` frames. Frames are produced by
`PydanticAIAgentService.stream_events()` (typed `(name, data)` pairs) and serialized
with `sse_event()`. **Consumers that need the payloads must iterate `stream_events`
— never re-parse the serialized frames.**

### Agent tool sets — keep these in sync with the MCP tool names

`app/services/ai_agent/tools/__init__.py` defines three lists and
`get_tools_for_role()` composes them:

| List | Roles | Contents |
|------|-------|----------|
| `DISCOVERY_TOOLS` | **all**, incl. guest | `discovery_search`, `discovery_property_get`, `discovery_recommendations` |
| `USER_TOOLS` | user, agent, admin | owner properties, tenant lease/rent/maintenance, bookings, `user_system_status` |
| `ADMIN_TOOLS` | agent, admin | `agent_*` + `admin_system_status` |

Two rules:

1. **A registered tool name must match the MCP tool name** for the same capability.
   `get_widget_name_for_tool()` (`app/mcp/chatgpt/__init__.py`) and both clients'
   tool-chip label maps (`tool_call_indicator.dart`, `ToolChip.jsx`) are keyed on it.
   A name only the agent knows renders an unlabelled chip and no widget.
2. **Property discovery must stay available to every role.** Scoping it to guests
   left signed-in users with no search tool at all, so the model answered "find me a
   flat" with `owner_properties_list` — the only property tool it had. Mirror any
   change here in `USER_TOOLS_SECTION` of `app/services/ai_agent/system_prompt.py`;
   the prompt is what actually steers tool choice.

The agent still exposes fewer tools than `/mcp` (no swipe/shortlist, no `visits_*`,
no owner lease/rent/maintenance). Implement shared logic in `app/mcp/tool_ops/`
first, then wire it through both surfaces.

## MCP Server

360Ghar exposes Model Context Protocol (MCP) servers compatible with **any MCP client** — ChatGPT Apps, Claude Desktop, Cursor, VS Code Copilot, Gemini, MCPJam, and all MCP-compliant hosts. Authentication uses OAuth 2.1 with PKCE.

### Server Architecture

| Endpoint | Server | Purpose |
|----------|--------|---------|
| `/mcp` | User MCP (`ghar360-user`) | End-user tools for owners, tenants, property seekers, and guests |
| `/mcp-admin` | Admin MCP (`ghar360-admin`) | Administrative tools for agents and platform admins |

Both servers use `AppsSDKFastMCP` (extends FastMCP 3.2.4) with OAuth 2.1 + PKCE and share authorization endpoints at `/mcp/oauth/*`.

### Protocol and Transport

- **MCP protocol version**: `2025-11-25`
- **Transport**: Streamable HTTP (stateless, binary JSON-RPC over HTTP) — not SSE
- **Framework**: FastMCP 3.2.4 via `AppsSDKFastMCP` (`app/mcp/apps_sdk.py`)
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
| User MCP server | `app/mcp/user/server.py` |
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
| OAuth endpoints | `app/api/api_v1/endpoints/oauth/` |
| Authorization | `app/services/pm_authz.py` |

> **Note on `tool_ops/`**: These modules contain the shared business logic (service calls, DB queries, authorization, serialization) used by both MCP servers and the AI agent tool bridge. When adding new MCP tools, implement the logic in `app/mcp/tool_ops/` first, then wire it through both `user/server.py`/`admin/` and `services/ai_agent/tools/`.

> **Note on PM tools split**: The former `app/mcp/chatgpt/pm_tools.py` has been decomposed into domain-specific modules (`pm_shared.py`, `pm_dashboard_tools.py`, `pm_lease_tools.py`, `pm_maintenance_tools.py`, `pm_owner_tools.py`, `pm_rent_tools.py`, `pm_tenant_tools.py`). Shared serialization helpers are in `pm_shared.py`.

## When To Update Docs
- Any new public endpoint or router family
- Any new service module or new nested service package
- Any new MCP tool, widget bundle, or AI-agent tool bridge
- Any new scheduler, background processing flow, or startup job
- Any new shared httpx client domain (register in `app/core/http.py`)
- Any new top-level runtime directory under `app/`, `tests/`, or `docs/`
- Any new flatmates or social feature (models, schemas, endpoints, services)
- Any new notification type registered in `NOTIFICATION_TYPES`
- Any new AI provider or vision model constant added to `app/core/constants/`
- Any new SSE event type or subscription (emit/subscribe change)
- Any new infrastructure module or lifespan change (startup/shutdown wiring)
- Any new or modified seed data (generators, loaders, clear script)
- Any new storage bucket, StorageFolder enum value, or storage path convention
- Any new `is_seed_data` column added to a model

## Documentation Drift Checklist
- New public endpoint
- New service domain
- New MCP tool or widget
- New background or scheduler flow
- New shared httpx client domain
- New flatmates or social feature
- New notification type (must be added to `NOTIFICATION_TYPES` in `notification_config.py`)
- New AI provider or vision model
- New SSE event type or subscription
- New infrastructure module or lifespan change
- New MCP tool_ops shared function
- New or modified seed data (generators, loaders, clear script)
- New storage bucket, StorageFolder, or storage path convention
- New is_seed_data column on a model
- Changes to media upload workflow (buckets, paths, optimization)
- If any item changed, update the relevant doc in `docs/` and `docs/repo-contract.json`

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
