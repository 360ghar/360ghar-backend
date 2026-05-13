# 360Ghar Backend Operating Contract

This repository uses repo-local docs as the source of truth for contributors and agents. The goal is to keep architecture, contribution rules, and test expectations explicit and lightly enforced.

## Operating Docs
- [Architecture Contract](docs/architecture-contract.md)
- [Contribution Contract](docs/contribution-contract.md)
- [Testing Contract](docs/testing-contract.md)
- [Terminology And Ownership](docs/terminology-and-ownership.md)
- [Machine Contract Inventory](docs/repo-contract.json)

## Build And Validation
```bash
docker-compose up -d db redis
uv run python run.py
uv run pytest tests/ -v
uv run python scripts/validate_docs_contracts.py
```

> **Note:** Dev dependencies (pytest, ruff, mypy) are in the `dev` optional group. Install with `uv sync --extra dev`.

## Layering Rules
- HTTP endpoints in `app/api/api_v1/endpoints/` validate input, enforce auth through dependencies, and delegate business logic to `app/services/`.
- REST route composition lives in `app/api/api_v1/api.py`; `app/factory.py` is the composition root, while app wiring, middleware, lifespan, and MCP mounts live in `app/infrastructure/`.
- Business rules belong in `app/services/`. Reuse service functions from REST, MCP, and AI-agent surfaces instead of re-implementing them.
- Persistence models live in `app/models/`; request and response shapes live in `app/schemas/`.
- Social and flatmates models (matches, conversations, blocks, reports) live in `app/models/social.py`; flatmates service logic lives in `app/services/flatmates/` package (conversations, helpers, interactions, matching, moderation, profiles, visits) with REST endpoints in `app/api/api_v1/endpoints/flatmates.py` and admin moderation endpoints in `app/api/api_v1/endpoints/flatmates_admin.py`.
- MCP servers and ChatGPT-specific tool wrappers live in `app/mcp/`. They may format tool responses, but authorization and state changes should still flow through shared services where possible.
- Shared MCP tool business logic lives in `app/mcp/tool_ops/`. These functions are called by both MCP servers (`user_server.py`, `app/mcp/admin/`) and the AI agent tool bridge (`tool_bridge.py`) — do not duplicate this logic.
- AI-agent orchestration lives in `app/services/ai_agent/`. Tool registration and model streaming belong there, but tool behavior should still call shared service-layer code.
- Notification dispatch flows through `app/services/notification_config.py` (type registry with channel, priority, frequency caps) → `app/services/notification_dispatcher.py` (multi-channel send) → `app/services/notifications/` (CRUD + Supabase push, sub-modules: crud, fcm, helpers, push) → `app/services/push_notification.py` (FCM). New notification types must be registered in the `NOTIFICATION_TYPES` dict.
- SSE real-time events flow through `SSEEventBus` in `app/core/sse.py`. Service methods call `await sse_bus.emit(user_id, event_dict)` after DB commit. The SSE endpoint is `GET /api/v1/flatmates/sse`. Event types: `new_match`, `new_message`, `conversation_updated`, `visit_updated`, `listing_status_changed`, `new_notification`. New SSE event types or subscriptions must update CLAUDE.md and AGENTS.md.
- OAuth token/code persistence uses `app/services/oauth_token_store.py` backed by CacheManager. Token stores require a real (non-null) cache backend in production.
- `app/modules/` is reserved for future physical domain entrypoints. Do not recreate shim-only re-export packages; use the current concrete homes (`app/api`, `app/services`, `app/models`, `app/schemas`, `app/repositories`, `app/mcp`) until a domain is migrated.
- Cross-cutting infrastructure belongs in `app/infrastructure/`, `app/core/`, `app/middleware/`, and `app/vector/`.
- `app/infrastructure/` owns lifespan wiring (startup/shutdown orchestration), middleware registration, exception handlers, MCP HTTP app construction, and route mounting. `app/factory.py` is a thin composition root that delegates to `app/infrastructure/`.
- `app/shared/` is reserved for future physical shared packages. Current shared contracts and helpers remain in `app/core`, `app/schemas`, `app/utils`, and endpoint dependencies.
- `app/config/` is a re-export package; `from app.config import settings` is the canonical import location (delegates to `app/core/config.py`).
- AI provider abstraction lives in `app/services/ai/` with a factory (`get_ai_provider`) supporting Gemini and GLM providers. All AI features (vastu, tour AI, blog generation) go through this layer with automatic retries and fallback.
- Blog SEO fields (meta_title, meta_description, focus_keyword, canonical_url, og_image_url, reading_time_minutes, word_count) are auto-computed from the post title/body when not explicitly provided, via helpers in `app/services/blog.py`.

## Contributor Requirements
- New REST endpoint modules must be routed through `app/api/api_v1/api.py`, covered by tests, and registered in `docs/repo-contract.json`.
- New service modules must follow existing naming conventions, keep I/O async when touching the database, and be registered in `docs/repo-contract.json`.
- New MCP tools, widget bindings, or AI-agent tool bridges must update the architecture and terminology docs when they add a new public surface or execution pattern.
- New background jobs or schedulers must be wired through `app/infrastructure/lifespan.py` startup and documented in the architecture contract.
- Do not add new dependencies without checking current upstream documentation and compatibility with Python 3.10+, FastAPI, SQLAlchemy 2.x, and Pydantic v2.

## Use Latest Versions & References
- **Always use the latest stable versions** of packages, SDKs, AI models, API versions, protocol versions, and any external references. Never rely on cached or training-knowledge version numbers, model names, API signatures, or SDK methods — these change frequently and are often outdated.
- **Research current docs before implementing**: Before using any 3rd party library, API, SDK, AI model, or protocol, look up the latest official documentation. Use web search, Context7 MCP tools, `WebFetch`, or `google_search` to retrieve up-to-date docs, version numbers, API references, and code examples.
- **Verify from official sources**: When referencing package versions, model names, API endpoints or signatures, SDK methods, protocol versions (e.g., MCP protocol version), or any external service, always confirm the latest from official sources (docs sites, GitHub releases, PyPI, npm, official changelogs). Never assume from memory.
- **Check changelogs and migration guides**: When upgrading any dependency or integrating a new service, review the official changelog/migration guide for breaking changes and new features.
- **Stay current with the ecosystem**: Periodically check for newer versions of key dependencies (FastAPI, SQLAlchemy, Pydantic, Supabase, FastMCP, etc.) and update when safe. Prefer latest official docs and examples over outdated tutorials or blog posts.

## Lint & Style Rules (enforced in CI)

All code must pass `uv run ruff check app/` before commit. The CI `lint` job enforces this — any violation fails the build.

**Imports (I001, UP035, F401, E402):**
- `from __future__ import annotations` must be the first import in every `.py` file (after docstrings).
- Use `list`/`dict`/`set`/`tuple`/`type` instead of `typing.List`/`Dict`/`Set`/`Tuple`/`Type`.
- Import `Callable`, `Awaitable`, `AsyncIterator`, `Sequence` from `collections.abc`, not `typing`.
- Remove all unused imports (F401). No "just in case" imports.
- All imports at file top before non-import code (E402). Use `# noqa: E402` only for unavoidable circular imports with an explanatory comment.

**Type annotations (UP045, UP006, UP007, UP037):**
- `X | None` instead of `Optional[X]`; `X | Y` instead of `Union[X, Y]`.
- `list[X]` instead of `List[X]`; `dict[K, V]` instead of `Dict[K, V]`.
- Remove unnecessary quotes in annotations (`"User"` → `User`).
- Forward references in models: add `from __future__ import annotations` + import under `TYPE_CHECKING`.

**Exception handling (B904):**
- `raise NewException(...) from None` when logging the original and raising a user-facing exception.
- `raise NewException(...) from e` when the original exception provides useful context.

**Equality (E712):** No `== True`/`== False`. Use the column directly or bitwise negation.

**Naming (E741):** Never use `l` as a variable name — use `lease`, `line`, `link`, etc.

**Unused variables (F841):** Don't assign to unused variables. Use `_` or `_name` to discard.

**Whitespace (W291, W292, W293):** No trailing whitespace, no whitespace on blank lines, files end with newline.

**Other:** `zip(a, b, strict=True)` (B905); set comprehensions not `set(gen)` (C401); no placeholder-free f-strings (F541); no name redefinitions (F811).

## When To Update Docs
- Any new public endpoint or router family
- Any new service module or new nested service package
- Any new MCP tool, widget bundle, or AI-agent tool bridge
- Any new scheduler, background processing flow, or startup job
- Any new top-level runtime directory under `app/`, `tests/`, or `docs/`
- Any new flatmates or social feature (models, schemas, endpoints, services)
- Any new notification type registered in `NOTIFICATION_TYPES`
- Any new AI provider or vision model constant added to `app/core/constants.py`
- Any new SSE event type or subscription (emit/subscribe change)
- Any new infrastructure module or lifespan change (startup/shutdown wiring)

## Documentation Drift Checklist
- New public endpoint
- New service domain
- New MCP tool or widget
- New background or scheduler flow
- New flatmates or social feature
- New notification type (must be added to `NOTIFICATION_TYPES` in `notification_config.py`)
- New AI provider or vision model
- New SSE event type or subscription
- New infrastructure module or lifespan change
- New MCP tool_ops shared function
- If any item changed, update the relevant doc in `docs/` and `docs/repo-contract.json`
