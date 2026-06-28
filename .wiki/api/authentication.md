# Authentication

360Ghar does not run its own auth server. Clients authenticate directly with Supabase Auth using the Supabase SDK, then send the resulting Supabase access token as a bearer JWT to the API. The backend verifies the token, syncs the Supabase user into a local `User` row, and attaches the user to the request. There are no `/api/v1/auth/login`, `/api/v1/auth/refresh`, or `/api/v1/auth/logout` endpoints. Clients own the entire session lifecycle.

Active contributors: Saksham, Ravi

## The verification path

The verification chain spans three files:

1. `app/core/jwt_verification.py` - local JWT verification against the Supabase JWKS
2. `app/core/auth.py` - Supabase client wrapper, failure classification, admin operations
3. `app/api/api_v1/dependencies/auth.py` - FastAPI dependencies that resolve the current user

### Local JWKS verification

`app/core/jwt_verification.py` verifies the Supabase access-token signature, `iss`, `aud`, and `exp` claims locally using the cached JWKS public key set. This avoids a per-request HTTP round-trip to `/auth/v1/user`. The JWKS is fetched from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, cached with a 1-hour TTL (`JWKS_TTL_SECONDS = 3600`), and refreshed on-demand when a `kid` is missing. A short-TTL positive cache (token hash to claims, 60s, max 5000 entries) avoids re-verifying identical tokens within the cache window. If the JWKS endpoint is unreachable, `JWKSUnavailable` is raised and the caller falls back to introspection.

### Failure classification

`app/core/auth.py` defines an `AuthFailureReason` enum with three values:

- `INVALID_TOKEN` - the JWT signature, claims, or expiry failed verification. Maps to HTTP 401.
- `PROVIDER_UNREACHABLE` - Supabase could not be reached (network error, DNS failure, timeout). Maps to HTTP 503.
- `PROVIDER_ERROR` - Supabase returned an error response. Maps to HTTP 401.

The `verify_supabase_token` function returns either the user payload or a tagged failure dict. The dependency layer inspects `_is_failure(result)` and maps the reason to the right status code. Transient network errors (connection resets, gaierror, httpx timeouts) are retried twice with a 0.3s flat wait via tenacity before being classified as `PROVIDER_UNREACHABLE`.

### The 503 distinction

This is the key design decision. A bad token returns 401. A Supabase outage returns 503 with `Retry-After: 5`. The response body carries a `code` of `AUTH_PROVIDER_UNREACHABLE` and a human-readable message. Clients can distinguish "my token is bad, log me out" from "Supabase is down, retry in 5 seconds" without parsing error strings. The constant `_RETRY_AFTER_SECONDS = "5"` lives in `app/api/api_v1/dependencies/auth.py`.

## Phone-first identity

Phone is the primary identifier for Indian users. The `User` model has a unique `phone` column with a partial unique index. The user service's `get_user_by_phone` tries an exact match first, then falls back to a normalized last-10-digits match (handling `+91`, `0091`, and bare-digit formats). Email is a secondary identity-linking key with its own partial unique index `uq_users_email` (unique only when not null).

`last_auth_method` and `last_auth_method_at` on the `User` model mirror the client login state machine. The column is stored as a `String` with a DB-level `CHECK` constraint and typed via the `AuthMethod` enum. Google OAuth client IDs (`GOOGLE_WEB_CLIENT_ID`, `GOOGLE_IOS_CLIENT_ID`, `GOOGLE_ANDROID_CLIENT_ID`) are surfaced to clients via `GET /api/v1/auth/config` so mobile and web clients can render the right sign-in buttons.

## FastAPI dependencies

All auth flows are exposed as FastAPI dependencies in `app/api/api_v1/dependencies/auth.py`:

- `get_current_user(request, authorization, db) -> User` - the primary dependency. Parses the bearer token, verifies it, syncs the Supabase user into a local `User` row via `get_or_create_user_from_supabase`, sets `request.state.user_id`, and tags the Sentry user context. Raises 401 on bad tokens, 503 on provider outage.
- `get_current_active_user(current_user)` - extends `get_current_user` to reject inactive users with 403 (`USER_INACTIVE`).
- `get_current_user_optional(request, authorization, db) -> User | None` - returns `None` instead of raising when no token is present or verification fails. Used by public endpoints that personalize for logged-in users (property feeds, share previews). On `PROVIDER_UNREACHABLE` it returns `None` rather than 503, so a Supabase outage degrades gracefully to anonymous mode.
- `get_current_agent(current_user)` - ensures `role == UserRole.agent`, else 403 (`AGENT_REQUIRED`).
- `get_current_admin(current_user)` - ensures `role == UserRole.admin`, else 403 (`ADMIN_REQUIRED`).
- `get_current_user_sse(request, authorization, token)` - SSE-specific. Browser `EventSource` cannot set custom headers, so this dependency accepts the token as a `?token=` query parameter and falls back to the `Authorization` header. It uses a short-lived background-pool session instead of `Depends(get_db)` so long-running SSE streams do not exhaust the main connection pool.

## What is not here

- No `/api/v1/auth/login`, `/auth/refresh`, `/auth/logout`, or `/auth/register` endpoints. Clients use the Supabase SDK directly.
- No session store on the backend. The backend is stateless with respect to auth - every request re-verifies the JWT.
- No `/users/me/delete` route. Account deletion is exposed at `DELETE /api/v1/users/me` (canonical, returns `MessageResponse`) and `POST /api/v1/auth/delete-account` (alternate for mobile clients, returns 204). The `delete_user_account` service hard-deletes the Supabase Auth user, anonymizes all PII, and soft-deletes the local row.

## MCP auth

The MCP servers at `/mcp` and `/mcp-admin` use OAuth 2.1 with PKCE, not bearer JWTs. The `SupabaseTokenVerifier` in `app/mcp/auth_provider.py` validates both Supabase JWT access tokens and first-party OAuth access tokens issued by this backend, returning a FastMCP `AccessToken` with rich claims. It implements audience validation per RFC 8707 to prevent token passthrough attacks. See [security.md](../security.md) and [features/mcp-servers.md](../features/mcp-servers.md).
