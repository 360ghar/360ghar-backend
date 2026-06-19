# Tooling

The build, lint, type, container, and migration tools for the 360Ghar backend. For the workflow that uses them, see [development-workflow.md](development-workflow.md). For the conventions they enforce, see [patterns-and-conventions.md](patterns-and-conventions.md).

## Build system

The project uses [uv](https://docs.astral.sh/uv/) for dependency management. Dependencies are declared in [`pyproject.toml`](../../pyproject.toml) and locked in `uv.lock`. Runtime dependencies include FastAPI, SQLAlchemy 2.x async, Pydantic v2, httpx, APScheduler, pgvector, GeoAlchemy2, Supabase, FastMCP 3.0.1, Pydantic AI, Pillow, Cloudinary, and Sentry SDK. Dev dependencies (pytest, ruff, mypy, respx) live in the `dev` optional group.

```bash
uv sync                  # Runtime deps only
uv sync --extra dev      # Runtime + dev deps
uv run python run.py     # Start the API through uv's managed venv
```

Always prefix commands with `uv run`. Running `python` or `fastapi` directly uses the system Python, which lacks `pgvector` and other project dependencies.

## Linters

Two linters run in CI and locally:

### ruff

```bash
uv run ruff check app/ --output-format=github
```

Ruff enforces import style, type annotation modernization, exception chaining, equality, naming, whitespace, and a handful of other rules. The enforced rules:

- **I001, UP035, F401, E402** — `from __future__ import annotations` first; `list`/`dict`/`set`/`tuple`/`type` instead of `typing.*`; `Callable`, `Awaitable`, `AsyncIterator`, `Sequence` from `collections.abc`; no unused imports; imports before non-import code.
- **UP045, UP006, UP007, UP037** — `X | None` not `Optional[X]`; `X | Y` not `Union[X, Y]`; `list[X]` not `List[X]`; no unnecessary quotes in annotations.
- **B904** — `raise NewException(...) from e` or `from None` inside `except`.
- **E712** — no `== True` / `== False` on columns. Use the column directly or bitwise negation.
- **E741** — no single-letter `l` variable name.
- **F841** — no unused variables. Use `_` or `_name` to discard.
- **W291, W292, W293** — no trailing whitespace, no whitespace on blank lines, files end with a newline.
- **B905** — `zip(a, b, strict=True)`.
- **C401** — set comprehensions, not `set(gen)`.
- **F541** — no f-strings without placeholders.
- **F811** — no name redefinitions.

### mypy

```bash
uv run mypy app/ --ignore-missing-imports --no-error-summary
```

mypy runs against `app/` with `--ignore-missing-imports`. Full type hints are expected everywhere, consistent with the ruff annotation rules.

## CI

GitHub Actions ([`.github/workflows/tests.yml`](../../.github/workflows/tests.yml)) runs on push and PR to `main` and `develop`. Three jobs:

| Job | What it does |
|---|---|
| `test` | Boots PostGIS (built from `.github/Dockerfile.test-db`) and Redis 7, creates `vector` and `postgis` extensions, runs `uv run pytest tests/ -v --cov=app --cov-report=xml --cov-fail-under=90`, uploads coverage to Codecov. |
| `lint` | Runs `uv run ruff check app/ --output-format=github` and `uv run mypy app/ --ignore-missing-imports --no-error-summary`. |

All three must pass before merge. The `test` job uses `uv sync --extra dev` to install dev dependencies.

## Docker

[`docker-compose.yml`](../../docker-compose.yml) starts three services:

- `db` — PostGIS 15
- `redis` — Redis 7
- `api` — the backend on hypercorn

```bash
docker-compose up -d           # Start everything
docker-compose up -d db redis  # Start only database services for local dev
```

The [`Dockerfile`](../../Dockerfile) uses `python:3.12-slim` with `uv sync` as the entry point. Railway deploys from `main` via `railway.toml` with a healthcheck on `/health` and `ON_FAILURE` restart policy.

## Supabase CLI

Database migrations live in [`supabase/migrations/`](../../supabase/migrations/). Use the Supabase CLI to apply and inspect them:

```bash
supabase db reset   # Reset local database
supabase db push    # Apply migrations
supabase db diff    # Check pending changes
```

Some lightweight DDL (enum additions, column adds) that cannot go through the Supabase CLI is applied at startup in [`app/infrastructure/lifespan.py`](../../app/infrastructure/lifespan.py). See [systems/infrastructure.md](../systems/infrastructure.md) for the startup migration behavior.

## Scripts

The [`scripts/`](../../scripts/) directory holds operational scripts that are not part of the runtime:

| Script | Purpose |
|---|---|
| `scripts/optimize_seed_images.py` | Reduces seed image size to shrink the Docker image. Supports `--dry-run` for preview. |

Seed data scripts live separately in [`seed_data/`](../../seed_data/) and are documented in [development-workflow.md](development-workflow.md).

## Local dev loop

A typical local loop:

```bash
docker-compose up -d db redis
cp .env.example .env          # Fill in DATABASE_URL, SUPABASE_*, REDIS_URL, AI keys
uv sync --extra dev
uv run python run.py          # API on 0.0.0.0:3600
```

Swagger UI at `http://localhost:3600/api/v1/docs`, ReDoc at `http://localhost:3600/api/v1/redoc`, health at `http://localhost:3600/health`.

## Where to go next

- [development-workflow.md](development-workflow.md) for the branch-test-PR cycle.
- [testing.md](testing.md) for the test suite and CI test environment.
- [debugging.md](debugging.md) for interpreting failures.
- [patterns-and-conventions.md](patterns-and-conventions.md) for the full coding conventions.
