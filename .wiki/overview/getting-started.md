# Getting started

360 Ghar runs as a FastAPI app backed by PostgreSQL with PostGIS, Redis, and Supabase Auth. Local development uses `uv` for dependency management and Docker Compose for the database and cache services. This page walks through prerequisites, install, build, test, run, and environment configuration.

## Prerequisites

- **Python 3.10+** (3.12 used in the Docker image).
- **uv** for dependency management. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Docker** and **Docker Compose** for local PostGIS and Redis.
- **PostgreSQL 15 + PostGIS** — provided via the `postgis/postgis:15-3.3` image in `docker-compose.yml`.
- **Redis 7** — provided via the `redis:7-alpine` image.
- A **Supabase** project for authentication (URL, publishable key, secret key).
- Optional: a Cloudinary account for media, a Google API key for Gemini embeddings, an FCM service account for push, Sentry DSN for observability.

## Install

```bash
# clone
git clone <repo-url> 360ghar-backend
cd 360ghar-backend

# install dependencies (reads pyproject.toml + uv.lock)
uv sync

# dev tooling (pytest, ruff, mypy, playwright, fastapi-cli, hypercorn)
uv sync --extra dev
```

All run commands below use the `uv run` prefix. Running `python run.py` directly uses the system Python, which lacks project deps like `pgvector`, and will fail with `ModuleNotFoundError`.

## Start services

```bash
# PostGIS + Redis only (recommended for local dev)
docker-compose up -d db redis

# full stack including the API
docker-compose up -d --build
```

The database container creates a `ghar360` database. Apply migrations with the Supabase CLI:

```bash
supabase db push        # apply migrations
supabase db reset       # reset local database
supabase db diff        # check pending changes
```

## Environment configuration

```bash
cp .env.example .env
```

Key groups to fill in:

- **Database/Supabase**: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_WEBHOOK_SECRET`.
- **Redis/Cache**: `REDIS_URL`.
- **Serverless**: `SERVERLESS_ENABLED` (skips schedulers, uses `NullPool`, in-memory cache fallback).
- **Pool tuning**: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_BG_POOL_SIZE` (background pool for schedulers and scrapers).
- **AI providers**: `PERPLEXITY_API_KEY`, `GLM_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, plus the `AI_AGENT_*` fallback chain.
- **Notifications**: `EMAIL_*`, `SMS_*`, `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `ENABLE_NOTIF_SCHEDULER`.
- **Vector search**: `VECTOR_SYNC_ENABLED`, `GEMINI_EMBED_MODEL`, `VECTOR_SYNC_CRON` or `VECTOR_SYNC_INTERVAL_SECONDS`.
- **Blog auto-publish**: `AUTO_BLOG_ENABLED`, `AUTO_BLOG_CRON`, `AUTO_BLOG_TIMEZONE`, `AUTO_BLOG_PUBLISHER_USER_ID`.
- **CORS override**: `CORS_ORIGINS_STR` (comma-separated, overrides the default `CORS_ORIGINS` list).
- **Public URLs**: `PUBLIC_BASE_URL` (OAuth/MCP), `PUBLIC_APP_URL` (share previews).

## Run

```bash
# primary (recommended)
uv run python run.py

# hot reload via FastAPI CLI
uv run fastapi dev app/main.py --host 0.0.0.0 --port 3600
```

The API is served at `http://localhost:3600`. Swagger UI at `/api/v1/docs`, ReDoc at `/api/v1/redoc`, OpenAPI YAML at `/api/v1/openapi.yaml`, health at `/health`.

## Test

```bash
uv run pytest tests/ -v                       # all tests
uv run pytest tests/test_user_service.py -v   # single file
uv run pytest tests/ -k "user" -v             # by keyword
uv run pytest tests/ --cov=app --cov-report=html
```

Coverage gate is 90% (`--cov-fail-under=90` in CI). Test markers: `unit`, `integration`, `api`, `mcp`, `e2e`, `external`, `postgis`, `slow`. `asyncio_mode = "auto"` is set in `pyproject.toml`.

## Lint and typecheck

```bash
uv run ruff check app/        # lint (enforced in CI)
uv run mypy app/              # type check (enforced in CI)
```

Ruff rules are summarized in [patterns and conventions](../how-to-contribute/patterns-and-conventions.md). The target is Python 3.10 with a 100-character line length.

## Seed data

```bash
uv run python seed_data/01_load_all.py                            # load all
uv run python seed_data/01_load_all.py --only hardcoded,seed      # skip generated activity
uv run python seed_data/01_load_all.py --quick                    # quick mode
uv run python seed_data/01_load_all.py --dry-run                  # validate only
uv run python seed_data/02_clear_data.py --confirm                # wipe seed data (dev only)
```

Seed loaders set `is_seed_data = true` on users, agents, and properties. The clear script deletes child records via FK joins to seed parents only, never real data. Never run `02_clear_data.py` against production.

## Vector backfill (one-time)

```bash
uv run python -m app.vector.backfill
```

Creates the `property_embeddings` table (pgvector) and runs an incremental sync pass. The first run processes all properties; subsequent runs track progress in `vector_sync_state`.

## CI

GitHub Actions (`.github/workflows/tests.yml`) runs on push/PR to `main`/`develop`:

1. `test` — PostGIS + Redis services, `pytest` with `--cov-fail-under=90`, Codecov upload.
2. `lint` — `ruff check app/` and `mypy app/`.

## Next

- [Architecture](architecture.md) for how the pieces fit together.
- [Patterns and conventions](../how-to-contribute/patterns-and-conventions.md) before writing code.
