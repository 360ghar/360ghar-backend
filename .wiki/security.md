# Security

360Ghar's security model is built on Supabase JWT auth, role-based access control, layered rate limiting, security headers, and OAuth 2.1 with PKCE for MCP clients. The backend never stores passwords or session secrets - Supabase owns the credential layer, and the backend verifies tokens statelessly on every request.

Active contributors: Saksham, Ravi

## Supabase JWT auth

The primary auth path is documented in [api/authentication.md](api/authentication.md). In summary: clients authenticate with Supabase Auth via the Supabase SDK, receive an access token, and send it as `Authorization: Bearer <token>`. The backend verifies the JWT signature locally against the cached Supabase JWKS (1-hour TTL, on-demand refresh on `kid` miss), checks `iss`, `aud`, and `exp`, and syncs the Supabase user into a local `User` row. A short-TTL positive cache (60s, max 5000 entries) keyed by token hash avoids re-verifying identical tokens. Transient network errors are retried twice with a 0.3s flat wait before being classified as `PROVIDER_UNREACHABLE`.

Phone is the primary identifier for Indian users. The `User.phone` column has a unique index, with a normalized last-10-digits fallback in `get_user_by_phone` to handle `+91`, `0091`, and bare-digit formats. Email is a secondary identity-linking key with a partial unique index `uq_users_email`.

## Role-based access control

Three roles, defined in the `UserRole` enum (`user`, `agent`, `admin`), stored on `User.role`. FastAPI dependencies in `app/api/api_v1/dependencies/auth.py` enforce them:

- `get_current_user` - any authenticated user
- `get_current_active_user` - authenticated and not deactivated
- `get_current_agent` - role == `agent`, else 403 `AGENT_REQUIRED`
- `get_current_admin` - role == `admin`, else 403 `ADMIN_REQUIRED`
- `get_current_user_optional` - returns `None` for unauthenticated requests (public endpoints that personalize for logged-in users)

Property Management has its own authorization layer in `app/services/pm_authz.py` that checks ownership and RM assignments on top of the role checks.

## The 503 vs 401 distinction

`AuthFailureReason` in `app/core/auth.py` classifies auth failures: `INVALID_TOKEN` -> 401, `PROVIDER_UNREACHABLE` -> 503 with `Retry-After: 5`, `PROVIDER_ERROR` -> 401. The 503 path lets clients distinguish "my token is bad, log me out" from "Supabase is down, retry in 5 seconds". The `get_current_user_optional` dependency returns `None` (graceful degradation to anonymous) on `PROVIDER_UNREACHABLE` rather than 503, so a Supabase outage does not break public endpoints.

## Rate limiting

File: `app/middleware/rate_limit.py`

A global sliding-window rate limiter runs as pure ASGI middleware. The default is 500 requests per minute per client IP, approximated with two fixed windows (current and previous) for O(1) time and space. It uses the cache manager (Redis in production, in-memory fallback) for cross-process coordination. When exceeded, the response is 429 with a `Retry-After` header. SSE streaming endpoints are exempt - held-open connections would otherwise consume a client's entire per-IP budget. Tighter per-route limits are applied via `EndpointRateLimiter` on sensitive endpoints (e.g. 60 req/min for the public identifier-status probe). Websocket and non-HTTP scopes bypass the limiter entirely.

## Security headers

File: `app/middleware/security.py` (`SecurityHeadersMiddleware`)

All HTTP responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, and `Referrer-Policy: strict-origin-when-cross-origin`. In production only, HSTS (`max-age=31536000; includeSubDomains`) and a `Content-Security-Policy` that restricts `default-src` to `'self'`, allows inline scripts and styles, permits images from Cloudinary and data URIs, and limits `connect-src` to self, Supabase, and Cloudinary. MCP streaming tool routes (`/mcp/*`, `/mcp-admin/*` except OAuth paths) skip the middleware to avoid breaking the streaming response.

## OAuth 2.1 with PKCE for MCP

File: `app/mcp/auth_provider.py`

The MCP servers at `/mcp` and `/mcp-admin` use OAuth 2.1 with PKCE, not bearer JWTs. The `SupabaseTokenVerifier` validates both Supabase JWT access tokens and first-party OAuth access tokens issued by this backend. It returns a FastMCP `AccessToken` with rich claims and implements audience validation per RFC 8707 to prevent token passthrough attacks. Full RFC 9728 / RFC 8414 well-known metadata at `/mcp/oauth/*` enables any OAuth 2.1 client to discover the authorization server and register dynamically via `/mcp/oauth/register`.

## API key validation

File: `app/middleware/security.py` (`APIKeyMiddleware`)

Selected external-facing paths require an `x-api-key` header validated against the `VALID_API_KEYS` setting - a secondary auth mechanism for service-to-service access where OAuth or JWT is impractical.

## Request ID and tracing

`RequestIDMiddleware` generates a UUID per request (or accepts an inbound `X-Request-ID`), stores it in a contextvar for structured logging, and echoes it back as `X-Request-ID` in the response. The contextvar is reset in a `finally` block to avoid leakage. MCP streaming tool routes skip the middleware to avoid buffering streamed responses.

## Sentry

The `sentry-sdk[fastapi]` package is integrated with `send_default_pii=False`. The `SENTRY_DSN` and `SENTRY_TRACES_SAMPLE_RATE` settings control initialization. The auth dependency tags the Sentry user context with `id`, `email`, and `phone` (as `username`) after successful authentication. Performance monitoring is sampled at the configured rate.

## Data safety

See the "Data Safety" section of `CLAUDE.md` for the full destructive-operations policy. The short version: never delete real user data. The `seed_data/02_clear_data.py` script filters by `is_seed_data = true` on `users`, `agents`, and `properties`, and deletes child records via subquery joins to seed parents - never via bare `DELETE FROM`.
