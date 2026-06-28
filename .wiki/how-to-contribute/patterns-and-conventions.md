# Patterns and conventions

Coding patterns the 360 Ghar backend enforces and how to follow them. Most are encoded in `CLAUDE.md` and `AGENTS.md` at the repo root and enforced by `ruff` in CI.

## Async-first

All database operations and services use `async`/`await`. Services inject an `AsyncSession` via FastAPI dependencies and never block on I/O. The service-class pattern is `class XService: def __init__(self, db: AsyncSession)`, with async methods returning ORM models or 3-tuples. Sync helpers (UTC, timezone) live in `app/core/utils.py`.

## Service layer

Endpoints in `app/api/api_v1/endpoints/` are thin controllers: validate input, enforce auth, delegate to `app/services/`. Business rules belong in services. REST, MCP, and the AI agent all call the same service functions instead of re-implementing them. Complex queries factor out into `app/repositories/` (`BaseRepository`, `PropertyRepository`, `PropertyQueryBuilder`).

## Shared MCP tool logic

MCP tool business logic lives in `app/mcp/tool_ops/`. Both MCP servers (`app/mcp/user_server.py`, `app/mcp/admin/server.py`) and the AI agent (`app/services/ai_agent/tool_bridge.py`) call into `tool_ops`. Never duplicate tool behavior in the server or the bridge. When adding a new MCP tool, implement the logic in `tool_ops/` first, then wire it through both surfaces. Multi-client wrappers in `app/mcp/chatgpt/` format responses and bind widgets but still call `tool_ops` for the actual work.

## Shared httpx clients

Four `httpx.AsyncClient` singletons live in `app/core/http.py`:

| Client | Timeout | Used by |
|---|---|---|
| `get_scraper_client()` | 30s | Data hub scrapers, jamabandi, gazette |
| `get_blog_client()` | 120s | Perplexity blog, SerpAPI image search |
| `get_general_client()` | 30s | Image downloads, geocoding, image gen |
| `get_supabase_auth_http_client()` | 10s | Supabase Auth JWKS / metadata |

Never create an ephemeral `async with httpx.AsyncClient()` per request. Use the shared clients and pass a per-request `timeout=` override when needed.

## Single scheduler and serverless mode

One `AsyncIOScheduler` from `app/infrastructure/scheduler.py` is registered in `app/infrastructure/lifespan.py`. Four job families attach to it: blog auto-publish, notifications, vector sync, and data hub scraping. Do not create per-module scheduler instances; add jobs via `get_scheduler()`. When `SERVERLESS_ENABLED=True`, both DB engines switch to `NullPool` (no persistent connections), schedulers are skipped, and the cache falls back to in-memory so the app can scale to zero behind PgBouncer. The trade-off is roughly 10-50ms added latency per request; move cron work to Railway cron jobs in that mode.

## SSE event bus

`SSEEventBus` in `app/core/sse.py` provides per-user pub/sub. Services call `await sse_bus.emit(user_id, event_dict)` after a DB commit, never before. The endpoint `GET /api/v1/flatmates/sse` consumes from the queue with a 30-second keepalive; the bus drops the oldest event on a full queue. Event types are listed in [the glossary](../overview/glossary.md); adding a new type requires updating `CLAUDE.md` and `AGENTS.md`. Streaming endpoints release the main-pool session before streaming and use the background pool (`get_bg_db`) for tool calls.

## 3-tuple cursor pagination

As of June 2026, paginated list endpoints return `(items, next_cursor, has_more)` tuples instead of bare lists, with keyset cursors on `created_at` replacing offset pagination. This applies across properties, users, agents, bookings, visits, and blog. New list endpoints should return the 3-tuple and accept a `cursor` query parameter.

## Overlapping bookings

The same property can be booked by multiple people for the same or overlapping dates. Do not add date-overlap conflict checks, double-booking guards, or DB exclusion constraints. `check_availability` in `app/services/booking.py` only validates that the property exists and the guest count fits `max_occupancy`.

## Auth

Clients authenticate directly with Supabase Auth and send a bearer access token. `get_current_user` (`app/api/api_v1/dependencies/auth.py`) verifies the JWT and syncs the local user row. Phone is the primary identifier. There are no `/api/v1/auth/*` session endpoints; clients own login, refresh, and logout via the Supabase SDK. When Supabase is unreachable, the dep returns `PROVIDER_UNREACHABLE` and the endpoint responds HTTP 503 with `Retry-After: 5`.

## Ruff lint rules

Ruff runs in CI (`uv run ruff check app/`) and fails on any violation. Target is Python 3.10, line length 100. Key rules:

- **I001, UP035, F401, E402** — `from __future__ import annotations` as the first import in every `.py` file. Use `list`/`dict`/`set`/`tuple`/`type` not `typing.*`. Import `Callable`, `Awaitable`, `AsyncIterator`, `Sequence` from `collections.abc`. Remove unused imports. All imports at file top; `# noqa: E402` only for unavoidable circular imports with a comment.
- **UP045, UP006, UP007, UP037** — `X | None` not `Optional[X]`, `X | Y` not `Union[X, Y]`, `list[X]` not `List[X]`. Remove unnecessary quotes in annotations. For forward references, add `from __future__ import annotations` and import the type under `TYPE_CHECKING`.
- **B904** — Always chain exceptions in `except`. `from e` when the original aids debugging; `from None` when logging the original and raising a user-facing exception.
- **E712** — Never `== True`/`== False`. Use the column directly (`Model.is_active`) or bitwise negation (`~Model.is_active`, `not_(...)`).
- **B905, C401, F541, F811, E741, F841, W291/W292/W293** — `zip(a, b, strict=True)`; set comprehensions not `set(gen)`; no placeholder-free f-strings; no redefining imported names; no single-letter `l`; no unused assignments (use `_`); no trailing whitespace, clean blank lines, files end with a newline.

Custom exceptions live in `app/core/exceptions.py`; always chain per B904.

## Data safety

Never delete real user data without explicit confirmation. `seed_data/02_clear_data.py` filters by `WHERE is_seed_data = true` on `users`, `agents`, and `properties`, and deletes child records via subquery joins to seed parents. Never run it against production. New seeded models need either an `is_seed_data` column (`server_default=text("false")`) or a FK cascade to an existing seeded parent.

## Docs drift

Update `docs/` and `docs/repo-contract.json` when adding any public surface: endpoint, service module, MCP tool, widget, scheduler, shared httpx client domain, flatmates/social feature, notification type, AI provider, SSE event type, infrastructure module, seed data, storage bucket, or `is_seed_data` column.

## See also

- [Getting started](../overview/getting-started.md) and [architecture](../overview/architecture.md).
