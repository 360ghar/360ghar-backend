---
name: qa-backend
description: >
  QA tests for the 360Ghar backend API. Tests REST endpoints, MCP tools,
  auth boundaries, and critical user flows via curl/httpx API calls.
  Covers property discovery, visits, bookings, flatmates, PM, tours, vastu,
  data hub, blog, and OAuth.
---

# QA Backend API

## Testing Target

**Strategy: Local dev server.** This project does NOT use Vercel/Netlify preview deployments (backend only).

1. Start the dev server locally: `uv run python run.py` or `python run.py`
2. Poll `http://localhost:3600/health` until it responds with `"status": "healthy"`
3. Use `http://localhost:3600` as the base URL for all API tests

**CRITICAL:** The sub-skill MUST NEVER fall back to a remote environment (dev, staging, prod) when testing a PR branch. Remote environments run different code -- testing against them tells you nothing about the PR's changes. If the local dev server is not available, report BLOCKED.

## Authentication in CI

When running in CI or automated mode, auth tokens are provided via environment variables:
- `QA_USER_TOKEN` -- Supabase JWT for a regular user
- `QA_AGENT_TOKEN` -- Supabase JWT for an agent
- `QA_ADMIN_TOKEN` -- Supabase JWT for an admin
- `QA_GUEST` -- No token needed (unauthenticated)

These are Supabase JWT access tokens. Pass them as `Authorization: Bearer $QA_USER_TOKEN` in API requests.

For new user signup during test runs, use the Supabase Auth API:
```
POST {SUPABASE_URL}/auth/v1/signup
Headers: apikey: {SUPABASE_PUBLISHABLE_KEY}
Body: { "email": "qa+signup_{RUN_ID}@360ghar.com", "password": "..." }
```

## API Base URL

```
BASE_URL=http://localhost:3600/api/v1
```

## Available Test Flows

The orchestrator picks only the flows relevant to the current diff. Each flow label maps to the code areas it covers.

### Flow 1: Property Discovery (guest, user)
**Covers:** `app/api/api_v1/endpoints/properties.py`, `app/services/property.py`, `app/repositories/`, `app/models/properties.py`
- `GET /properties/` -- list properties with pagination and filters
- `GET /properties/{id}` -- get property detail
- `GET /amenities/` -- list amenities
- Test geospatial search: `GET /properties/?lat=28.4595&lng=77.0266&radius_km=10`
- Test full-text search: `GET /properties/?search=gurgaon`
- Test type/purpose filters: `GET /properties/?property_type=apartment&purpose=rent`
- **Auth boundary:** Guest can search; unauthenticated users can see property listings
- **Success criteria:** Returns 200 with property list; detail returns full property data

### Flow 2: Swipe Discovery (user)
**Covers:** `app/api/api_v1/endpoints/swipes.py`, `app/services/swipe.py`
- `GET /swipes/feed` -- get discovery feed for swiping
- `POST /swipes/` -- record like/pass on a property
- `GET /swipes/shortlist` -- get liked properties
- **Auth boundary:** Requires authentication; guest gets 401
- **Success criteria:** Feed returns properties; swipe recorded; shortlist contains liked properties

### Flow 3: Visit Scheduling (user, agent)
**Covers:** `app/api/api_v1/endpoints/visits.py`, `app/services/visit.py`
- `POST /visits/` -- schedule a visit (requires auth)
- `GET /visits/` -- list user's visits
- `GET /visits/{id}` -- get visit details
- `PUT /visits/{id}/cancel` -- cancel a visit
- **Auth boundary:** Guest cannot schedule visits (401); user can manage own visits
- **Success criteria:** Visit created with scheduled status; appears in list; can be cancelled
- **Cleanup:** Cancel any created visits after testing

### Flow 4: Short-Stay Booking (user)
**Covers:** `app/api/api_v1/endpoints/bookings.py`, `app/services/booking.py`
- `GET /bookings/check-availability/{property_id}` -- check availability
- `POST /bookings/` -- create a booking
- `GET /bookings/` -- list user's bookings
- `GET /bookings/{id}` -- get booking details
- `PUT /bookings/{id}/cancel` -- cancel a booking
- **Auth boundary:** Requires authentication; guest gets 401
- **Success criteria:** Booking created with pending status; availability checked; can be cancelled
- **Cleanup:** Cancel any created bookings after testing

### Flow 5: Property CRUD -- Owner (user)
**Covers:** `app/api/api_v1/endpoints/properties.py` (POST/PUT/DELETE), `app/services/property.py`, `app/models/properties.py`, `app/schemas/property.py`
- `POST /properties/` -- create a new property listing
- `GET /properties/{id}` -- verify creation
- `PUT /properties/{id}` -- update property
- `DELETE /properties/{id}` -- delete property
- **Auth boundary:** Requires authentication; guest gets 401
- **Success criteria:** Property created with available status; updates reflected; deletion returns 204
- **Cleanup:** Delete any created properties after testing

### Flow 6: Property Management (user, agent, admin)
**Covers:** `app/api/api_v1/endpoints/pm_*`, `app/services/pm_*`, `app/models/pm_*`
- `GET /pm/properties` -- list managed properties
- `GET /pm/leases` -- list leases
- `POST /pm/maintenance` -- create maintenance request
- `GET /pm/rent/` -- view rent status
- `GET /pm/dashboard` -- dashboard overview
- **Auth boundary:** Requires authentication; different roles see different data
- **Success criteria:** Managed properties listed; leases accessible; maintenance request created
- **Cleanup:** Delete test maintenance requests via API if possible

### Flow 7: Flatmates (user)
**Covers:** `app/api/api_v1/endpoints/flatmates.py`, `app/services/flatmates.py`, `app/models/social.py`, `app/schemas/flatmates.py`
- `POST /flatmates/profile` -- create flatmate profile
- `GET /flatmates/discover` -- discover flatmates
- `GET /flatmates/profile/me` -- get own profile
- `PUT /flatmates/profile` -- update profile
- **Auth boundary:** Requires authentication; guest gets 401
- **Success criteria:** Profile created; discovery returns results; profile updates work

### Flow 8: 360 Virtual Tours (user, guest)
**Covers:** `app/api/api_v1/endpoints/tours.py`, `app/services/tour.py`, `app/models/tours.py`
- `GET /public/tours` -- list public tours (guest)
- `GET /tours/` -- list user's tours (auth)
- `POST /tours/` -- create a tour
- `GET /tours/{id}` -- get tour details
- **Auth boundary:** Public tours accessible to guest; user's tours require auth
- **Success criteria:** Tour created with draft status; public tours listed

### Flow 9: MCP Tools (user, agent, admin)
**Covers:** `app/mcp/user_server.py`, `app/mcp/admin/`, `app/mcp/tool_ops/`, `app/mcp/chatgpt/`
- Send JSON-RPC to `/mcp` with `tools/call` for user tools
- Send JSON-RPC to `/mcp-admin` with `tools/call` for admin tools
- Test `discovery_search` (guest)
- Test `owner_properties_list` (auth)
- Test `agent_properties_list` (agent auth)
- Test `admin_system_status` (admin auth)
- **Auth boundary:** User MCP has guest + auth tools; Admin MCP requires agent/admin
- **Success criteria:** Tools return structured responses; auth-required tools return auth challenge without token

### Flow 10: Blog (guest, user)
**Covers:** `app/api/api_v1/endpoints/blog.py`, `app/services/blog.py`
- `GET /blog/posts` -- list blog posts (public)
- `GET /blog/posts/{slug}` -- get blog post
- `GET /blog/categories` -- list categories
- `GET /blog/tags` -- list tags
- **Auth boundary:** Public read access; creation requires auth
- **Success criteria:** Posts listed; post detail returns content

### Flow 11: Vastu AI (guest)
**Covers:** `app/api/api_v1/endpoints/vastu.py`, `app/services/ai/vastu/`
- `POST /vastu/analyze` -- analyze property vastu (public)
- **Success criteria:** Returns vastu analysis with score and recommendations
- **Note:** This calls AI providers; may take 10-30 seconds. Increase timeout.

### Flow 12: OAuth/MCP Auth Flow (guest)
**Covers:** `app/api/api_v1/endpoints/oauth.py`, `app/mcp/auth_provider.py`
- `GET /.well-known/oauth-protected-resource` -- discover OAuth metadata
- `GET /.well-known/oauth-protected-resource/mcp` -- MCP resource metadata
- `GET /.well-known/openid-configuration` -- OIDC discovery
- `POST /mcp/oauth/register` -- dynamic client registration
- **Success criteria:** Well-known endpoints return valid OAuth 2.1 metadata; registration works

### Flow 13: Data Hub (guest)
**Covers:** `app/api/api_v1/endpoints/data_hub.py`, `app/services/data_hub/`, `app/models/data_hub.py`
- `GET /data-hub/bank-auctions` -- list bank auctions
- `GET /data-hub/circle-rates` -- list circle rates
- `GET /data-hub/rera-projects` -- list RERA projects
- `GET /data-hub/neighbourhoods` -- neighbourhood data
- **Auth boundary:** Public read access
- **Success criteria:** Data hub endpoints return paginated results

## Auth Boundary Tests

For every authenticated endpoint, verify the following auth boundaries:

| Endpoint Type | Guest | User | Agent | Admin |
|---|---|---|---|---|
| Public read (properties, blog, data-hub, vastu) | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| User actions (swipe, visit, booking) | :x: 401 | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| Owner/tenant PM | :x: 401 | :white_check_mark: (own) | :white_check_mark: (assigned) | :white_check_mark: |
| Agent PM tools | :x: 401 | :x: 403 | :white_check_mark: | :white_check_mark: |
| Admin endpoints | :x: 401 | :x: 403 | :x: 403 | :white_check_mark: |
| MCP user tools (guest) | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| MCP user tools (auth) | :no_entry: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| MCP admin tools | :no_entry: | :no_entry: | :white_check_mark: | :white_check_mark: |

## Common API Patterns

### Pagination
Most list endpoints support `page` and `page_size` query params:
```
GET /api/v1/properties/?page=1&page_size=10
```

### Error Response Format
All errors follow this structure:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message"
  }
}
```

### Authentication Header
```
Authorization: Bearer <supabase-jwt-token>
```

## Known Failure Modes

1. **Dev server not running.** If `curl -sf http://localhost:3600/health` fails, the dev server needs to be started. Run `uv run python run.py` in the background.

2. **Supabase token expired.** Supabase JWTs expire after 30 minutes (configurable). If auth tests suddenly return 401, the token may have expired. Re-authenticate via Supabase Auth API.

3. **PostGIS extension missing.** Geospatial queries (`lat`/`lng`/`radius_km` params) fail if the database doesn't have the PostGIS extension. Check with `SELECT extname FROM pg_extension WHERE extname = 'postgis'`.

4. **Redis not running.** Cache-dependent endpoints may fail silently if Redis is down. Start with `docker-compose up -d redis`.

5. **AI provider timeouts.** Vastu analysis and AI agent calls may take 10-30 seconds. Use `--max-time 60` with curl for these endpoints.

6. **Empty database.** Property search returns empty if no data is loaded. Run `uv run python seed_data/01_load_all.py --only hardcoded,seed` to seed test data.

7. **MCP tool auth challenge format.** MCP tools requiring auth return a 401 with `WWW-Authenticate: Bearer resource_metadata="..."` header. This is expected -- not a failure.

8. **Rate limiting.** Global rate limit is 100 req/min. If tests hit this, add small delays between batches.
