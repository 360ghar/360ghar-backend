# Terminology And Ownership

## Core Terms
- Marketplace property: a property exposed through the core discovery and booking surfaces.
- PM managed property: a property operated through the `pm_*` endpoints and services for owners, managers, and tenants.
- MCP tool: a FastMCP-exposed action in `app/mcp/` that serves ChatGPT or other MCP clients.
- AI-agent tool bridge: the adapter layer in `app/services/ai_agent/tool_bridge.py` that exposes shared backend actions to the in-app agent.
- Widget-backed tool response: a tool result that carries structured content plus widget metadata for ChatGPT Apps surfaces.
- Plain API response: a standard FastAPI JSON or streaming HTTP response without Apps SDK widget metadata.

## Ownership Boundaries
- REST endpoint ownership starts in `app/api/api_v1/endpoints/` and is composed in `app/api/api_v1/api.py`.
- Shared business ownership sits in `app/services/`.
- MCP ownership sits in `app/mcp/`, but the underlying business behavior should still belong to shared services.
- AI-agent ownership sits in `app/services/ai_agent/`, with model orchestration and tool registration there and business rules delegated down.
- Scheduler ownership sits in dedicated service modules and is activated from `app/infrastructure/lifespan.py`.

## Ambiguity Resolution
- If a feature must work from REST, MCP, and the AI agent, the source of truth belongs in `app/services/`.
- If the change only affects formatting for ChatGPT widgets, keep it in `app/mcp/chatgpt/`.
- If the change only affects agent streaming, event persistence, or model/tool orchestration, keep it in `app/services/ai_agent/`.
