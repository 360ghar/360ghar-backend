# API Standardization Design

**Date:** 2026-06-17
**Status:** Approved (pending spec review)
**Scope:** Backend (`360ghar/backend`) + 6 client apps + docs

## Problem

The platform's HTTP API is internally inconsistent, per `FULL_AUDIT_REPORT.md`:

1. **Pagination is fragmented** — 19 endpoints use `page`/`limit`, ~24 use `offset`/`limit` (mostly `/pm/*`), tours+upload use `page`/`page_size`, 10 list endpoints have **no** pagination, 0 use cursors. Response envelopes also vary (`PaginatedResponse`, raw `list`, custom dicts).
2. **Error formats vary at the edges** — the central exception handlers already normalize to `{"error": {"code", "message", "details?}}`, but 3 middlewares (rate-limit, API-key, IP-whitelist) still emit raw `{"detail": ...}`.
3. **Duplicate router mount** — the blog router is mounted at both `/api/v1/blog` and `/api/v1/blogs`.
4. **Overlapping profile endpoints** — `/users/me` and `/users/profile` are aliases (same `UserSchema`, same logic) for GET+PUT (+`/avatar`).
5. **Missing pagination** — 10 list endpoints return all records.
6. **DB connection pooling** — already configured (`QueuePool`, `pool_pre_ping`, `pool_recycle`, `NullPool` in serverless); needs verification/tuning/docs.
7. **API documentation** — Swagger/ReDoc already live at `/api/v1/docs`; needs enriched examples, descriptions, shared error responses.

## Decisions (locked)

- **Pagination format: cursor-based.** (User chose the audit's recommendation.)
- **Migration strategy: hard cut.** Old params/routes removed immediately; all clients updated in the same effort. No backward-compat aliases.
- **Client scope: all 6** — `app`, `stays-app`, `360-estate-app` (Flutter), `360-viewer`, `frontend`, `real-estate-admin-dashboard` (React).

### Accepted consequences

- **List/admin UIs lose "jump to page N" and page numbers** — they become next/prev or "load more." An opt-in `?include_total=true` preserves the *count* ("X results") but not page navigation.
- **Property search & semantic search use an offset-fallback cursor** — true keyset is impossible for distance-from-arbitrary-point and relevance-rank sorts, so these keep offset's snapshot-drift behavior behind an opaque cursor API.

## Architecture

### Cursor pagination core (`app/schemas/pagination.py` — new)

Replaces `PaginationParams`, `PaginatedResponse`, and `make_paginated` in `app/schemas/common.py` (those are removed).

**Response envelope — `CursorPage[T]` (generic):**
```json
{
  "items": [ ... ],
  "next_cursor": "eyJ2IjoxLCJrIjpbIjIwMjYtMDYtMTdUMDA6MDA6MDBaIiwxMDBdfQ",
  "has_more": true,
  "limit": 20
}
```
- Forward-only. `next_cursor: null` ⇒ end of list.
- No `total`/`total_pages`/`page` by default.
- Opt-in `?include_total=true` adds `"total": <int>` (computed via a separate `COUNT(*)` only when requested).

**Request params — `CursorParams` (FastAPI dependency):**
- `cursor: str | None = None`
- `limit: int = Query(20, ge=1, le=100)`
- `include_total: bool = False`

**Cursor token:** opaque, URL-safe base64 of compact JSON `{"v": 1, ...}` with a schema version. Two strategies, chosen per-endpoint, transparent to the client:

- **Keyset** (preferred): for stable, indexable sorts (`created_at DESC, id`; `price`; `updated_at`). Payload `{"v":1,"k":[sort_value, id]}`. Query:
  ```sql
  WHERE (sort_col, id) < (:val, :id)
  ORDER BY sort_col DESC, id DESC
  LIMIT :limit + 1
  ```
  Fetch `limit+1` to compute `has_more`; drop the extra row; `next_cursor` encodes the last returned row.
- **Offset-fallback**: for sorts where keyset is impossible (geospatial distance from an arbitrary point, semantic-relevance score, full-text rank). Payload `{"v":1,"o": offset}`. Backend uses `OFFSET`/`LIMIT` internally; client sees only an opaque cursor.

**Helper API (in `pagination.py`):**
- `encode_cursor(payload: dict) -> str`
- `decode_cursor(cursor: str) -> dict` (raises `ValidationException("INVALID_CURSOR")` on malformed/unsupported version)
- `CursorParams` dependency class
- `build_cursor_page(items, *, limit, next_payload, total=None) -> dict` / `CursorPage[T]` model
- Keyset helpers: `apply_keyset(stmt, *, sort_col, id_col, cursor_payload, limit)` and `keyset_next_payload(last_row, sort_attr, id_attr)`

**Decode failure contract:** an invalid/expired cursor returns `400` with the standard error envelope, code `INVALID_CURSOR`.

### Endpoint conversion

All ~45 list endpoints converge onto `CursorParams` + `CursorPage[T]`, including the 10 currently unpaginated and the per-user convenience endpoints (`/visits/upcoming`, `/bookings/past`, etc.).

Strategy assignment:
- **Keyset:** PM lists (`/pm/*`), users, agents, swipes history, blog posts/categories/tags, visits, bookings, notifications, flatmates matches/likes, tours, uploads, AI jobs, core (bugs/pages/faqs), data-hub registry/auctions/circle-rates/rera — sort by `created_at DESC, id` (or domain-natural stable key).
- **Offset-fallback:** `GET /properties` (geo/text/sort_by), `GET /properties/semantic-search`, `GET /properties/recommendations`, `GET /pm/dashboard/activity`.

Removed: the `offset`/`count`/`skip`/`page`/`page_size` query params; the `PaginatedResponse` envelope; `make_paginated`.

### Error normalization (`app/infrastructure/errors.py`, middlewares)

Add `error_json_response(status_code, code, message, details=None) -> JSONResponse` emitting the standard `{"error": {"code","message","details?}}`. Convert:
- `app/middleware/rate_limit.py` — `RATE_LIMIT_EXCEEDED` (429, keep `Retry-After`/`X-RateLimit-*` headers).
- `app/middleware/security.py` — API-key (`API_KEY_REQUIRED` 401 / `INVALID_API_KEY` 403) and IP-whitelist (`IP_NOT_ALLOWED` 403).

**Unchanged (documented intentional exceptions):** OAuth endpoints (`{error, error_description}`, RFC 6749) and MCP tool/response envelopes (`app/mcp/errors.py`).

### Router & profile cleanup

- `app/api/api_v1/api.py`: remove the second `include_router(blog.router, prefix="/blogs", ...)` mount; keep `/blog`.
- `app/api/api_v1/endpoints/users.py`: remove `GET`+`PUT /users/profile` and `POST /users/profile/avatar`; `/users/me`, `PUT /users/me`, `POST /users/me/avatar` are canonical.

### DB connection pooling (`app/core/database.py`, `app/core/config.py`, `.env.example`)

- Keep `QueuePool` + `pool_pre_ping=True` + `pool_recycle` (PgBouncer-safe); keep `NullPool` only under `SERVERLESS_ENABLED`.
- Add `pool_use_lifo=True` to both non-serverless engines (reduces idle connection count).
- Add a startup log line summarizing the resolved pool config (class, size, overflow, recycle).
- Surface recommended prod values + brief guidance in `.env.example`.
- Test: assert `NullPool` is used iff `SERVERLESS_ENABLED`, and `QueuePool` params map from settings otherwise.

### OpenAPI/Swagger enrichment

- Define shared error-response components and attach `responses={401,403,404,422,429,500}` at router include sites (or via a reusable dict).
- Ensure every router has consistent `tags`, and every operation a `summary`/`description`.
- Document cursor params (`cursor`, `limit`, `include_total`) with descriptions; provide a `CursorPage` example.
- Add request/response `examples` to high-value schemas (auth, properties, bookings, the cursor envelope) via `Field(examples=...)` / `model_config["json_schema_extra"]`.
- Remaining per-endpoint example coverage is mechanical follow-up, not a blocker.

## Client migrations

Each client is its own git repo. Central touch-points:

- **Flutter — `app`** (`lib/core/data/models/api_response_models.dart`, `lib/core/network/api_paths.dart`, `lib/core/network/api_client.dart`, list controllers/repositories): replace `PaginationParams`/`PaginatedResponse` with `CursorParams`/`CursorPage`; thread `next_cursor` instead of incrementing `page`; `/users/profile*` → `/users/me*` (incl. session-critical path constant at `api_client.dart:644` and `api_paths.dart:43`).
- **Flutter — `stays-app`** (`lib/app/data/providers/users_provider.dart`, property/list providers): same cursor model swap; `/api/v1/users/profile/` → `/api/v1/users/me/`, `/users/profile/avatar/` → `/users/me/avatar/`.
- **Flutter — `360-estate-app`** (`lib/features/auth/data/auth_repository.dart` + list repos): cursor swap; `/users/profile/` → `/users/me/`.
- **React — `frontend`** (`src/services/http.js`, `src/services/propertyAPIService.js`, `src/services/userService.js`, `src/services/authService.js`): cursor params in `buildPropertySearchParams` and list fetchers; `/users/profile` → `/users/me`.
- **React — `360-viewer`** (`src/api/client.ts`, list hooks, `src/test/mocks/handlers.ts`): cursor-aware fetching; `/users/profile/` → `/users/me/`.
- **React — `real-estate-admin-dashboard`** (`src/store/api.ts` + feature slices): convert paged tables to cursor next/prev (client keeps a cursor stack for "back"); use `include_total=true` to preserve "X results"; migrate any `/api/v1/blogs/*` **API** calls to `/api/v1/blog/*` (React-router `/blogs` UI routes are unaffected).

## Documentation

- Backend `CLAUDE.md` + `AGENTS.md`: rewrite pagination section (cursor envelope, params, strategies, `include_total`), error-format section (standard envelope + intentional exceptions), note blog single-mount and `/users/me` canonical, DB pool guidance.
- Per-client `CLAUDE.md`/`AGENTS.md` where present: update pagination + profile-endpoint references.

## Out of scope

- Raw-SQL-injection audit item (`FULL_AUDIT_REPORT.md:578`) — separate concern, not in this batch.
- MCP and OAuth error envelopes — intentionally preserved.

## Testing

- Backend unit: `pagination.py` (encode/decode round-trip, version mismatch → `INVALID_CURSOR`, keyset boundary, offset-fallback, `has_more` via `limit+1`, `include_total`).
- Backend integration: representative keyset endpoint (`/pm/leases`) and offset-fallback endpoint (`/properties`) paginate correctly across pages with stable ordering.
- Middleware tests: rate-limit / API-key / IP-whitelist now return the standard error envelope.
- Endpoint test: `/users/profile` and `/api/v1/blogs/*` return 404; `/users/me` and `/api/v1/blog/*` work.
- DB pool test as above.
- Client tests updated per repo (e.g. `app` has `test/core/network/*`).

## Risks

- **Coordinated release:** hard cut means backend + all 6 clients must deploy together or older app builds break. Mitigation: ship behind a dated release; document the cutover.
- **Offset-fallback drift:** acceptable per decision; documented.
- **Lost totals:** `include_total` mitigates count display; page-number UIs must be reworked to next/prev.
