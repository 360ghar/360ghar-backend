# Debugging

How to read what the backend is telling you and where to look when it is not. For build and lint problems, see [tooling.md](tooling.md). For test failures, see [testing.md](testing.md).

## Logs and request IDs

Logging is structured through [`app/core/logging.py`](../../app/core/logging.py). Every request gets a request ID via `RequestIDMiddleware` in [`app/middleware/security.py`](../../app/middleware/security.py), stored in a context var and attached to every log line in the request. The token is reset in a `finally` block via `reset_request_id(token)`, so the context var does not leak across requests.

When debugging a specific request:

1. Grab the `request_id` from the response header or the client log.
2. Filter the backend log by that ID. All log lines for that request, including downstream service calls, carry the same ID.
3. Sentry groups by the same context, so the same ID appears in Sentry event metadata if the error was captured.

Logs are JSON-formatted in production and human-readable in development. The `RequestIDFilter` ensures the ID is present on every record, not just the entry log.

## Supabase auth errors

Auth is verified in [`app/core/auth.py`](../../app/core/auth.py) and the dependencies in [`app/api/api_v1/dependencies/auth.py`](../../app/api/api_v1/dependencies/auth.py). Two failure modes look similar but mean different things:

- **`PROVIDER_UNREACHABLE`** — Supabase is down or unreachable from the backend. The dependency returns HTTP 503 with `Retry-After: 5`. This is a transient outage, not a bad token. Retry the request after the backoff.
- **HTTP 401** — The JWT is missing, expired, or malformed. The client needs to refresh the token via the Supabase SDK; the backend does not expose `/auth/*` session endpoints.

If you see 503s in a loop, check Supabase status and the `SUPABASE_URL` configuration. If you see 401s, the client owns the fix. The distinction is deliberate: a bad token should not be retried, and a Supabase outage should not be reported as an auth failure.

The backend also does DNS prewarm for Supabase at startup (see [systems/infrastructure.md](../systems/infrastructure.md)) to reduce cold-start `PROVIDER_UNREACHABLE` errors.

## Database connection issues

The async engine is configured in [`app/core/database.py`](../../app/core/database.py). Common symptoms and causes:

- **`OperationalError: connection refused`** — Postgres is not running. Start it with `docker-compose up -d db`.
- **`Extension "vector" or "postgis" does not exist`** — The database was created without the extensions. CI creates them with `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS postgis;`. Locally, run the same against your dev database.
- **`Too many connections`** — Connection pool exhaustion. In serverless mode the app uses `NullPool` and relies on PgBouncer; in normal mode it uses a sized pool. Check `DATABASE_URL` and pool settings in `app/core/config.py`.
- **Transient errors** — [`app/core/db_resilience.py`](../../app/core/db_resilience.py) detects transient DB errors and retries with rollback. If a retry storm appears in logs, look at the underlying error class.

SSE and streaming endpoints release the main-pool session before streaming and use a background-pool session via `get_bg_db`. If a streaming endpoint holds a session too long, the main pool can starve; check that the endpoint calls `get_bg_db` for any DB work inside the stream.

## Cache fallback

The cache subsystem in [`app/core/cache/`](../../app/core/cache/) has two backends: Redis and in-memory. If `REDIS_URL` is not set or Redis is unreachable, the cache falls back to the in-memory backend automatically. Symptoms:

- **Stale reads after a deploy** — The in-memory cache is per-process and does not survive restarts. This is expected; the next request repopulates.
- **Inconsistent values across workers** — Only one worker is running, or each worker has its own in-memory cache. Use Redis in any multi-worker setup.
- **Cache misses in serverless mode** — Serverless mode (`SERVERLESS_ENABLED=True`) uses the in-memory fallback because instances are ephemeral. Cache hit rates will be low; design callers to tolerate misses.

## Serverless mode

When `SERVERLESS_ENABLED=True`, the app:

- Uses `NullPool` for both main and background DB engines (no persistent connections).
- Skips all in-process schedulers (blog, notifications, vector sync, data hub). Cron work must move to Railway cron jobs.
- Uses the in-memory cache fallback.

Debugging serverless issues:

- A scheduled job that stopped running likely never started. Move it to an external cron.
- Higher per-request latency (10 to 50 ms added) is the NullPool trade-off and is expected.
- PgBouncer handles server-side pooling. Connection errors in serverless mode usually point at PgBouncer config, not the app pool.

## MCP OAuth debugging

The MCP servers at `/mcp` and `/mcp-admin` use OAuth 2.1 with PKCE, wired through [`app/mcp/auth_provider.py`](../../app/mcp/auth_provider.py) and the endpoints in [`app/api/api_v1/endpoints/oauth/`](../../app/api/api_v1/endpoints/oauth/). Tokens are stored via [`app/services/oauth_token_store.py`](../../app/services/oauth_token_store.py), which requires a real (non-null) cache backend in production.

Common issues:

- **`AuthRequiredError` raised without a challenge URL** — Use `raise_auth_required()` from the MCP helpers, not the raw exception. The challenge must include `resource_metadata` so the host can render the OAuth UI.
- **Token not persisting across requests** — The cache backend is in-memory in dev. Use Redis in any multi-process deployment.
- **`invalid_grant` from the host** — The authorization code expired or was replayed. Codes are single-use; check the token store logic in `oauth_token_store.py`.
- **Discovery failures** — RFC 9728 / RFC 8414 well-known metadata lives at `/mcp/oauth/*`. If a client cannot discover the server, confirm those endpoints are reachable and not blocked by CORS or a proxy.

OAuth metadata is served from the same origin as the MCP server. Custom domains for tours are a separate system (see [features/mcp-servers.md](../features/mcp-servers.md)).

## Where to go next

- [tooling.md](tooling.md) for build, lint, and type errors.
- [testing.md](testing.md) for interpreting test failures.
- [systems/core-cross-cutting.md](../systems/core-cross-cutting.md) for config, auth, db, cache, http, sse, and logging internals.
- [systems/infrastructure.md](../systems/infrastructure.md) for lifespan, middleware, and scheduler behavior.
