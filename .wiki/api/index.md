# API

360Ghar exposes a single REST surface at `/api/v1/*` plus two MCP servers at `/mcp` and `/mcp-admin`. This page maps the REST route groups. For the MCP surface, see [features/mcp-servers.md](../features/mcp-servers.md). For auth, see [authentication.md](authentication.md).

Active contributors: Saksham, Ravi

## Router composition

All REST routers are mounted by `app/api/api_v1/api.py` onto a single `APIRouter` named `api_router`, which the app factory mounts at `/api/v1`. The file imports 38 endpoint modules and calls `include_router` for each, with explicit `prefix` and `tags`. Tags drive the OpenAPI grouping in Swagger UI at `/api/v1/docs`.

## Route groups

| Prefix | Tag | Module | Notes |
|---|---|---|---|
| `/auth` | auth | `app/api/api_v1/endpoints/auth.py` | Account deletion, config. No login/refresh/logout - clients use Supabase SDK. |
| `/users` | users | `users.py` | Profile, preferences, account. |
| `/properties` | properties | `properties.py` | Marketplace listings, search, recommendations, cursor-paginated. |
| `/visits` | visits | `visits.py` | Property tours and flatmate meetings. |
| `/bookings` | bookings | `bookings.py` | 360 Stays short-stay reservations. |
| `/swipes` | swipes | `swipes.py` | Tinder-like property and user interactions. |
| `/payments` | payments | `payments.py` | Razorpay integration. |
| `/agents` | agents | `agents.py` | Agent directory, profiles, interactions. |
| `/amenities` | amenities | `amenities.py` | Amenity catalog. |
| `/upload` | upload | `upload.py` | Cloudinary media uploads. |
| (none) | core | `core.py` | Misc: pages, FAQs, bug reports, app versions. |
| `/blog` | blog | `blog.py` | Blog posts, categories, tags, SEO fields. |
| `/flatmates` | flatmates, flatmates-admin | `flatmates.py`, `flatmates_admin.py` | Two routers share the prefix. Admin handles moderation. |
| `/notifications` | notifications | `notifications.py` | In-app notification center. |
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
| `/tours` | tours | `tours.py` | Virtual tour CRUD. |
| `/scenes` | scenes | `scenes.py` | Tour scenes. |
| `/hotspots` | hotspots | `hotspots.py` | Scene hotspots. |
| (none) | floor-plans | `floor_plans.py` | Floor plan upload and processing. |
| `/dashboard` | dashboard | `dashboard.py` | Tour analytics dashboard. |
| `/public` | public-tours | `public.py` | Unauthenticated tour viewer. |
| `/ai` | ai | `ai.py` | Tour AI processing endpoints. |
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

## Conventions

- Endpoints are thin controllers. They validate input via Pydantic schemas, enforce auth through dependencies, and delegate to `app/services/`.
- List endpoints return 3-tuples `(items, next_cursor, has_more)` for keyset cursor pagination (June 2026 refactor).
- Streaming endpoints (SSE, AI agent chat) release the main DB session and use the background pool via `get_bg_db`.
- MCP routes (`/mcp`, `/mcp-admin`) are mounted outside `api_router` and bypass the request ID middleware for streaming tool calls.
