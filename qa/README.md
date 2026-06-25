# 360Ghar Backend — QA / Feature Verification

This directory is the **single canonical home** for the end-to-end QA effort:
enumerating every feature, capturing its expected behaviour as a user story,
testing each behaviour, logging errors, and tracking fixes.

## Artifacts

| File | Purpose |
|------|---------|
| `feature_user_stories.csv` | **The canonical spreadsheet.** One row per user-facing feature (REST endpoint), with role, user story, expected behaviour, status, and test results. |
| `error_log.md` | Phase 2 findings — every error discovered during testing, classified (real app bug vs. stale test), with fix status. |
| `../scripts/dump_routes.py` | Introspects the live FastAPI app and dumps every route (method, path, auth dependency, params, docstring) to JSON. Source of truth for the inventory. |
| `../scripts/gen_user_stories.py` | One-time seed generator: turns the route dump into the initial CSV. After seeding, the CSV is **hand-maintained**. |

## Methodology (the loop requested)

1. **Enumerate** every feature → `dump_routes.py` (359 REST endpoints across 15 modules) plus MCP tools, schedulers, and background jobs.
2. **User stories + expected behaviour** → `feature_user_stories.csv`, grounded in the actual endpoint/service code.
3. **Test** each user story; **document** every error → `error_log.md` + the `Status` / `Test Result` columns.
4. **Fix** every logical / UX error.
5. **Re-test** post-fix.
6. **Author comprehensive tests** (incl. edge cases) under `tests/` with a clean structure.

## Status legend (`Status` column)

| Value | Meaning |
|-------|---------|
| `Pending` | Not yet tested. |
| `Tested - Pass` | Behaviour verified, matches expectation. |
| `Tested - Fail` | Behaviour deviates; see `Test Result / Errors`. |
| `Fixed & Verified` | A bug was found and fixed; re-tested green. |
| `Stale test` | Existing test was outdated vs. evolved code; rewritten in Phase 5. |

## Module breakdown (REST endpoints)

Ghar Core 43 · Virtual Tours 56 · Property Management 49 · Auth & Identity 51 ·
Flatmates 37 · Data Hub 33 · Core/Platform 24 · Blog 19 · 360 Stays 18 ·
Notifications 11 · Media & Upload 9 · AI Agent 6 · Vastu 2 · Design Studio 1.

## Running the test suite locally

```bash
docker build -f .github/Dockerfile.test-db -t test-postgres .
docker run -d --name test-postgres -e POSTGRES_USER=test_user -e POSTGRES_PASSWORD=test_password -e POSTGRES_DB=test_db -p 5432:5432 test-postgres
docker run -d --name test-redis -p 6379:6379 redis:7-alpine
docker exec test-postgres psql -U test_user -d test_db -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS postgis;"

export TEST_DATABASE_URL=postgresql+psycopg://test_user:test_password@localhost:5432/test_db
export DATABASE_URL=$TEST_DATABASE_URL REDIS_URL=redis://localhost:6379/0
export SUPABASE_URL=https://mock.supabase.co SUPABASE_PUBLISHABLE_KEY=mock SUPABASE_SECRET_KEY=mock
export ENVIRONMENT=test CI=true
uv run pytest tests/ -q
```
