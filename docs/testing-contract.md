# Testing Contract

The test suite is organized by intent. Add tests in the narrowest layer that proves the behavior.

## Suite Shape
- `app/modules/<domain>/tests/`: co-located characterization or unit tests for migrated domain code.
- `tests/unit/`: isolated logic with mocks or lightweight objects.
- `tests/api/`: REST endpoint behavior against the ASGI app and overridden dependencies.
- `tests/integration/`: database-backed integration tests, including PostGIS and full-text behavior.
- `tests/e2e/`: user-facing business flows that traverse multiple layers.
- `tests/mcp/`: MCP server behavior, Apps SDK formatting, widget registration, and auth wiring.
- `tests/pm/`: focused PM domain behavior that spans authz and ledger rules.
- `tests/middleware/`: request pipeline behavior.

## Fixture Expectations
- [`tests/conftest.py`](../tests/conftest.py) is the base fixture contract for the async engine, transaction rollback session, and ASGI test client.
- Tests that touch the database should use the shared session fixtures instead of creating their own engines or persistent state.
- External network calls should be mocked with `respx`, `AsyncMock`, or equivalent local fakes.

## Determinism Rules
- Do not rely on live third-party services in default test runs.
- Freeze or inject time when behavior depends on dates, expiration, or scheduled work.
- Keep assertions on MCP and AI-agent flows focused on stable artifacts such as tool names, structured payloads, persisted message roles, and SSE event types.

## Coverage Expectations
- New endpoint modules require API or e2e coverage.
- New service logic requires unit coverage and integration coverage when database semantics are important.
- Data Hub provenance unit tests cover allowlists, safe summaries, no-op/changed revisions, and complete/partial/failed outcomes. PostgreSQL FK/check constraints and revision immutability require an isolated local database; never substitute hosted Supabase.
- HRERA-rights gate and public-isolation tests in `tests/unit/services/test_hrera_rights.py` and `tests/unit/api/test_hrera_rights.py` must be mock-only, run with `--noconftest` and dotenv disabled, and assert no DB/network call on disabled paths. Never use live HRERA, a database, or an external portal for these tests. Cover scheduler/manual gates, RERA route query prevention, locality/property isolation, digest filters across query and cached routes, reviewer-backed verification, source-to-checked-time mapping, and deterministic builder ordering.
- RSS/CDN cache state is external to the backend test contract; tests must not purge it. Backend-only suppression cannot invalidate existing RSS XML, which may remain cached for up to 24 hours.
- New MCP tools require `tests/mcp/` coverage and should verify tool metadata or response structure.
- New AI-agent behavior requires unit coverage for helper behavior and API coverage where SSE persistence or widget emission changes.
- Public route stability is characterized by `tests/fixtures/openapi_path_baseline.json`; behavior-preserving architecture refactors must not change that path list without explicit API approval.
