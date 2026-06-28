# Development workflow

The branch, code, test, PR, merge cycle for the 360Ghar backend. This page is mechanics. For what reviewers expect, see [index.md](index.md). For conventions, see [patterns-and-conventions.md](patterns-and-conventions.md).

## Dependencies and environment

The project uses [uv](https://docs.astral.sh/uv/) for dependency management. Dependencies are declared in [`pyproject.toml`](../../pyproject.toml) and locked in `uv.lock`. Always prefix commands with `uv run` so the managed venv is used. Running `python run.py` directly uses the system Python, which lacks project dependencies like `pgvector` and will fail with `ModuleNotFoundError`.

```bash
uv sync --extra dev        # Install runtime + dev deps (pytest, ruff, mypy)
uv run python run.py       # Start the API on 0.0.0.0:3600
```

For hot reload, `uv run fastapi dev app/main.py --host 0.0.0.0 --port 3600` works. Locally you usually want Postgres+PostGIS and Redis up:

```bash
docker-compose up -d db redis
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_*_KEY`, `REDIS_URL`, and the AI provider keys you plan to exercise.

## Branch

Branch from `main`. Keep the name short and intent-revealing, for example `feat/flatmates-super-like` or `fix/booking-cursor`. The team is two people, so branch hygiene is mostly about not stomping on each other.

## Code

Follow the patterns enforced by ruff (see [patterns-and-conventions.md](patterns-and-conventions.md) and [tooling.md](tooling.md) for the full list). The non-negotiables:

- `from __future__ import annotations` as the first import in every `.py` file.
- `X | None` not `Optional[X]`, `list[X]` not `List[X]`, `dict[K, V]` not `Dict[K, V]`.
- Async-first database access via `AsyncSession` injected through FastAPI dependencies.
- Service-class pattern: `class XService: def __init__(self, db: AsyncSession)`.
- Exception chaining in `except` blocks (`from e` or `from None`).
- No ephemeral `async with httpx.AsyncClient()` per request. Use the shared clients in [`app/core/http.py`](../../app/core/http.py) with per-request `timeout=` overrides.
- No new `AsyncIOScheduler` instances. Use `get_scheduler()` from [`app/infrastructure/scheduler.py`](../../app/infrastructure/scheduler.py).

Place code by layer: endpoints in `app/api/api_v1/endpoints/`, business logic in `app/services/`, persistence in `app/models/`, transport in `app/schemas/`, MCP logic in `app/mcp/`. The [contribution contract](../../docs/contribution-contract.md) has the full placement rules.

## Test

```bash
uv run pytest tests/ -v                         # All tests
uv run pytest tests/unit/services/ -v           # A subtree
uv run pytest tests/test_user_service.py -v     # One file
uv run pytest tests/ -k "user" -v               # By keyword
uv run pytest tests/ --cov=app --cov-report=html
```

Coverage must stay at or above 90%; CI enforces `--cov-fail-under=90`. Pick the narrowest layer that proves the behavior: `tests/unit/` for isolated logic, `tests/api/` for REST behavior, `tests/integration/` for database semantics, `tests/e2e/` for cross-layer flows, `tests/mcp/` for MCP tools, `tests/pm/` for property management, `tests/middleware/` for request pipeline. See [testing.md](testing.md) for the full breakdown.

External network calls must be mocked with `respx`, `AsyncMock`, or local fakes. Default test runs never hit live third parties.

## Seed data

The seed system lives in [`seed_data/`](../../seed_data/). It generates deterministic JSON (with `random.seed(42)`), loads it into the database, and uploads media to Cloudinary. Seed records set `is_seed_data = true` on `users`, `agents`, and `properties`.

```bash
uv run python seed_data/01_load_all.py                          # Load all data
uv run python seed_data/01_load_all.py --only hardcoded,seed    # Skip generated activity
uv run python seed_data/01_load_all.py --quick                  # Quick mode
uv run python seed_data/01_load_all.py --dry-run                # Validate without writing
```

Clear with [`seed_data/02_clear_data.py`](../../seed_data/02_clear_data.py):

```bash
uv run python seed_data/02_clear_data.py --confirm
```

## Data safety

These rules are load-bearing and enforced by review:

- **Never delete real user data.** Any `DELETE`, `TRUNCATE`, or `DROP` on a table that may hold real user data must be reviewed with the user before execution.
- **`02_clear_data.py` is dev-only.** It filters by `WHERE is_seed_data = true` on `users`, `agents`, and `properties`, and deletes child records via subquery joins to seed parents. Never run it against production.
- **Child tables are protected via FK joins.** Tables without an `is_seed_data` column (PropertyImage, Visit, Booking, BlogPost, etc.) are only touched when their FK parent is a confirmed seed record. Never issue bare `DELETE FROM` on tables that could contain real data.
- **New seeded models** must either add an `is_seed_data` boolean column with `server_default=text("false")` or cascade from an existing seeded parent.

## Lint and types

Before pushing, run the same lint and type jobs CI runs:

```bash
uv run ruff check app/ --output-format=github
uv run mypy app/ --ignore-missing-imports
```

Ruff rules are listed in [tooling.md](tooling.md) and [patterns-and-conventions.md](patterns-and-conventions.md). Common violations to watch for: missing `from __future__ import annotations`, `Optional`/`List`/`Dict` from `typing`, bare `except` without `from e`/`from None`, `== True`/`== False` on columns, single-letter `l` variable names, and `zip` without `strict=`.

## PR and merge

1. Push your branch and open a PR against `main`.
2. Confirm all three CI jobs pass: `docs-contracts`, `test`, `lint`.
3. Update [`docs/repo-contract.json`](../../docs/repo-contract.json) if you added or moved an endpoint, service, or MCP module. The `docs-contracts` job will fail if the inventory drifts.
4. Request review. For auth, schedulers, migrations, or data-deletion paths, review is mandatory.
5. Squash or rebase merge into `main`. There is no `develop` long-running branch in active use, although CI still triggers on it.

After merge, Railway auto-deploys from `main` via the `railway.toml` healthcheck on `/health`.

## Where to go next

- [testing.md](testing.md) for the test suite, fixtures, and coverage rules.
- [debugging.md](debugging.md) for logs, request IDs, and common errors.
- [tooling.md](tooling.md) for uv, ruff, mypy, Docker, and Supabase CLI migrations.
- [patterns-and-conventions.md](patterns-and-conventions.md) for the full coding conventions.
