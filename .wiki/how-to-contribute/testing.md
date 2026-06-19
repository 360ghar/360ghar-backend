# Testing

How the test suite is organized and what CI expects. The authoritative source is [`docs/testing-contract.md`](../../docs/testing-contract.md); this page is the practical companion.

## Suite shape

Tests are organized by intent. Add tests in the narrowest layer that proves the behavior.

| Directory | What lives here |
|---|---|
| `tests/unit/` | Isolated logic with mocks or lightweight objects. Subdivided into `api/`, `app/`, `core/`, `models/`, `schemas/`, `services/`, `mcp/`, `repositories/`, `utils/`. |
| `tests/api/` | REST endpoint behavior against the ASGI app with overridden dependencies. |
| `tests/integration/` | Database-backed integration tests, including PostGIS and full-text behavior. Includes `services/` for integration-level service tests. |
| `tests/e2e/` | User-facing business flows that traverse multiple layers (booking, PM lifecycle, property listing, user registration). |
| `tests/pm/` | Property management behavior that spans authz and ledger rules. |
| `tests/middleware/` | Request pipeline behavior (rate limit, security headers, trailing slash). |
| `tests/mcp/` | MCP server behavior, Apps SDK formatting, widget registration, and auth wiring. |
| `tests/fixtures/` | Shared fixtures: `auth`, `common`, `data`, `factories`, `mocks`. |

When a new behavior lands, pick the layer that proves it with the least machinery. A pure helper belongs in `tests/unit/`. An endpoint contract belongs in `tests/api/`. A database semantic that needs PostGIS belongs in `tests/integration/`. A full user-visible flow belongs in `tests/e2e/`.

## Running tests

```bash
uv run pytest tests/ -v                              # All tests
uv run pytest tests/unit/services/ -v                # A subtree
uv run pytest tests/test_user_service.py -v          # One file
uv run pytest tests/ -k "user" -v                    # By keyword
uv run pytest tests/test_file.py::test_func -v       # Single test
uv run pytest tests/ --cov=app --cov-report=html     # With coverage
```

Dev dependencies (pytest, ruff, mypy, respx) live in the `dev` optional group. Install with `uv sync --extra dev`.

## Coverage

Coverage must stay at or above 90%. CI enforces this with `--cov-fail-under=90` (see [`.github/workflows/tests.yml`](../../.github/workflows/tests.yml)). The test-to-code ratio is currently around 49% by line count, with 33,125 test lines against 67,841 source lines in `app/`.

Coverage expectations by change type:

- New endpoint module: API or e2e coverage.
- New service logic: unit coverage, plus integration coverage if database semantics matter.
- New MCP tool: `tests/mcp/` coverage that verifies tool metadata or response structure.
- New AI-agent behavior: unit coverage for helpers, API coverage where SSE persistence or widget emission changes.
- Public route stability is characterized by `tests/fixtures/openapi_path_baseline.json`. Behavior-preserving refactors must not change that path list without explicit API approval.

## CI test environment

The `test` job in CI boots two service containers before running pytest:

- **PostGIS** built from `.github/Dockerfile.test-db`, with the `vector` and `postgis` extensions created on `test_db`.
- **Redis 7** (`redis:7-alpine`) with a health check.

Tests run with `TEST_DATABASE_URL`, `DATABASE_URL`, and `ASYNC_DATABASE_URL` all pointing at the same PostGIS instance, and `REDIS_URL` pointing at the Redis container. `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `SUPABASE_SECRET_KEY` are set to mock values; tests that exercise auth mock the Supabase client rather than calling the real one.

## Fixtures

[`tests/conftest.py`](../../tests/conftest.py) is the base fixture contract. It provides the async engine, a transaction-rollback session, and the ASGI test client. Tests that touch the database should use the shared session fixtures instead of creating their own engines or persistent state.

Shared fixture groups in `tests/fixtures/`:

- `auth` — authenticated client helpers and fake JWTs.
- `common` — shared domain objects and request bodies.
- `data` — seeded test data.
- `factories` — builders for model instances.
- `mocks` — respx routers and AsyncMock factories for external services.

## Mock patterns

External network calls must be mocked. The patterns in use:

- **`respx`** for HTTP mocking of outbound calls to Supabase, Cloudinary, AI providers, and scraper targets.
- **`AsyncMock`** for service-layer dependencies injected into endpoints or MCP tools.
- **Local fakes** for the cache backend when a test needs deterministic cache behavior without Redis.

Determinism rules from the testing contract:

- Do not rely on live third-party services in default test runs.
- Freeze or inject time when behavior depends on dates, expiration, or scheduled work.
- Keep assertions on MCP and AI-agent flows focused on stable artifacts: tool names, structured payloads, persisted message roles, and SSE event types.

## Where to go next

- [development-workflow.md](development-workflow.md) for the branch-test-PR cycle.
- [tooling.md](tooling.md) for ruff, mypy, and the CI jobs.
- [debugging.md](debugging.md) for interpreting test failures and logs.
- [patterns-and-conventions.md](patterns-and-conventions.md) for the coding conventions tests assume.
