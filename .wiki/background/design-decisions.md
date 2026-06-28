# Design decisions

The four ADRs in `docs/adrs/` document architectural decisions accepted by the 360Ghar team. All four were written on 2026-05-08 (ADR 004 revised 2026-06-06). They describe a target architecture the codebase is migrating toward - the current type-based layout in `app/api/`, `app/services/`, `app/models/` is what ADR 001 proposes to move away from.

Active contributors: Saksham, Ravi

## ADR 001: Domain-Driven Module Structure

File: `docs/adrs/001-domain-module-structure.md`

**Problem.** The current type-based (layered) directory layout organizes code by technical role rather than business domain. A change to the booking flow touches `bookings.py` in endpoints, `booking.py` in services, models in `models/`, schemas in `schemas/`, and MCP tools in `mcp/tool_ops/`. With 40+ service files and 30+ schema modules in flat directories, finding the relevant file for a domain concept requires knowing the project's naming conventions. MCP tool logic lives in `app/mcp/tool_ops/` while the same domain's REST endpoint lives elsewhere, leading to duplicated or divergent authorization.

**Decision.** Migrate to a domain-driven module structure under `app/modules/{domain}/` where each module is self-contained: `api.py`, `service.py`, `repository.py`, `models.py`, `schemas.py`, `mcp.py`, `enums.py`, and a `tests/` directory. Sub-domains (like PM under property) nest further. `app/shared/` holds cross-domain contracts.

**Status.** Accepted but not implemented. `app/modules/` and `app/shared/` exist as reserved placeholders. The current concrete homes (`app/api`, `app/services`, `app/models`, `app/repositories`, `app/mcp`) remain canonical until a domain is migrated.

## ADR 002: Repository Pattern with Protocol Interfaces

File: `docs/adrs/002-repository-protocol-interfaces.md`

**Problem.** The repository pattern is incomplete. `app/repositories/` has `BaseRepository[T]`, `PropertyRepository`, and `PropertyQueryBuilder`, but most services (`booking.py`, `visit.py`, `flatmates.py`, `user.py`) write raw SQLAlchemy queries directly against `AsyncSession`. This couples services to SQLAlchemy, makes unit testing impossible without a real database, and duplicates query logic (filter by user ID, paginate, load relationships) across services.

**Decision.** Introduce `typing.Protocol`-based repository interfaces that define the data access contract for each domain. Services depend on protocols, not on concrete SQLAlchemy repositories. Concrete implementations wrap SQLAlchemy and live in the repository layer. This creates a clean seam for swapping persistence or inserting a caching layer.

**Status.** Accepted. `BaseRepository` and `PropertyRepository` already follow this pattern for the property domain; other domains have not been migrated.

## ADR 003: Event-Driven Side Effects

File: `docs/adrs/003-event-driven-side-effects.md`

**Problem.** Business operations trigger side effects (push notifications, emails, cache invalidation, analytics) that are executed inline as sequential in-service function calls. The notification dispatcher blocks the primary operation's response - if email or FCM is slow, the HTTP response to the client is delayed. Error handling is inconsistent across call sites. There is no ordering guarantee, no deduplication, no replay, and unit tests must mock every side effect.

**Decision.** Introduce a simple in-process event bus that decouples primary business operations from their side effects. Operations emit events; registered handlers react asynchronously in background tasks. Handler failures are isolated from the primary operation. Optional Redis pub/sub extension for multi-process dispatch.

**Status.** Accepted. The `SSEEventBus` in `app/core/sse.py` is a per-user pub/sub for real-time UI updates, not the general-purpose event bus this ADR describes. The notification dispatcher (`app/services/notification_dispatcher.py`) still runs inline. Migration to the event bus is pending.

## ADR 004: Adapter Pattern for External Services

File: `docs/adrs/004-external-service-adapters.md`

**Problem.** The backend integrates with many external HTTP services (Gemini, GLM, Supabase, FCM, email, SMS, Cloudinary, 15+ data hub scrapers). The AI provider layer (`app/services/ai/`) already demonstrates a well-structured adapter pattern with `AIProvider`, `GeminiProvider`, `GLMProvider`, `get_ai_provider()`, and centralized tenacity retries - but other services implement their own error handling inconsistently, some with no retries. There is no circuit breaking: if Gemini is down, every request still tries it and waits for the full timeout cycle. HTTP client setup is duplicated.

**Decision.** Formalize the adapter pattern for all external service integrations. Each external service is wrapped behind an adapter interface that centralizes retry, circuit-breaking, timeout, and health tracking. Business code depends on adapter protocols, not on raw HTTP clients. The shared `httpx.AsyncClient` singletons in `app/core/http.py` (`get_scraper_client`, `get_blog_client`, `get_general_client`, `get_supabase_auth_http_client`) are a step in this direction.

**Status.** Accepted. The shared httpx clients exist and the AI provider factory is the reference implementation. Other services (email, SMS, FCM, scrapers) have not been migrated to the adapter pattern.

## Cross-cutting theme

All four ADRs push in the same direction: decouple. Decouple domains from each other (ADR 001), services from persistence (ADR 002), primary operations from side effects (ADR 003), and business code from external services (ADR 004). The codebase has the seams in place (`app/modules/`, `app/shared/`, `BaseRepository`, `SSEEventBus`, shared httpx clients) but the migration is incremental.
