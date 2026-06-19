# Features

Active contributors: Saksham, Ravi

360 Ghar is a unified real estate platform that bundles six product modules and several cross-cutting capabilities into a single async backend. This section of the wiki covers the user-facing features, one page per module. Each page traces its claims back to source files under `app/` and cross-links the underlying [systems](../systems/infrastructure.md) where relevant.

## Modules

The platform is organised around these feature areas, each with its own REST surface under `/api/v1` and (for several) dedicated [MCP servers](mcp-servers.md) tool surfaces:

- [Ghar Core](ghar-core.md) — the property marketplace. Swipe-based discovery, PostGIS geospatial search, PostgreSQL full-text search, hybrid semantic search over pgvector, and the recent 3-tuple cursor pagination refactor for list endpoints. Covers properties, swipes, visits, and agents.
- [360 Stays](stays.md) — short-stay bookings for hotels, vacation rentals, and temporary accommodation. Covers availability checks, dynamic pricing, the booking lifecycle, and the deliberate overlapping-bookings business rule.
- [Flatmates](flatmates.md) — flatmate and PG discovery with swipe-based matching, conversations, moderation, QnA, and SSE-driven real-time events.
- [Property Management](property-management.md) — the PM system for landlords and relationship managers: leases, rent collection, maintenance, documents, inspections, reports, tenants, applications, and RM assignments.
- [360 Virtual Tours](virtual-tours.md) — immersive 360° tour platform with AI-powered hotspot generation, floor plans, analytics, and custom branded domains.
- [360 Data Hub](data-hub.md) — real estate data aggregation. Twenty-six scraper modules covering bank auctions, RERA projects, circle rates, gazette notifications, jamabandi, zoning, and neighbourhood scores, scheduled by a single APScheduler instance.

## Cross-cutting capabilities

These features span multiple modules and are documented separately:

- [MCP servers](mcp-servers.md) — two Model Context Protocol servers (`/mcp`, `/mcp-admin`) exposing 40+ tools and 11 React widgets to LLM clients via OAuth 2.1 + PKCE. The largest feature surface in the codebase.
- [AI agent](ai-agent.md) — a Pydantic AI conversational agent that streams SSE responses, calls into the same shared tool layer as the MCP servers, and supports both authenticated and guest modes.
- [Blog](blog.md) — AI-generated, SEO-optimised blog content with a daily auto-publish scheduler. Perplexity powers generation; SEO fields are auto-computed from the post body.
- [Notifications](notifications.md) — multi-channel dispatch (push, email, SMS, in-app) driven by a central type registry, with per-user frequency caps and a shared APScheduler job.
- [Vastu](vastu.md) — a public, AI-powered floor plan analyzer that checks compliance with Vastu Shastra principles using the Gemini and GLM vision providers.

## Navigation

Most feature pages follow the same structure: purpose, directory layout, key abstractions, a Mermaid diagram of the control flow, integration points, and entry points for modification. The [MCP servers](mcp-servers.md) and [Property Management](property-management.md) pages are intentionally longer because of their surface area. For the building blocks underneath these features, see the [systems](../systems/infrastructure.md) pages, and for the core domain objects see the [primitives](../primitives/property.md) pages.
