# Pitfalls

These are the non-obvious rules and trade-offs that have bitten contributors before. Read this page before adding "fixes" that turn out to break the platform on purpose.

Active contributors: Saksham, Ravi

## Overlapping bookings are allowed

The same property can be booked by multiple people for the same or overlapping dates. There are no double-booking guards, no date-overlap conflict checks, and no DB exclusion constraints on the `bookings` table.

`check_availability` in `app/services/booking.py` only validates that the property exists and that the guest count fits `max_occupancy`. It does not check for conflicting bookings. This is deliberate: hosts manually confirm or decline each `pending` booking, and overlapping requests are treated as competing leads rather than conflicts.

**Do not** add an exclusion constraint, a date-overlap check, or a "this property is already booked" error. If you do, you will break the lead-intake flow that hosts rely on. See [primitives/booking.md](../primitives/booking.md) for the full booking lifecycle.

## Serverless mode trade-offs

When `SERVERLESS_ENABLED=true` (production on Railway), the app uses `NullPool` for both main and background DB engines. Every request opens a fresh Postgres connection, hands it to PgBouncer, and closes it. The trade-off is 10-50ms of added latency per request - acceptable for an API that scales to zero, unacceptable for a high-throughput always-on service.

In serverless mode, all in-process schedulers (blog, notifications, vector sync, data hub) are skipped. Cron work must move to Railway cron jobs or an external scheduler. The cache falls back to in-memory if Redis is unavailable - this means cache entries are not shared across instances, so rate limiting and notification frequency caps become per-instance rather than global.

**Do not** re-enable schedulers in serverless mode without addressing multi-instance coordination. Two scheduler instances will double-fire blog posts, notifications, and scrapers.

## Ephemeral httpx clients are an anti-pattern

Creating `async with httpx.AsyncClient()` per request exhausts file descriptors and adds TLS handshake latency under load. The shared singletons in `app/core/http.py` exist for connection reuse:

| Client | Default timeout | Used by |
|---|---|---|
| `get_scraper_client()` | 30s | Data hub scrapers, jamabandi, gazette, neighbourhood |
| `get_blog_client()` | 120s | Perplexity blog generation, SerpAPI image search |
| `get_general_client()` | 30s | Image downloads, geocoding, OAuth metadata, image gen |
| `get_supabase_auth_http_client()` | 10s | Supabase JWKS fetch, auth introspection |

**Do not** create ephemeral `httpx.AsyncClient()` instances. Use the shared clients with per-request `timeout=` overrides when a call needs a different timeout than the client default. This is enforced by convention and code review, not by linting.

## Double-booking guards

This is a corollary of the overlapping-bookings rule, called out separately because it comes up in code review often. The instinct is to add a `UNIQUE` index or an `EXCLUDE USING gist` constraint on `(property_id, check_in_date, check_out_date)`. Do not. The platform's business model is lead intake, not reservation. Multiple interested parties for the same dates is the expected state, not a bug.

## MCP routes bypass request ID and security headers

MCP streaming tool routes (`/mcp/*`, `/mcp-admin/*` except OAuth paths) skip the request ID middleware, the security headers middleware, and the rate limiter. This is intentional: the middlewares buffer the response, which breaks streaming. OAuth endpoints under `/mcp/oauth/*` and `/mcp-admin/oauth/*` still go through the middlewares because they return normal JSON responses.

**Do not** "fix" the missing security headers on `/mcp` by wrapping it in the middleware. It will break tool streaming.

## Startup migrations are best-effort

The lifespan applies lightweight DDL at startup (enum value additions, column adds) that cannot go through the Supabase CLI migrations. Each statement is wrapped in try/except so a failure logs a warning and continues. If a column already exists (because a previous deploy added it), the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` is a no-op. If the enum value already exists, `ALTER TYPE ... ADD VALUE IF NOT EXISTS` is a no-op.

**Do not** promote these to hard failures. A failed startup migration should not block the app from serving traffic - the migration is almost always already applied.

## Seed data deletion is scoped

The `seed_data/02_clear_data.py` script filters by `WHERE is_seed_data = true` on `users`, `agents`, and `properties`, and deletes child records via subquery joins to seed parents. It never issues bare `DELETE FROM <table>` on tables that could contain real data.

**Do not** run `02_clear_data.py` against production. It is dev-only. If you add a new seeded model, either add an `is_seed_data` column (with `server_default=text("false")`) or ensure a FK cascade chain links it back to a parent with `is_seed_data`.

## 3-tuple service returns (recent refactor)

As of June 2026, property list/search/recommendations and several other list endpoints return a 3-tuple `(items, next_cursor, has_more)` instead of a plain list. Callers must unpack all three values. Tests and MCP tool callers have been adapted, but new code that calls these services must handle the tuple shape.

**Do not** "simplify" a 3-tuple return back to a list. The cursor is required for keyset pagination, and `has_more` is required for the client to know whether to fetch the next page.
