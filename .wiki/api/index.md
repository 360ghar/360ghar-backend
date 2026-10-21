# API

360Ghar exposes a single REST surface at `/api/v1/*` plus two MCP servers at `/mcp` and `/mcp-admin`. This page maps the REST route groups. For the MCP surface, see [features/mcp-servers.md](../features/mcp-servers.md). For auth, see [authentication.md](authentication.md).

Active contributors: Saksham, Ravi

## Router composition

All REST routers are mounted by `app/api/api_v1/api.py` onto a single `APIRouter` named `api_router`, which the app factory mounts at `/api/v1`. The file imports 42 endpoint modules (the deep-link fallback pages in `app/api/deeplinks.py` are mounted at the root, not under `/api/v1`) and calls `include_router` 43 times, with explicit `prefix` and `tags`. Tags drive the OpenAPI grouping in Swagger UI at `/api/v1/docs`. The authoritative full OpenAPI spec is committed at `docs/openapi.json` (regenerate with `uv run python scripts/generate_openapi.py`); a curated flatmates-only subset lives at `docs/flatmates-openapi.yaml`.

## Route groups

| Prefix | Tag | Module | Notes |
|---|---|---|---|
| `/auth` | auth | `app/api/api_v1/endpoints/auth.py` | Account deletion, config. No login/refresh/logout - clients use Supabase SDK. |
| `/users` | users | `users.py` | Profile, preferences, account. |
| `/properties` | properties | `properties.py` | Marketplace listings, search, recommendations. `CursorPage` with filter-bound cursors. `owner_contact` and `listing_preferences` are masked per viewer. `POST` returns 201, `DELETE` returns 204. |
| `/visits` | visits | `visits.py` | Property tours and flatmate meetings. |
| `/bookings` | bookings | `bookings.py` | 360 Stays short-stay reservations. |
| `/swipes` | swipes | `swipes.py` | Tinder-like property and user interactions. |
| `/leads` | leads | `leads.py` | Public callback requests (`POST /leads`). Returns 201 with `{id}`. No sign-in needed. Rate limited per IP and per phone number. Admin reads the stored requests with `GET /leads` (CursorPage, newest first, no filters yet). |
| `/agents` | agents | `agents.py` | Agent directory, profiles, interactions. |
| `/amenities` | amenities | `amenities.py` | Amenity catalog. `CursorPage[Amenity]`. |
| `/upload` | upload | `upload.py` | Cloudinary media uploads. `folder_type` is a `StorageFolderType` enum on every upload route. Batch returns one result per file. Batch limits: 20 files (400 `BATCH_TOO_MANY_FILES`) and 200 MB total (413 `BATCH_TOO_LARGE`). Presign returns `signature`, `api_key`, `timestamp` and `public_id`. Image and video public_ids have no extension; raw files keep it. Documents are stored as Cloudinary `authenticated` assets. `/upload` and `/upload/batch` return 422 `FOLDER_TYPE_NOT_ALLOWED` for folder types that need a property or scene id; use `/upload/presigned` for them. |
| (none) | core | `core.py` | Misc: pages, FAQs, bug reports, app versions. |
| `/content` | content | `content.py` | Public generated content. `GET /content/{entity_type}/{slug}?locale=` serves `auto` and `approved` blocks with `s-maxage` cache headers. `GET /content/manifest` lists served rows (`truncated` is true past `limit`). |
| `/admin/content` | content-admin | `admin_content.py` | `POST /run` (header `X-Cron-Secret`, bounded batch, returns `next_after` and `done`), `GET /review` (admin, CursorPage, filters), `PATCH /{id}/status` (admin), `POST /market-digest` (header `X-Cron-Secret`, weekly Gurugram data digest saved through the blog service). |
| `/blog` | blog | `blog.py` | Blog posts, categories, tags, SEO fields. |
| `/flatmates` | flatmates, flatmates-admin | `flatmates.py`, `flatmates_admin.py` | Two routers share the prefix. Admin handles moderation. |
| `/notifications` | notifications | `notifications.py` | Notification inbox (`GET /me`, read state per delivery), device tokens (`/devices/register`, `/devices/unregister`), admin typed and marketing sends. Topic sends return 409. |
| (root) | oauth | `oauth/` | OAuth 2.1 endpoints for MCP. Mounted at root for MCP compatibility. |
| `/pm/dashboard` | pm-dashboard | `pm_dashboard.py` | PM owner/agent overview. |
| `/pm/properties` | pm-properties | `pm_properties.py` | Managed property CRUD. |
| `/pm/assignments` | pm-assignments | `pm_assignments.py` | Owner-to-RM assignments. |
| `/pm/applications`, `/pm/public` | pm-applications, pm-public | `pm_applications.py` | Rental applications. Public router for applicant-facing flows. |
| `/pm/tenants` | pm-tenants | `pm_tenants.py` | Tenant management. |
| `/pm/leases` | pm-leases | `pm_leases.py` | Lease lifecycle. |
| `/pm/rent` | pm-rent | `pm_rent.py` | Rent charges and payments. |
| `/pm/expenses` | pm-expenses | `pm_expenses.py` | Owner expenses. |
| `/pm/maintenance` | pm-maintenance | `pm_maintenance.py` | Maintenance requests and work orders. |
| `/pm/documents` | pm-documents | `pm_documents.py` | PM document storage. |
| `/pm/inspections` | pm-inspections | `pm_inspections.py` | Move-in/move-out checklists. |
| `/pm/reports` | pm-reports | `pm_reports.py` | PM financial and occupancy reports. |
| `/design-studio` | design-studio | `design_studio.py` | AI image generation (auth required). |
| `/vastu` | vastu | `vastu.py` | Vastu checker (public). |
| `/deeplinks` | deeplinks | `app/api/deeplinks.py` | Public deep-link fallback pages and well-known files (no auth). The JSON link-generation API was removed. |
| `/tours` | tours | `tours.py` | Virtual tour CRUD. Includes `POST /tours/{tour_id}/generate-3d` (textured skybox mesh AIJob). |
| `/scenes` | scenes | `scenes.py` | Tour scenes. Includes `POST /scenes/{scene_id}/stitch` (cloud panorama stitch AIJob). |
| `/hotspots` | hotspots | `hotspots.py` | Scene hotspots. |
| `/tours` | floor-plans | `floor_plans.py` | Floor plan CRUD. Includes `POST /tours/{tour_id}/floor-plans/generate`, which draws a schematic plan from the tour's analyzed rooms and doorway links (replaces the previous AI-estimated row). |
| `/dashboard` | dashboard | `dashboard.py` | Tour analytics dashboard. |
| `/public` | public-tours | `public.py` | Unauthenticated tour viewer. |
| `/ai` | ai | `ai.py` | Tour AI processing endpoints. Includes `POST /ai/tours/{tour_id}/connect-spatial` (re-runs doorway linking on an existing tour). |
| `/lab` | lab | `lab.py` | 3D Splat Lab: Gaussian splatting pipeline jobs (create/start/upload/list). `POST /jobs/{id}/start` runs the Daytona sandbox pipeline (`lab_pipeline.py`) when `DAYTONA_API_KEY` is set, else the Modal GPU worker. |
| `/custom-domains` | custom-domains | `custom_domains.py` | Vanity domain DNS verification. |
| `/agent` | ai-agent | `agent_chat.py` | Pydantic AI agent chat (auth + public). |
| `/data-hub` | data-hub | `data_hub/` | Bank auctions, RERA, circle rates, gazette, jamabandi, zoning, neighbourhood. |
| (root) | webhooks | `webhooks/` | Inbound integrations. Router carries its own `/webhooks/auth` prefix. |

## Health and docs

- `/health` - root-level health check (Railway healthcheck target)
- `/api/v1/health` - redirects to `/health`
- `/api/v1/docs` - Swagger UI
- `/api/v1/redoc` - ReDoc
- `/api/v1/openapi.yaml` - OpenAPI spec

## Flatmates compatibility endpoint

The `/flatmates` group now exposes a per-user compatibility endpoint at:

- `GET /flatmates/profiles/{user_id}/compatibility` — returns a `CompatibilityBreakdown` with per-dimension scores, summaries, and top-match chips.

The engine is implemented in `app/services/flatmates/compatibility.py` and is also used to populate `match_percentage` on `FlatmatesPeer` results and `compatibility_score` on `Property` detail/search/recommendation responses.

## Conventions

- Endpoints are thin controllers. They validate input via Pydantic schemas, enforce auth through dependencies, and delegate to `app/services/`.
- List endpoints return 3-tuples `(items, next_cursor, has_more)` for keyset cursor pagination (June 2026 refactor).
- Every non-2xx JSON response uses one envelope: `{"error": {"code", "message", "details"?}}`. Validation errors (422) list `details.fields` as `[{"field", "msg", "type"}]`. Build error bodies with `error_body` / `error_response` in `app/infrastructure/errors.py`.
- Every 422 body has `details.fields` (an empty list when no field applies), so clients read one shape.
- Unknown query keys return 422 `VALIDATION_ERROR` with `query.<name>` in `details.fields`. Accepted everywhere: `cursor`, `limit`, `include_total`.
- A cursor value of the wrong type, an id out of range, or a UTC offset of 16 hours or more returns 400 `INVALID_CURSOR`. The check runs inside `keyset_filter` and `read_keyset`, so every list is covered.
- `docs/openapi.json` is the wire contract. `app/infrastructure/openapi.py` adds the `ErrorEnvelope` and `ValidationErrorEnvelope` components, a `default` error response and a 422 on every operation, the `HTTPBearer` scheme with `security` per operation, and standard numeric bound keywords.
- `GET /agent/conversations/{id}/messages` (bare list) is removed. Use `GET /agent/conversations/{id}/messages/page`.
- A cursor is bound to the request filters. A cursor sent with other filters returns 422 `INVALID_CURSOR`.
- Streaming endpoints (SSE, AI agent chat) release the main DB session and use the background pool via `get_bg_db`.
- MCP routes (`/mcp`, `/mcp-admin`) are mounted outside `api_router` and bypass the request ID middleware for streaming tool calls.
