# Glossary

Domain and technical vocabulary used across the 360 Ghar codebase, docs, and wiki. Domain terms come from Indian real estate and the platform's six modules; technical terms are specific to this backend.

## Domain terms

- **Ghar** — Hindi for "home". The platform brand.
- **Ghar Core** — Buy/rent marketplace module: properties, swipes, visits, agents.
- **360 Stays** — Short-stay booking module for hotels and vacation rentals.
- **Flatmates** — Roommate and PG discovery module with swipe matching, conversations, and moderation.
- **Property Management (PM)** — Landlord module: leases, rent, maintenance, documents, inspections, reports.
- **360 Virtual Tours** — 360 degree tour builder with scenes, hotspots, floor plans, and AI jobs.
- **360 Data Hub** — Data aggregation module: scrapers for auctions, RERA, circle rates, gazette, jamabandi, zoning, neighbourhood.
- **PG** — Paying Guest accommodation. A property type in the flatmates module.
- **Swipe** — Tinder-like property or user interaction: `like`, `pass`, `super_like`. Recorded in `UserSwipe`.
- **Visit** — A scheduled property tour or flatmate meet, coordinated through agents.
- **Vastu** — Vastu Shastra, the traditional Hindu system of architecture. The analyzer in `app/services/ai/vastu/` checks floor plan compliance.
- **RERA** — Real Estate (Regulation and Development) Act, 2016. Indian real estate regulator. The data hub scrapes RERA projects and complaints.
- **Jamabandi** — Hindi/Punjabi term for land revenue records (ownership documents). Scraped by the data hub.
- **Circle Rate** — Government-set minimum property price per area, used for stamp duty. Scraped by the data hub.
- **Gazette** — Official government notifications: land acquisition, rate revisions, policy and CLU changes.
- **SARFAESI** — Securitisation and Reconstruction of Financial Assets and Enforcement of Securities Interest Act. A source of bank auction listings.
- **RM** — Relationship Manager. Owner-to-RM assignments in the PM module.

## Technical terms

- **MCP** — Model Context Protocol. Two servers (`/mcp` for users, `/mcp-admin` for agents/admins) for LLM clients. Streamable HTTP transport, protocol version `2025-11-25`.
- **AppsSDKFastMCP** — The backend's `FastMCP` subclass (`app/mcp/apps_sdk.py`) adding OAuth 2.1 + PKCE, dual widget metadata (standard MCP + OpenAI aliases), and Apps SDK compliance.
- **SSE** — Server-Sent Events. `SSEEventBus` in `app/core/sse.py` provides per-user pub/sub at `GET /api/v1/flatmates/sse`. Events: `new_match`, `new_message`, `conversation_updated`, `visit_updated`, `listing_status_changed`, `new_notification`.
- **pgvector** — PostgreSQL extension for vector embeddings. Powers semantic property search via the `property_embeddings` table.
- **NullPool** — SQLAlchemy pool that opens a fresh connection per request. Enabled in serverless mode (`SERVERLESS_ENABLED=True`) so the app scales to zero behind PgBouncer.
- **3-tuple return** — Paginated list endpoints return `(items, next_cursor, has_more)` instead of a bare list. Applied across properties, users, agents, bookings, visits, blog.
- **tool_ops** — Shared MCP tool business logic in `app/mcp/tool_ops/`. Called by both MCP servers and the AI agent tool bridge.
- **is_seed_data** — Flag on `users`, `agents`, `properties` marking seed/demo records. The clear script deletes child records via FK joins to seed parents only.
- **Background pool** — A separate SQLAlchemy engine (`get_bg_db`) for schedulers, scrapers, and streaming endpoints so long-running work doesn't consume the request pool.

## See also

- [Project overview](index.md) and [architecture](architecture.md).
