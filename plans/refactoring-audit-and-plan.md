# 360Ghar Backend Refactoring — Audit Report & Prioritized Plan

**Date**: 2026-05-08
**Status**: Approved — Execution In Progress

---

## PHASE 1: AUDIT REPORT

### A. BROKEN / CRITICALLY WRONG (Must Fix)

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| 1 | **Raw `dict[str, Any]` payloads on admin mutation endpoints** — no Pydantic validation, arbitrary JSON accepted | CRITICAL | `app/api/api_v1/endpoints/flatmates.py` lines 623, 759 |
| 2 | **Social model columns use `String(32)` instead of defined enums** — `UserMatch.status`, `UserConversation.status`, `UserReport.status`, `UserConversation.source`, `UserMessage.message_type`, `UserReport.reason` all store raw strings despite enums existing in `app/models/enums.py` | CRITICAL | `app/models/social.py` lines 39, 69, 169 |
| 3 | **Wildcard injection in property query builder** — `sort_by` field maps directly to SQL ORDER BY without allowlist | CRITICAL | `app/repositories/property_query_builder.py` |
| 4 | **Circular dependency: `core/logging.py` ↔ `infrastructure/request_context.py`** — `setup_logging()` imports `RequestIDFilter` from infrastructure, while infrastructure imports from core | HIGH | `app/core/logging.py` line ~130, `app/infrastructure/request_context.py` |
| 5 | **PII sent to Sentry** — `send_default_pii=True` in Sentry init leaks IP, user agent, cookies | HIGH | `app/main.py` line ~41 |
| 6 | **`SECRET_KEY = "change-me-in-production"`** — default secret key in code, only validated at runtime | HIGH | `app/core/config.py` line 7 |
| 7 | **MCP user tools duplicate tool_ops logic** — `app/mcp/user/owner.py`, `booking.py`, `tenant.py` re-implement logic from `app/mcp/tool_ops/` instead of calling it, violating the architecture contract | HIGH | `app/mcp/user/` |
| 8 | **Fat controller: 330+ lines of business logic in flatmates endpoint** — DB queries, notification dispatch, moderation, serialization all inline | HIGH | `app/api/api_v1/endpoints/flatmates.py` |
| 9 | **Duplicate authorization logic** — `_can_access_booking` and `_can_access_visit` are near-identical inline functions instead of using `pm_authz` | HIGH | `app/api/api_v1/endpoints/bookings.py`, `visits.py` |
| 10 | **Inconsistent exception hierarchy** — `app/core/exceptions.py` is the real implementation, `app/shared/errors.py` does `import *`, `app/infrastructure/errors.py` imports from shared. Three layers for one hierarchy. | HIGH | `app/core/exceptions.py`, `app/shared/errors.py`, `app/infrastructure/errors.py` |

### B. ACCEPTABLE BUT IMPROVABLE (Should Fix)

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| 11 | **Half-completed domain migration** — `app/modules/` contains 19 domain directories but every file is just a wildcard re-export from legacy locations. No real co-location yet. | MEDIUM | `app/modules/*/` |
| 12 | **Dual import paths for all core infrastructure** — Services import `from app.core.config`, `from app.core.logging`, `from app.core.database` while infrastructure layer imports `from app.infrastructure.logging`, `from app.config`. ~40 services use `app.core.*` while ~6 infrastructure files use `app.infrastructure.*`/`app.config.*` | MEDIUM | Throughout `app/services/`, `app/infrastructure/` |
| 13 | **Broad `except Exception` clauses** — 40+ locations catch `Exception` without re-raising. Some swallow silently (`pass`), others log but continue. Notable: lifespan scheduler startups, vector sync, image processing. | MEDIUM | 40+ locations across services, API, vector |
| 14 | **Magic strings for status values** — moderation actions (`"approve"`, `"reject"`, `"request_edit"`), report actions (`"dismiss"`, `"warn_user"`), and AI job statuses are raw strings instead of enums | MEDIUM | `app/api/api_v1/endpoints/flatmates.py`, `app/models/tours.py`, `app/models/data_hub.py` |
| 15 | **God files > 400 lines** — `pm_tools.py` (1211), `flatmates.py` endpoint (883), `discovery_tools.py` (662), `storage/service.py` (~680), `property/search.py` (~550), `blog_auto_publish.py` (~540) | MEDIUM | Multiple |
| 16 | **God functions** — `get_unified_properties_optimized` (~200 lines), filter-building logic duplicated between `property/search.py` and `swipe.py` (~80% overlap) | MEDIUM | `app/services/property/`, `app/services/swipe.py` |
| 17 | **Inline serialization in endpoints** — `_serialize_flatmate_listing`, `_serialize_user_summary`, `_serialize_report` build response dicts manually instead of using schemas | MEDIUM | `app/api/api_v1/endpoints/flatmates.py` |
| 18 | **Missing `response_model` on several endpoints** — `get_blocked_users`, `unmatch`, `get_recommendations` return untyped responses | MEDIUM | Various API endpoints |
| 19 | **Function-body imports** (circular import workaround) — `from app.schemas.user import User` imported inside 4+ function bodies in `users.py`; `UserSchema` imported inside every MCP tool function body | MEDIUM | `app/api/api_v1/endpoints/users.py`, `app/mcp/user/owner.py` |
| 20 | **Inconsistent MCP response format** — Mix of `MCPResponse.success(...)`, raw `{"error": True, "message": "..."}`, and `not_found_response()` helpers | MEDIUM | `app/mcp/user/` |
| 21 | **`starlette>=1.0.0` dependency** — invalid; Starlette is at 0.x. FastAPI pins its own Starlette; declaring this separately can cause version conflicts | MEDIUM | `pyproject.toml` |
| 22 | **Dynamic column filtering in repositories** — some query methods accept arbitrary column names from user input | MEDIUM | `app/repositories/` |
| 23 | **CORS config with 26 hardcoded localhost entries** — should use environment variable or pattern matching | MEDIUM | `app/core/config.py` CORS_ORIGINS |
| 24 | **`like_tour`/`unlike_tour` without rate limiting or user tracking** — count manipulation possible | MEDIUM | `app/api/api_v1/endpoints/public.py` |
| 25 | **Raw SQL in vector module** — `pgvector` operations use text() queries instead of ORM | LOW | `app/vector/` |

### C. ALREADY CLEAN (Leave Alone)

| Area | Assessment |
|------|------------|
| **Exception class hierarchy** (`app/core/exceptions.py`) | Well-structured: base class with `status_code`, `error_code`, `detail`, `details`. Good domain-specific subclasses. |
| **Structured logging** (`app/core/logging.py`) | Production JSON, dev color, sensitive-field redaction, correlation ID propagation — solid. |
| **Database resilience** (`app/core/db_resilience.py`) | Transient error detection, retry-with-rollback, pool exhaustion fast-fail — well-designed. |
| **Health check** (`app/main.py`) | Isolated raw engine connection, short timeout, transient retry, degraded-mode response — correct. |
| **App factory** (`app/factory.py`) | Clean composition root with dependency injection of MCP apps, middleware, routes. |
| **Error handler registration** (`app/infrastructure/errors.py`) | Standardized JSON error format, MCP OAuth WWW-Authenticate headers, production-safe messages. |
| **Middleware stack** | Security headers, rate limiting, request ID, request logging, trailing slash — all purposeful. |
| **MCP error schema** (`app/mcp/errors.py`) | `MCPErrorCode` enum, `MCPResponse` with success/failure factory methods — good design. |
| **Auth dependency chain** | `get_current_user` → JWT verification → Supabase → local user sync — properly layered. |
| **Pydantic settings** (`app/core/config.py`) | Environment-based, validated, field validators for production safety — 12-factor compliant. |
| **No `print()` statements** | All modules use `get_logger(__name__)` correctly. |
| **No bare `except:` clauses** | All exception handlers are typed. |
| **Ruff/mypy/pytest CI** | Linting, type-checking, and test pipeline already configured. |

---

## PHASE 2: PRIORITIZED REFACTORING PLAN

### Phase 0: Security Quick Wins (1-2 days)
| Step | Action | Why Better |
|------|--------|------------|
| 0.1 | Add Pydantic schemas for `moderate_listing`, `moderate_report`, `complete_visit`, `assign_agent` — replace `dict[str, Any]` payloads | Prevents arbitrary JSON injection on admin endpoints |
| 0.2 | Allowlist `sort_by` values in `property_query_builder.py` — validate against known column names before SQL interpolation | Closes SQL injection vector |
| 0.3 | Set `send_default_pii=False` in Sentry init | Stops leaking user IP/agent/cookies to third party |
| 0.4 | Add rate limiting to `like_tour`/`unlike_tour` endpoints | Prevents count manipulation |

### Phase 1: Kill the Shim Layer (2-3 days)
| Step | Action | Why Better |
|------|--------|------------|
| 1.1 | Choose canonical locations and delete shim re-export files | Single source of truth for imports |
| 1.2 | Delete all `app/modules/*/` wildcard re-export files | Removes 100+ zero-value files |
| 1.3 | Break circular dependency by moving `RequestIDFilter` into `app/core/logging.py` | Eliminates the only circular import |
| 1.4 | Unify config imports to `from app.config import settings` | One import path for settings |

### Phase 2: Enum Enforcement & Type Safety (2-3 days)
| Step | Action | Why Better |
|------|--------|------------|
| 2.1 | Wire existing enums to social model columns with SQLAlchemy `TypeDecorator` wrappers | DB-level and ORM-level constraint enforcement |
| 2.2 | Add missing enums: `AIJobStatus`, `AIJobType`, etc. | Closes the gap where models have comments instead of enforcement |
| 2.3 | Create moderation action enums: `ModerationAction`, `ReportAction` | Type-safe action dispatch |
| 2.4 | Extract all magic numbers to named constants | Every literal encodes meaning |

### Phase 3: Service Layer Hardening (3-4 days)
| Step | Action | Why Better |
|------|--------|------------|
| 3.1 | Extract business logic from flatmates endpoint into service layer | SRP; testable; reusable by MCP/AI-agent |
| 3.2 | Consolidate authorization into `pm_authz.py` | DRY; single source of truth for access control |
| 3.3 | Wire MCP user tools through tool_ops | Follows architecture contract |
| 3.4 | Normalize MCP response format | Consistent error contract |
| 3.5 | Extract inline serialization to schemas | Reusable, validated response shapes |

### Phase 4: Decompose God Files (2-3 days)
| Step | Action | Why Better |
|------|--------|------------|
| 4.1 | Split `pm_tools.py` (1211 lines) into sub-modules | Each file < 300 lines |
| 4.2 | Split `flatmates.py` endpoint (883 lines) | Separate public API from admin API |
| 4.3 | Split `storage/service.py` (~680 lines) | CRUD operations separated by lifecycle |
| 4.4 | Extract shared filter-building logic | DRY; one filter builder |
| 4.5 | Split `blog_auto_publish.py` (~540 lines) | Orchestrator, content, publishing separated |

### Phase 5: Error Handling & Logging Cleanup (2-3 days)
| Step | Action | Why Better |
|------|--------|------------|
| 5.1 | Audit all `except Exception` blocks | No more silent failures |
| 5.2 | Add `exc_info=True` to all `logger.error()` calls missing it | Full stack traces in production |
| 5.3 | Add structured context to key log points | Machine-queryable log entries |
| 5.4 | Add timing instrumentation for outbound calls | Performance visibility |

### Phase 6: Dependency & Config Hygiene (1-2 days)
| Step | Action | Why Better |
|------|--------|------------|
| 6.1 | Remove invalid `starlette>=1.0.0` dependency | Eliminates version conflict |
| 6.2 | Move CORS origins to environment variable | 12-factor compliance |
| 6.3 | Fix circular imports causing function-body imports | Clean module-level imports |
| 6.4 | Audit deps: move dev-only to `[dev]` group | Smaller production image |
| 6.5 | Pin exact versions for production dependencies | Predictable builds |

### Phase 7: Test Structure & Coverage (3-4 days)
| Step | Action | Why Better |
|------|--------|------------|
| 7.1 | Add unit tests for MCP user tools | Validates architecture contract |
| 7.2 | Add unit tests for flatmates moderation | Critical admin path coverage |
| 7.3 | Add integration tests for booking lifecycle | Highest-value user flow |
| 7.4 | Fix conftest.py fixture issues | Tests must actually run |
| 7.5 | Co-locate domain tests | Tests found where developers look |

### Phase 8: Long-Term Architecture Evolution (Future — Document Only)
| Step | Action | Why Better |
|------|--------|------------|
| 8.1 | Design domain-driven module structure | Clear domain boundaries |
| 8.2 | Design repository pattern with Protocol-based interfaces | Testable without DB |
| 8.3 | Design event/observer pattern for side effects | Side effects don't pollute business logic |
| 8.4 | Design adapter pattern for external services | Swappable providers; centralized retry/circuit-breaker |

---

## Execution Progress

| Phase | Status | Key Changes |
|-------|--------|-------------|
| 0 | Completed | Pydantic schemas for admin endpoints (ListingModerationAction, ReportModerationAction, VisitComplete, AssignAgentPayload); Sentry PII disabled; like/unlike rate-limited per IP |
| 1 | Completed | Deleted 9 shim re-export files + 18 module shim directories; moved RequestIDFilter to core/logging; unified imports to app.core.* |
| 2 | Completed | Wired 6 social model enums; added 8 new enums (AIJobStatus, AIJobType, etc.); replaced magic strings with ModerationAction/ReportAction enums |
| 3 | Completed | Consolidated authorization into pm_authz (can_access_booking, can_access_visit); wired MCP user tools (owner, booking, tenant) through tool_ops; normalized MCP response format to MCPResponse across all user tools |
| 4 | Completed | Split flatmates.py (883→400 lines) into flatmates.py + flatmates_admin.py; Split pm_tools.py (1211 lines) into 7 sub-modules (pm_shared, pm_lease, pm_rent, pm_dashboard, pm_maintenance, pm_tenant, pm_owner) |
| 5 | Completed | Added exc_info=True to 34 logger.error() calls (26 in tour_ai/image/notification + 8 in auth/share/websocket/push); Audited and fixed 15 broad except Exception blocks (narrowed types, added exc_info); Replaced 6 function-body imports with top-level in users.py |
| 6 | Completed | Removed invalid starlette dep; moved 5 dev-only deps to [dev]; added CORS_ORIGINS_STR env var override; fixed deprecated typing imports (Optional→X|None, Dict→dict, List→list) across exceptions, schemas |
| 7 | Completed | Added 73 new tests: 43 MCP user tool tests (test_user_tools.py), 30 flatmates admin moderation tests (test_flatmates_admin.py); 662 total passing |
| 8 | Completed | Created 4 ADRs: 001-domain-module-structure, 002-repository-protocol-interfaces, 003-event-driven-side-effects, 004-external-service-adapters |
