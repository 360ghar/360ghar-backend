# Contribution Contract

These rules apply to human contributors and code agents.

## Placement Rules
- Put domain code in the current concrete homes (`app/api`, `app/services`, `app/models`, `app/schemas`, `app/repositories`, `app/mcp`) unless the domain is being physically migrated into `app/modules/<domain>/`.
- Put request handlers in `app/api/api_v1/endpoints/`.
- Put shared business logic in `app/services/`.
- Put persistence structures in `app/models/` and transport/data validation shapes in `app/schemas/`.
- Put MCP server logic and Apps SDK formatting in `app/mcp/`.
- Put AI-agent orchestration in `app/services/ai_agent/`.
- Put cross-cutting infrastructure in `app/infrastructure/`, `app/core/`, `app/middleware/`, `app/repositories/`, or `app/vector/` as appropriate.
- Put cross-domain contracts and helpers in their current canonical homes (`app/core`, `app/schemas`, `app/utils`, or endpoint dependencies). `app/shared/` is reserved for future physical shared packages, not re-export shims.

## Change Requirements
- Endpoint change: update the endpoint module, router registration, tests, and any affected docs.
- Service change: keep async DB access patterns, preserve structured exceptions, and update docs if the service adds a new domain or public behavior.
- MCP or widget change: update tool registration, any widget mapping, tests, and the terminology or architecture docs if the behavior introduces a new surface.
- AI-agent change: update tool bridge or agent service tests and document any new tool path, streaming event, or persistence pattern.
- Scheduler or background change: update `app/infrastructure/lifespan.py` and document the operational behavior in the architecture contract.

## Documentation Rules
- `AGENTS.md` is the entrypoint and contributor contract.
- `docs/repo-contract.json` is the machine-readable inventory used by CI to detect drift.
- Every new endpoint module, service module, and MCP module must be represented in `docs/repo-contract.json` in the same change.
- Use short contract-style updates. Prefer rules, paths, and acceptance checks over long narrative explanations.

## Public Surface Documentation
- Changes that add or reshape public API behavior must update the relevant doc and mention the owning path.
- The current public AI and MCP surfaces that must remain documented include:
  - [`app/api/api_v1/api.py`](../app/api/api_v1/api.py)
  - [`app/mcp/chatgpt/visit_tools.py`](../app/mcp/chatgpt/visit_tools.py)
  - [`app/services/ai_agent/tool_bridge.py`](../app/services/ai_agent/tool_bridge.py)
