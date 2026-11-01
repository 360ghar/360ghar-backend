# Deployment

360Ghar runs on Railway in production, with Docker and docker-compose for local and self-hosted deployments. The app is a single async Python process (no workers, no Celery) that serves REST, MCP, WebSocket, and SSE traffic from one Hypercorn/Uvicorn instance. Background work runs on an in-process `AsyncIOScheduler`, disabled in serverless mode.

Active contributors: Saksham, Ravi

## Railway (production)

File: `railway.toml`

Railway builds from the `Dockerfile` and runs `python run.py`. The healthcheck hits `/health` and the restart policy is `ON_FAILURE` with a 3-retry max. Production env vars are set in the Railway dashboard and mirrored in `[deploy.env]`:

- `ENVIRONMENT = production`, `DEBUG = false`
- `SERVERLESS_ENABLED = true` - skips in-process schedulers, falls back to in-memory cache
- `DB_USE_NULL_POOL = false`, `DB_POOL_SIZE = 8`, `DB_MAX_OVERFLOW = 2`, `DB_BG_POOL_SIZE = 2`, `DB_BG_MAX_OVERFLOW = 0`, `DB_POOL_TIMEOUT = 5` - bounded client-side pool
- `DB_POOLER_CLIENT_BUDGET = 120`, `DB_REPLICA_COUNT = 1` - startup refuses to run when replicas × pool budget exceeds the budget
- `PUBLIC_BASE_URL = https://api.360ghar.com` - used for OAuth metadata, MCP resource URIs, share previews

Supavisor (Railway's PgBouncer equivalent) does the server-side multiplexing, but it only has 200 client slots. That is why production keeps `NullPool` off: `NullPool` removes the client-side cap, so every concurrent request becomes a Supavisor client and bursts fail with `FATAL: (EMAXCONN) max client connections reached`. The bounded pool makes excess requests wait briefly and then return 503 with `Retry-After` instead of exhausting the pooler.

For Supabase-backed Railway deployments, `DATABASE_URL` must use the transaction-pooler connection string on port `6543`. The shared pooler session-mode URL on port `5432` can exhaust the small Supavisor session client cap under bursty mobile traffic; production startup rejects Supabase pooler URLs that are not transaction-pooler URLs. Prepared statements remain disabled via psycopg `prepare_threshold=None`, which is required for transaction pooling.

## Docker

File: `Dockerfile`

A multi-stage build on `python:3.12-slim`. The builder stage installs `gcc`, `g++`, `libpq-dev` for native extensions, copies `pyproject.toml` and `uv.lock`, and runs `uv sync --frozen --no-dev --no-install-project` to install runtime deps (no dev tools, no project itself) into `/app/.venv`. The runtime stage installs only `libpq5`, copies the builder's `.venv` and the source tree, sets `PATH=/app/.venv/bin:$PATH`, exposes port 3600, and runs `python run.py`. The `--frozen` flag enforces lockfile fidelity - if `uv.lock` is out of sync, the build fails.

## docker-compose (local dev)

File: `docker-compose.yml`

Three services: `db` (`postgis/postgis:15-3.3` with a persistent volume, PostGIS required for geospatial and pgvector), `redis` (`redis:7-alpine`, 64MB maxmemory, allkeys-lru, 128MB limit), and `api` (built from the `Dockerfile`, 512MB limit, depends on db and redis). For day-to-day dev, most contributors run `docker-compose up -d db redis` for data services and `uv run python run.py` for the API against the local venv.

## Serverless mode

When `SERVERLESS_ENABLED=true`, the app adapts for scale-to-zero hosting: all in-process schedulers are skipped (cron work moves to the GitHub Actions cron endpoints) and the cache falls back to in-memory if Redis is unavailable. The DB pool is a separate decision: `DB_USE_NULL_POOL` defaults to `false` and production keeps the bounded pool under `DB_POOLER_CLIENT_BUDGET`. See [background/pitfalls.md](background/pitfalls.md).

## Health check

`/health` is the Railway healthcheck target. `/api/v1/health` redirects to it (307). The endpoint probes the database with a lightweight `SELECT 1` but always returns HTTP 200 (with a `degraded` status field on failure), so a Postgres outage does not trigger a restart loop.

## Environment configuration

All configuration is environment-variable driven, loaded by `pydantic-settings` in `app/core/config.py`. Copy `.env.example` to `.env` for local dev. See [reference/configuration.md](reference/configuration.md) for the full variable reference.

## Startup sequence

The lifespan in `app/infrastructure/lifespan.py` runs on startup: initialize the cache (Redis with in-memory fallback), apply lightweight DDL that cannot go through Supabase CLI migrations (enum value additions, column adds, each wrapped in try/except), prewarm Supabase DNS via `getaddrinfo` so misconfig surfaces in startup logs, then register scheduler jobs (blog, notifications, vector sync, data hub) on the shared `AsyncIOScheduler` and start it (skipped in serverless mode). Shutdown disposes both DB engines, closes all shared httpx clients, shuts down the scheduler, closes AI provider HTTP clients, and drains the notification thread pool.

## Other deployment artifacts

- `Procfile` - `web: python run.py` (Heroku-style platforms)
- `app.yaml` - Wasmer Edge app metadata for `wasmer deploy`
- `wasmer.toml` - Wasmer package config
- `run.py` - robust entry script that binds to the platform-provided `PORT` (defaults to 3600)
