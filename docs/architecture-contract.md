# Architecture Contract

This document defines the current backend shape. It is normative: new code should fit these boundaries unless the contract is updated in the same change.

## Runtime Surfaces
- REST API: [`app/api/api_v1/api.py`](../app/api/api_v1/api.py) wires all versioned routers; [`app/factory.py`](../app/factory.py) is the composition root; `app/infrastructure/` owns middleware, exception handlers, lifespan, route mounting, and MCP HTTP app construction.
- `app/modules/` is reserved for future physical domain entrypoints. The previous wildcard re-export wrappers have been removed; do not recreate shim-only domain packages.
- Core marketplace and booking flows currently live in the REST endpoint modules under `app/api/api_v1/endpoints/` and shared business logic under `app/services/`.
- Property Management flows are exposed through the `app/api/api_v1/endpoints/pm_*.py` endpoints and the matching `app/services/pm_*.py` modules.
- Tours and media flows are exposed through the tour/storage endpoint and service modules.
- MCP surfaces live in `app/mcp/user/`, `app/mcp/admin/`, and multi-client tool modules such as [`app/mcp/chatgpt/visit_tools.py`](../app/mcp/chatgpt/visit_tools.py). The MCP servers use `AppsSDKFastMCP` with Streamable HTTP transport and support MCP-compatible clients.
- AI-agent orchestration lives in `app/services/ai_agent/`, especially [`app/services/ai_agent/tool_bridge.py`](../app/services/ai_agent/tool_bridge.py) and `agent_service.py`.
- Vector search and sync live in `app/vector/` and the vector sync scheduler.
- Data Hub aggregation flows live in `app/services/data_hub/`, exposed via `app/api/api_v1/endpoints/data_hub/` and scheduled via `app/services/data_hub_scheduler.py`.
- Startup jobs and schedulers are registered from `app/infrastructure/lifespan.py` and currently include blog auto publish, notifications, vector sync, and data hub scraping.

## Layer Contracts
- `app/modules` is a reserved namespace for future domain packages. New code should use the existing concrete homes (`app/api`, `app/services`, `app/models`, `app/schemas`, `app/repositories`, `app/mcp`) until a domain is physically migrated.
- `app/api` remains the REST transport layer and should delegate to module or service entrypoints. It should not own business rules that are needed elsewhere.
- `app/services` remains the legacy business-logic implementation layer during migration and depends on `app.models`, `app.schemas`, `app.repositories`, `app.core`, and narrowly-scoped external clients.
- `app/infrastructure` owns composition and adapters: app factory helpers, database/session lifecycle re-exports, cache, logging context, middleware registration, routes, and lifespan jobs.
- `app/shared` is a reserved namespace for future cross-domain contracts. Current canonical homes remain `app.core.exceptions`, `app.api.api_v1.dependencies.auth`, `app.schemas.common`, `app.core.utils`, and `app.utils`.
- `app/mcp` may depend on module/service entrypoints, schemas, shared errors, and serializer/formatter helpers. MCP tools should not create alternate business-rule paths when a service already exists.
- `app/services/ai_agent` may orchestrate models, tool registration, and streaming, but tool execution should prefer shared service-layer behavior over agent-only mutations.
- `app/models` and `app/schemas` are leaf data layers. They should not import endpoint or transport code.

## Approved Extension Points
- Add new REST functionality by wiring the REST transport in `app/api/api_v1/endpoints/`, service logic in `app/services/`, and matching schemas in `app/schemas/`. Only add `app/modules/<domain>/` code when the domain implementation is physically migrated there, not as a re-export shim.
- Add new MCP capabilities by extending `app/mcp/user/server.py`, `app/mcp/admin/`, or the multi-client tool modules in `app/mcp/chatgpt/`, while reusing existing services for authz and persistence. Tools must use `AppsSDKToolResult` and include standard annotations (`readOnlyHint`, `openWorldHint`, `destructiveHint`, `securitySchemes`).
- Add new AI-agent capabilities by extending `app/services/ai_agent/tool_bridge.py` or related agent orchestration files, while keeping transport-specific logic out of shared services.
- Add new background automation via dedicated scheduler modules in `app/services/` and explicit startup wiring in `app/infrastructure/lifespan.py`.

## Known Anti-Patterns To Avoid
- Repeating auth, DB session bootstrapping, or validation logic separately in REST, MCP, and AI-agent flows when the same business action already exists in a shared service.
- Mutating ORM state directly inside endpoint or tool wrappers when an equivalent service abstraction exists or should be added.
- Introducing new public runtime surfaces without updating `AGENTS.md`, this contract, and `docs/repo-contract.json`.
