# 360 Ghar Backend

360 Ghar is a unified real estate platform backend built with FastAPI, PostgreSQL+PostGIS, SQLAlchemy 2.x async, and Pydantic v2. It powers six integrated modules from a single async codebase, authenticates against Supabase Auth, and exposes both a REST API at `/api/v1/*` and two MCP servers at `/mcp` and `/mcp-admin` for LLM clients.

## Overview video

[![360 Ghar Backend Overview](video/overview.mp4)](video/overview.mp4)

A 2-3 minute silent walkthrough of the platform's six modules and architecture.

## The six modules

| Module | Purpose |
|---|---|
| [Ghar Core](features--ghar-core) | Buy/rent marketplace with swipe-based discovery, geospatial search, agent coordination, and visits. |
| [360 Stays](features--stays) | Short-stay bookings with availability checks and dynamic pricing. |
| [360 Flatmates](features--flatmates) | Roommate and PG discovery with swipe matching, conversations, and moderation. |
| [Property Management](features--property-management) | Landlord tools: leases, rent collection, maintenance, documents, inspections, reports. |
| [360 Virtual Tours](features--virtual-tours) | Immersive 360 degree tour builder with AI hotspot generation and analytics. |
| [360 Data Hub](features--data-hub) | Real estate data aggregation: bank auctions, RERA, circle rates, gazette, jamabandi, zoning. |

## Start here

- [Architecture](overview--architecture) — layered structure, request flow, MCP architecture with diagrams.
- [Getting started](overview--getting-started) — prerequisites, install, build, test, run.
- [By the numbers](by-the-numbers) — codebase statistics snapshot.
- [Glossary](overview--glossary) — domain vocabulary (ghar, vastu, RERA, jamabandi, flatmates, MCP).

## Browse by lens

- [Features](features--index) — cross-cutting product capabilities (11 pages).
- [Systems](systems--index) — internal building blocks (8 pages).
- [Primitives](primitives--index) — foundational domain objects (8 pages).
- [API](api--index) — REST surface map and authentication.

## Operations

- [Deployment](deployment) — Railway, Docker, serverless mode.
- [Security](security) — auth, rate limiting, security headers, OAuth.
- [Monitoring](how-to-monitor--index) — logging, Sentry, health checks.
- [Design decisions](background--design-decisions) — ADRs and rationale.
- [Pitfalls](background--pitfalls) — overlapping bookings, serverless trade-offs, anti-patterns.

## Reference

- [Configuration](reference--configuration) — environment variables.
- [Data models](reference--data-models) — entity relationships with ERD.
- [Dependencies](reference--dependencies) — Python and JavaScript dependencies.
- [Maintainers](maintainers) — subsystem ownership.

## Repository

- [Source code](https://github.com/360ghar/360ghar-backend)
- [README](https://github.com/360ghar/360ghar-backend#readme)
- [CLAUDE.md](https://github.com/360ghar/360ghar-backend/blob/main/CLAUDE.md) — coding guidelines and architecture reference.
- [AGENTS.md](https://github.com/360ghar/360ghar-backend/blob/main/AGENTS.md) — operating contract for contributors and agents.
