# Logging patterns

This page documents the logging conventions used across the 360Ghar backend. The goal is consistency: every module uses `get_logger(__name__)`, every log call passes structured `extra` where useful, and every record automatically carries the current request ID.

Active contributors: Saksham, Ravi

## Logger acquisition

Every module acquires its logger the same way:

```python
from app.core.logging import get_logger

logger = get_logger(__name__)
```

`get_logger` is a thin wrapper around `logging.getLogger`. Using `__name__` means the logger name mirrors the module path (`app.services.user`, `app.api.api_v1.endpoints.properties`), which makes it trivial to filter logs by subsystem.

## Formatters

The logging subsystem selects a formatter based on environment:

| Environment | Formatter | Output |
|---|---|---|
| Local dev with TTY | `ColorFormatter` | ANSI-colored `HH:MM:SS \| LEVEL \| logger \| message` |
| CI / non-TTY dev | `standard` | `YYYY-MM-DDTHH:MM:SS%z \| LEVEL \| logger \| message` |
| Production | `StructuredFormatter` | One JSON object per line |

The `ColorFormatter` maps internal logger names to cleaner display names (`uvicorn.error` -> `uvicorn`) and color-codes levels: DEBUG cyan, INFO green, WARNING yellow, ERROR red, CRITICAL white-on-red.

## Request ID contextvar

The request ID flows through a `contextvars.ContextVar`, not a thread-local, so it correctly propagates across `await` boundaries in the async stack. `RequestIDMiddleware` sets the contextvar at request start and resets it in a `finally` block:

```python
request_id_token = set_request_id(request_id)
try:
    await self.app(scope, receive, send_with_request_id)
finally:
    reset_request_id(request_id_token)
```

The `RequestIDFilter` reads the contextvar on every log record and attaches it as `record.request_id`. Outside a request context, the filter adds nothing - the default value is an empty string.

MCP streaming tool routes (`/mcp/*`, `/mcp-admin/*` except OAuth paths) skip the middleware entirely, so streamed responses are not buffered. Those routes do not get a request ID in their logs.

## Structured extra

Pass structured context via `extra=` rather than f-string interpolation, so the JSON formatter can emit it as fields:

```python
logger.warning(
    "Auth provider unreachable (suffix=%s): %s",
    token_suffix,
    error,
    extra={
        "reason": "auth_provider_unreachable",
        "token_suffix": token_suffix,
    },
)
```

In production, this becomes a JSON object with `reason` and `token_suffix` as top-level fields. In dev, the extra fields are dropped and the `%s` placeholders render the values inline.

## Silenced loggers

To keep the log stream readable, noisy libraries are explicitly silenced in the `dictConfig`:

- `httpx` -> WARNING (suppresses every request/response line)
- `asyncio` -> WARNING
- `sqlalchemy.engine` and `sqlalchemy.engine.Engine` -> WARNING (suppresses SQL statements)
- `uvicorn` and `uvicorn.error` -> INFO
- `uvicorn.access` -> INFO
- `app.services.user` -> WARNING in production, DEBUG in dev (user auth lookups fire on every request and would flood production logs at DEBUG)

## What to log

- **INFO**: lifecycle events (startup, shutdown, scheduler job registration, startup migration applied)
- **WARNING**: recoverable degradation (cache connection failed, Supabase DNS prewarm failed, startup migration skipped, optional auth resolution failed)
- **ERROR**: unrecoverable failures (startup exception, authentication error, unhandled exception in a request)
- **DEBUG**: per-request detail (incoming request method/path, user authenticated successfully, user found by phone) - only in non-production

Never log secrets. The Sentry `before_send` hook strips `authorization` and `x-api-key` headers, but logs themselves should not include tokens, API keys, or passwords. Token suffixes (last 8 chars) are acceptable for correlation.

## Log levels per environment

The root logger level is driven by `settings.LOG_LEVEL` (defaults to INFO). In production, only WARNING and above reaches Sentry as breadcrumbs via the `LoggingIntegration(level=logging.WARNING, event_level=None)` config - logs do not create Sentry events on their own.
