# ADR 001: Domain-Driven Module Structure

**Status:** Accepted

**Date:** 2026-05-08

## Context

The 360Ghar backend currently uses a **type-based (layered) directory layout** where code is organized by technical role rather than business domain:

```
app/
├── api/api_v1/endpoints/   # All REST endpoints in a flat directory
├── services/               # All service modules in a flat directory
├── models/                 # All ORM models in a flat directory
├── schemas/                # All Pydantic schemas in a flat directory
├── repositories/           # All repositories in a flat directory
├── mcp/                    # All MCP servers and tools in a flat directory
├── core/                   # Cross-cutting infrastructure
├── middleware/             # Middleware
└── vector/                 # Vector search
```

This layout has several growing problems:

1. **High coupling across domains.** A change to the booking flow touches `bookings.py` in endpoints, `booking.py` in services, models in `models/`, schemas in `schemas/`, and potentially MCP tools in `mcp/tool_ops/`. Developers must navigate 5+ directories to understand a single feature.

2. **Poor discoverability.** With 40+ service files, 15+ endpoint modules, and 30+ schema modules in flat directories, finding the relevant file for a domain concept requires knowing the project's naming conventions. New contributors struggle to locate code related to a business capability.

3. **Scattered MCP tool logic.** Tool business logic lives in `app/mcp/tool_ops/` while the same domain's REST endpoint lives in `app/api/api_v1/endpoints/` and service logic in `app/services/`. The AI agent `tool_bridge.py` calls tool_ops, but REST endpoints call services directly—leading to duplicated or divergent authorization and validation.

4. **Inconsistent sub-domain organization.** Some domains (property management, AI, data hub, flatmates) already have sub-packages under `services/`, while others (bookings, visits, users) are single flat files. The `app/modules/` directory exists but is nearly empty—signaling an incomplete transition.

5. **Test directory mirrors the flat structure.** Tests are also organized by type (`unit/services/`, `unit/schemas/`, `integration/`) rather than by domain, making it hard to find all tests for a given business capability.

The current `app/api/api_v1/api.py` imports and mounts 30+ endpoint routers in a single file, each from a flat `endpoints/` directory. This file becomes a bottleneck for merge conflicts and makes it difficult to understand which domains the platform exposes.

## Decision

Migrate to a **domain-driven module structure** under `app/modules/{domain}/` where each module is a self-contained unit containing all layers for its domain:

```
app/modules/
├── property/
│   ├── api.py              # FastAPI router(s)
│   ├── service.py          # Business logic
│   ├── repository.py       # Data access (SQLAlchemy)
│   ├── models.py           # ORM models
│   ├── schemas.py          # Pydantic request/response schemas
│   ├── mcp.py              # MCP tool definitions
│   ├── enums.py            # Domain-specific enums
│   └── tests/
│       ├── test_service.py
│       ├── test_api.py
│       └── test_repository.py
├── booking/
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── models.py
│   ├── schemas.py
│   ├── mcp.py
│   └── tests/
├── flatmates/
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── models.py
│   ├── schemas.py
│   ├── mcp.py
│   └── tests/
├── visit/
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── models.py
│   ├── schemas.py
│   ├── mcp.py
│   └── tests/
├── pm/                     # Property Management (sub-domains)
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── models.py
│   ├── schemas.py
│   ├── mcp.py
│   ├── leases.py           # Sub-domain logic
│   ├── rent.py
│   ├── maintenance.py
│   └── tests/
├── tour/
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── models.py
│   ├── schemas.py
│   ├── mcp.py
│   └── tests/
├── datahub/
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── models.py
│   ├── schemas.py
│   ├── mcp.py
│   ├── scrapers/           # Existing scraper modules
│   └── tests/
├── user/
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── models.py
│   ├── schemas.py
│   ├── mcp.py
│   └── tests/
├── agent/                  # Real-estate agents
│   ├── api.py
│   ├── service.py
│   ├── models.py
│   ├── schemas.py
│   └── tests/
├── blog/
│   ├── api.py
│   ├── service.py
│   ├── models.py
│   ├── schemas.py
│   └── tests/
├── vastu/
│   ├── api.py
│   ├── service.py
│   └── tests/
└── ai_agent/
    ├── api.py
    ├── service.py
    ├── tool_bridge.py
    └── tests/
```

### Target Structure Diagram

```
                    ┌─────────────────────────────────┐
                    │          app/main.py             │
                    │   (composition root, lifespan)   │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │     app/api/api_v1/api.py        │
                    │   (re-exports module routers)    │
                    └──────────────┬──────────────────┘
                                   │
           ┌───────────┬───────────┼───────────┬───────────┐
           │           │           │           │           │
    ┌──────▼──────┐ ┌──▼──────┐ ┌──▼──────┐ ┌──▼──────┐ ┌──▼──────┐
    │  property   │ │ booking │ │flatmates│ │  visit   │ │   pm    │  ...
    │   module    │ │ module  │ │ module  │ │ module  │ │ module  │
    ├─────────────┤ ├─────────┤ ├─────────┤ ├─────────┤ ├─────────┤
    │ api.py      │ │ api.py  │ │ api.py  │ │ api.py  │ │ api.py  │
    │ service.py  │ │service  │ │service  │ │service  │ │service  │
    │ repository  │ │repo     │ │repo     │ │repo     │ │repo     │
    │ models.py   │ │models   │ │models   │ │models   │ │models   │
    │ schemas.py  │ │schemas  │ │schemas  │ │schemas  │ │schemas  │
    │ mcp.py      │ │mcp     │ │mcp     │ │mcp     │ │mcp     │
    │ tests/      │ │tests/   │ │tests/   │ │tests/   │ │tests/   │
    └─────────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │      Cross-cutting layer      │
    │  core/  infrastructure/      │
    │  middleware/  shared/        │
    │  vector/                     │
    └──────────────────────────────┘
```

### Module Boundary Rules

1. **No cross-module model imports.** A module may not import ORM models from another module. Cross-module data needs flow through service interfaces or shared schemas in `app/shared/`.

2. **Cross-module service calls go through public APIs.** If the `booking` module needs to check property availability, it calls `property.service.get_availability()`—not the property repository directly.

3. **MCP tools per module.** Each module owns its MCP tool definitions in `mcp.py`. The global MCP server (`app/mcp/`) aggregates tools from modules but does not define new ones.

4. **Shared types live in `app/shared/`.** Cross-domain enums (e.g., `PropertyType`, `UserRole`), common schemas (e.g., `PaginatedResponse`), and shared utilities belong in `app/shared/`, not in any single module.

5. **Infrastructure stays cross-cutting.** Database config, auth, caching, middleware, and logging remain in `app/core/` and `app/infrastructure/`. Modules consume these via dependency injection.

6. **Tests are co-located.** Each module's `tests/` directory contains unit and integration tests for that domain. End-to-end tests remain in `tests/e2e/` at the project root.

### Router Registration

`app/api/api_v1/api.py` becomes a thin re-export layer:

```python
from app.modules.property.api import router as property_router
from app.modules.booking.api import router as booking_router
from app.modules.flatmates.api import router as flatmates_router
# ...

api_router = APIRouter()
api_router.include_router(property_router, prefix="/properties", tags=["properties"])
api_router.include_router(booking_router, prefix="/bookings", tags=["bookings"])
# ...
```

Each module's `api.py` exports a `router: APIRouter` with its sub-paths already configured.

## Consequences

### Positive

- **Feature locality.** All code for a business capability is in one directory. A developer working on bookings only needs to open `app/modules/booking/`.

- **Reduced merge conflicts.** Teams working on different domains modify different directories.

- **Clearer ownership.** Each module has a natural boundary for code review, testing, and documentation.

- **Aligned MCP tooling.** MCP tools for a domain live alongside the service they call, reducing divergence between REST and MCP code paths.

- **Scalable team structure.** Modules map cleanly to team ownership as the organization grows.

- **Better test isolation.** Domain tests are co-located with domain code, making it easier to run tests for a specific module.

### Negative

- **Migration effort.** Moving ~40 service files, ~15 endpoint modules, ~30 schema modules, and ~15 model files is significant work even with an incremental approach.

- **Import path churn.** All imports across the codebase change from `app.services.booking` to `app.modules.booking.service`. This affects tests, MCP servers, and the AI agent tool bridge.

- **Risk of module coupling.** Without enforced boundaries, modules may still import each other's internals, recreating the flat-directory coupling problem within the module structure.

- **Shared model complexity.** Some models (e.g., `User`) are referenced by nearly every domain. These must remain in `app/shared/` or a dedicated `user` module with careful interface design.

- **Legacy import compatibility.** During migration, re-exports from old paths (`app.services.booking`, `app.models.properties`) must be maintained to avoid breaking existing imports.

## Migration Strategy

The migration must be **incremental**, not a big-bang rewrite. Each module is migrated independently, and the system remains fully functional at every step.

### Phase 1: Foundation (1–2 weeks)

1. Create the `app/modules/` directory structure.
2. Move `app/shared/` types: cross-domain enums, common schemas, and shared utilities.
3. Establish backward-compatible re-exports: `app/services/booking.py` → `from app.modules.booking.service import *`.
4. Update `app/api/api_v1/api.py` to import from module routers while keeping the same URL prefixes.

### Phase 2: Independent Domain Migration (per domain, 1–2 weeks each)

Migrate domains one at a time in isolation. For each domain:

1. **Create the module directory** with `__init__.py`.
2. **Move models** from `app/models/` to `app/modules/{domain}/models.py`. Add re-export in `app/models/{domain}.py`.
3. **Move schemas** from `app/schemas/` to `app/modules/{domain}/schemas.py`. Add re-export.
4. **Move service** from `app/services/{domain}.py` (or `app/services/{domain}/`) to `app/modules/{domain}/service.py`. Add re-export.
5. **Move repository** from `app/repositories/` to `app/modules/{domain}/repository.py`. Add re-export.
6. **Move API router** from `app/api/api_v1/endpoints/{domain}.py` to `app/modules/{domain}/api.py`. Update `api.py` import.
7. **Move MCP tools** from `app/mcp/tool_ops/` to `app/modules/{domain}/mcp.py`. Wire into MCP server.
8. **Move tests** from `tests/unit/services/`, `tests/unit/schemas/`, etc. to `app/modules/{domain}/tests/`.
9. **Update all imports** across the codebase. Run full test suite to verify.
10. **Remove re-exports** once all consumers are migrated.

### Recommended Migration Order

1. **blog** — Self-contained, low coupling. Good first migration to validate the pattern.
2. **vastu** — Small, isolated domain.
3. **visit** — Moderate coupling (references property, user).
4. **booking** — Moderate coupling (references property, user).
5. **flatmates** — High internal complexity (conversations, matches, moderation, QnA).
6. **pm** (Property Management) — Large domain with many sub-concerns.
7. **property** — Highest coupling (referenced by most other domains). Migrate last.
8. **user** — Highest coupling. Must be migrated carefully with shared re-exports.

### Phase 3: Cleanup (1 week)

1. Remove all backward-compatible re-exports from legacy directories.
2. Remove empty directories (`app/services/`, `app/models/`, `app/schemas/` once fully migrated).
3. Update `CLAUDE.md`, `AGENTS.md`, and `docs/repo-contract.json`.
4. Update CI test paths.

### Rollback Plan

Each domain migration is independently revertible. If a migration introduces regressions:
- Revert the specific module directory.
- Restore the legacy re-exports (which are still in place during Phase 2).
- No cross-domain rollback is needed.
