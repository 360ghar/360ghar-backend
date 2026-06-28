# Monitoring

360Ghar's observability story is built on three layers: structured logging with request IDs for local and production debugging, Sentry for error tracking and performance monitoring, and a shallow health endpoint for uptime checks. Real-time SSE monitoring is per-user rather than system-wide.

Active contributors: Saksham, Ravi

## Structured logging

File: `app/core/logging.py`

The logging subsystem configures the root logger via `dictConfig`. Three formatters: **Color** (default in local dev with a TTY, ANSI-colored `HH:MM:SS | LEVEL | logger | message`), **Standard** (CI, non-TTY, ISO-8601 timestamps), and **Structured** (production, JSON via `StructuredFormatter`).

Noisy libraries are silenced: `httpx` at WARNING, `asyncio` at WARNING, `sqlalchemy.engine` at WARNING (suppresses SQL), and `app.services.user` at WARNING in production (auth lookups fire on every request). Uvicorn access and error logs stay at INFO. A `RequestIDFilter` is attached to the root handler so every record carries the active `request_id` from the contextvar.

## Request IDs

`RequestIDMiddleware` in `app/middleware/security.py` generates a UUID per request (or accepts an inbound `X-Request-ID`), stores it in a `_current_request_id` contextvar, and echoes it back as `X-Request-ID`. The contextvar is reset in a `finally` block to prevent leakage across requests in the same async worker.

## Sentry

File: `app/main.py`

Sentry initializes when `SENTRY_DSN` is set. Key config: `send_default_pii=False`, `traces_sample_rate` defaults to 0.5 in dev and 0.05 in prod (overridable), `release=f"360ghar-backend@{settings.APP_VERSION}"`, a `before_send` hook that strips `authorization` and `x-api-key` headers, and integrations for FastAPI, SQLAlchemy, and logging (WARNING-and-above as breadcrumbs, no events). The auth dependency tags the Sentry user context with `id`, `email`, and `phone` after successful authentication.

## Health endpoint

`GET /health` is the Railway healthcheck target. It uses a raw engine connection (not the session pool) with a short timeout so it never blocks on pool exhaustion, and retries once on transient PgBouncer errors. It always returns 200 - the `status` field indicates `healthy` or `degraded`, so a degraded dependency does not trigger a restart loop. `GET /api/v1/health` redirects to `/health` (307).

## SSE monitoring

The SSE event bus in `app/core/sse.py` is per-user, not system-wide. Services emit events (`new_match`, `new_message`, `conversation_updated`, `visit_updated`, `listing_status_changed`, `new_notification`) after a DB commit, and `GET /api/v1/flatmates/sse` consumes from the user's queue with a 30s keepalive. The bus drops the oldest event on queue full and reaps dead queues, so a slow consumer does not destabilize the process. There is no system-wide SSE stream for ops monitoring - use logs and Sentry for that.

## Further reading

- [logging.md](logging.md) for logging patterns, formatters, and conventions
- [security.md](../security.md) for the auth and rate-limiting layers that feed the audit trail
