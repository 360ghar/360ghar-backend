# Project overview

360 Ghar is a unified real estate platform backend built on FastAPI, PostgreSQL with PostGIS, SQLAlchemy 2.x async, and Pydantic v2. It runs six integrated modules from a single async codebase, authenticates against Supabase Auth, and exposes both a REST surface at `/api/v1/*` and two MCP servers at `/mcp` and `/mcp-admin` for LLM clients. The codebase is roughly 68,000 lines of Python across 352 source files, with 333 REST endpoints and 40+ MCP tools.

## The six modules

| Module | Purpose | Key paths |
|---|---|---|
| **Ghar Core** | Buy/rent marketplace with swipe-based discovery, geospatial search, agent coordination, and visits. | `app/api/api_v1/endpoints/properties.py`, `swipes.py`, `visits.py`, `agents.py` |
| **360 Stays** | Short-stay bookings for hotels, vacation rentals, and temporary stays with availability checks and dynamic pricing. | `bookings.py`, `app/services/booking.py` |
| **360 Flatmates** | Roommate and PG discovery with swipe matching, conversations, moderation, QnA, and visit scheduling. | `app/services/flatmates/` |
| **Property Management** | Landlord and PM tools: leases, tenants, rent collection, maintenance, documents, inspections, reports. | `app/services/pm_*.py`, endpoints `pm_*.py` |
| **360 Virtual Tours** | Immersive 360 degree tour builder with scenes, hotspots, floor plans, AI jobs, and analytics. | `app/services/tour/`, `app/services/tour_ai/` |
| **360 Data Hub** | Real estate data aggregation: bank auctions, RERA projects/complaints, circle rates, gazette, jamabandi, zoning, neighbourhood. | `app/services/data_hub/` |

## Who uses it

- **Property seekers** discover homes through swipe feeds and semantic search, schedule visits, and chat with agents.
- **Owners and landlords** list properties, manage leases and rent, track maintenance, and view portfolio dashboards.
- **Agents** coordinate visits, manage assignments, and run portfolio operations via the admin MCP server.
- **LLM clients** (ChatGPT, Claude Desktop, Cursor, VS Code Copilot) call MCP tools and render interactive widgets.
- **Platform admins** moderate flatmate listings, manage notifications, and run data hub scrapers.

## Tech stack

Python 3.10+ with FastAPI, SQLAlchemy 2.x async, Pydantic v2, httpx, APScheduler, pgvector, GeoAlchemy2, Supabase, FastMCP 3.0.1, Pydantic AI, Pillow, Cloudinary, and Sentry. Dependencies are managed with `uv` and locked in `uv.lock`. PostGIS powers geospatial queries, pgvector powers semantic search, and Redis backs the cache and pub/sub layers.

## Key wiki pages

- [Architecture](architecture.md) — layered structure, request flow, MCP architecture with diagrams.
- [Getting started](getting-started.md) — prerequisites, install, build, test, run commands, env config.
- [Glossary](glossary.md) — domain and technical vocabulary used across the codebase and docs.
- [Patterns and conventions](../how-to-contribute/patterns-and-conventions.md) — async-first, service layer, shared httpx clients, ruff rules.

Other areas worth bookmarking once written: API authentication, MCP servers, infrastructure, the data model reference, and feature pages for each module.

## Where to start reading code

- `app/factory.py` — thin composition root that builds the FastAPI app.
- `app/infrastructure/` — lifespan, middleware, routing, MCP mounts, scheduler.
- `app/api/api_v1/api.py` — REST router composition.
- `app/main.py` — entrypoint, Sentry init, `/health` and `/config` probes.
- `app/core/config.py` — settings.
- `app/models/enums.py` — 50+ enums that shape every domain object.

The codebase has only two `TODO`/`FIXME` markers, so what you read is what ships. For the full operating contract, see `CLAUDE.md` and `AGENTS.md` at the repo root.
