# Lore

A short history of the 360Ghar backend. Dates are month-precision where the exact day is uncertain; commit-level dates appear where they matter. The project is young, so this is mostly growth narrative rather than legacy cleanup.

## Era 1: Foundation (June to August 2025)

The repository begins with the June 29, 2025 "fastapi" commit: a FastAPI scaffold, the first property and user models, and the data population pipeline. Auth against Supabase lands in the same window, along with a logging refactor and the move to async database operations. By the end of August, Ghar Core is walkable end to end.

The property and user models from June 2025 are the longest-standing artifacts in the codebase. They predate every other module and have been adapted, not replaced, since.

## Era 2: Blog and models (October 2025)

On October 1, 2025 a model refactor lands alongside the first blog APIs. The blog surface grows to include AI generation, SEO fields, and an auto-publish scheduler, but the seed is this October commit. This is also roughly when the model layer stabilizes into the shape now documented in [systems/models.md](systems/models.md).

## Era 3: Notifications and caching (November 2025 to January 2026)

November 30, 2025 brings notification and email services. The work expands on January 1, 2026 with the cache subsystem (memory plus Redis backends) and the first property management features. The MCP server, built on FastMCP, also appears in this window. The pattern of one shared `AsyncIOScheduler` and shared `httpx.AsyncClient` singletons dates from here.

## Era 4: Data Hub (March 2026)

March 28, 2026 is the data hub day. A base scraper class lands, followed by 11 scraper service files covering bank auctions, RERA, circle rates, gazette, jamabandi, zoning, and neighbourhood data. Six data categories are wired into the scheduler. The hub grows to 26 scraper modules over the following weeks.

## Era 5: Major refactor (May 2026)

May 2026 is the biggest structural month. Monolith service files are decomposed into packages: flatmates becomes a seven-module package, the MCP server is restructured, and the data hub is improved. Database pool tuning and blog enhancements ride along. The flatmates social feature, with swipe matching, conversations, moderation, and SSE event delivery, is the headline addition.

## Era 6: Flatmates deepening (May to June 2026)

Through late May and June 2026 the flatmates module thickens: interactions, super likes, moderation flows, profile filters, and property and move-in filters. The SSE event bus settles into its current set of event types. The data hub also picks up improvements in this window.

## Era 7: API standardization (June 2026, ongoing)

June 2026 is the current active work. Cursor pagination is being rolled out across users, agents, bookings, visits, blog, and properties. Service functions return a 3-tuple of `(items, next_cursor, has_more)`, with keyset cursoring on `created_at`. The latest commits on `main` adapt callers to this shape. This refactor is not finished; expect more endpoints to migrate.

## Patterns that have held

A few decisions from the early months are still load-bearing:

- Property and user models from June 2025, adapted in place.
- Supabase JWT auth from June 2025, with the `PROVIDER_UNREACHABLE` versus 401 distinction added later.
- The single shared scheduler and shared httpx clients from January 2026.
- The overlapping-bookings business rule, deliberately no double-booking guards, from the bookings module's inception.

## What is not here

There are no deprecated features, no major rewrites, and no tags or releases. The codebase has only 2 `TODO`/`FIXME` markers, which suggests decisions have been made rather than deferred. With 182 commits over roughly a year and 2 contributors, the trajectory is incremental and additive rather than cyclical.

## Where to look next

- [by-the-numbers.md](by-the-numbers.md) for the current size and churn figures.
- [how-to-contribute/index.md](how-to-contribute/index.md) for how to pick up work against the current state of `main`.
- [background/design-decisions.md](background/design-decisions.md) for the ADRs that back the patterns above.
