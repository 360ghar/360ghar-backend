# MCP servers

Active contributors: Saksham, Ravi

360 Ghar exposes two Model Context Protocol servers from a single FastAPI backend: a user-facing server at `/mcp` and an admin server at `/mcp-admin`. Together they register 40+ tools and 11 React widget resources, all served with OAuth 2.1 + PKCE auth, dual metadata (standard MCP `ui.*` plus OpenAI `openai/*` aliases) so the same server works on ChatGPT Apps, Claude Desktop, Cursor, VS Code Copilot, Gemini, MCPJam, and any MCP-compliant host. This is the largest feature surface in the codebase.

## Directory layout

```
app/mcp/
├── apps_sdk.py            # AppsSDKFastMCP, AppsSDKToolResult, AuthRequiredError, dual metadata
├── auth_provider.py       # SupabaseTokenVerifier + RemoteAuthProvider, OAuth metadata
├── utils.py               # get_db, get_user_from_mcp_context, serializers, role helpers
├── errors.py              # MCPResponse, MCPError, MCPErrorCode
├── user/                  # User MCP server (ghar360-user) at /mcp
│   ├── server.py          # creates user_mcp instance, imports submodules to register tools
│   ├── discovery.py       # discovery_* tools (search, get, feed, swipe, shortlist, recs)
│   ├── owner.py           # owner_* tools (properties, leases, rent, maintenance, dashboard)
│   ├── tenant.py          # tenant_* tools (lease, rent, maintenance)
│   ├── booking.py         # bookings_* tools (create, list, get, cancel, availability, pricing)
│   ├── visits.py          # visits_* tools (schedule, list, get, cancel)
│   └── system.py          # user_system_status
├── admin/                 # Admin MCP server (ghar360-admin) at /mcp-admin
│   ├── server.py          # creates admin_mcp instance, imports submodules
│   ├── admin.py           # admin_system_status
│   ├── agent.py           # imports agent_tools package
│   └── agent_tools/       # agent_* tools (properties, leases, rent, maintenance, bookings, dashboard)
├── chatgpt/               # ChatGPT-specific tool wrappers + widgets + formatters
│   ├── __init__.py        # WIDGETS dict, get_widget_for_tool, widget resource registration
│   ├── discovery_tools.py # discovery + guest tools with widget metadata
│   ├── visit_tools.py     # visit tools with widget metadata
│   ├── pm_dashboard_tools.py
│   ├── pm_lease_tools.py
│   ├── pm_maintenance_tools.py
│   ├── pm_owner_tools.py
│   ├── pm_rent_tools.py
│   ├── pm_tenant_tools.py
│   ├── pm_shared.py       # shared PM serialization helpers
│   └── response_formatter.py # format_chatgpt_response, format_auth_required_response
└── tool_ops/              # shared business logic called by MCP servers + AI agent
    ├── __init__.py
    ├── properties.py
    ├── leases.py
    ├── rent.py
    ├── maintenance.py
    ├── bookings.py
    └── dashboard.py
chatgpt-widgets/
├── src/
│   ├── widgets/           # 11 React widget components (.tsx)
│   ├── utils/
│   │   ├── bridge.ts      # multi-host runtime detection + hooks (openai / mcp-apps / standalone)
│   │   └── theme.ts       # light/dark propagation
│   └── types/
└── dist/                  # 11 built standalone HTML bundles (text/html;profile=mcp-app)
```

## Key abstractions

| Abstraction | File | Role |
|---|---|---|
| `AppsSDKFastMCP` | `app/mcp/apps_sdk.py` | FastMCP 3.2.4 subclass advertising `io.modelcontextprotocol/ui` capability and mapping `AuthRequiredError` to OAuth challenge |
| `AppsSDKToolResult` | `app/mcp/apps_sdk.py` | ToolResult subclass propagating `isError` and `_meta` to wire format |
| `build_widget_tool_meta` | `app/mcp/apps_sdk.py` | Emits both `ui.*` (standard) and `openai/*` (alias) keys per tool |
| `raise_auth_required` | `app/mcp/apps_sdk.py` | Raises `AuthRequiredError` with `WWW-Authenticate` challenge including `resource_metadata` URL |
| `MCP_SECURITY_SCHEMES_MIXED` | `app/mcp/apps_sdk.py` | `[noauth, oauth2]` for guest-accessible tools |
| `MCP_SECURITY_SCHEMES_OAUTH2_ONLY` | `app/mcp/apps_sdk.py` | `[oauth2]` for auth-required tools |
| `RESOURCE_MIME_TYPE` | `app/mcp/apps_sdk.py` | `text/html;profile=mcp-app` — required for widget resources |
| `SupabaseTokenVerifier` | `app/mcp/auth_provider.py` | Validates first-party OAuth access tokens from `oauth_token_store` |
| `get_user_from_mcp_context` | `app/mcp/utils.py` | Resolves current user from MCP access token using background pool |
| `get_db` | `app/mcp/utils.py` | Background-pool session generator for long-lived tool calls |
| `MCPResponse` / `MCPError` | `app/mcp/errors.py` | Standardised `{ok, data, error}` envelope for non-ChatGPT callers |
| `WIDGETS` | `app/mcp/chatgpt/__init__.py` | Maps widget name → tool list, title, description; used for resource registration |
| `get_widget_for_tool` | `app/mcp/chatgpt/__init__.py` | Reverse lookup: tool name → cache-busted widget URI |
| `format_chatgpt_response` | `app/mcp/chatgpt/response_formatter.py` | Wraps data + summary + meta into `AppsSDKToolResult` |
| `tool_ops/*` | `app/mcp/tool_ops/` | Shared business logic called by MCP servers and [AI agent](ai-agent.md) |

## How it works

Two `AppsSDKFastMCP` instances are created in `app/mcp/user/server.py` (`user_mcp = AppsSDKFastMCP("ghar360-user")`) and `app/mcp/admin/server.py` (`admin_mcp = AppsSDKFastMCP("ghar360-admin")`). Importing the submodules triggers `@user_mcp.tool()` / `@admin_mcp.tool()` decorators that register each tool. Both servers are mounted by `app/infrastructure/mcp.py` at `/mcp` and `/mcp-admin` and share OAuth endpoints at `/mcp/oauth/*`.

Each tool registration carries an `annotations` dict with `readOnlyHint`, `openWorldHint`, `destructiveHint`, and `securitySchemes`. Guest-accessible tools (discovery, public property details) use `MCP_SECURITY_SCHEMES_MIXED = [noauth, oauth2]`; auth-required tools use `MCP_SECURITY_SCHEMES_OAUTH2_ONLY`. Widget-linked tools additionally pass `build_widget_tool_meta(widget_uri=..., invoking=..., invoked=...)` which emits both standard MCP keys (`ui.resourceUri`, `ui/visibility`) and OpenAI aliases (`openai/outputTemplate`, `openai/widgetAccessible`, `openai/toolInvocation/*`).

```mermaid
graph TD
    Host[MCP Host: ChatGPT / Claude / Cursor / VS Code] -->|Streamable HTTP| Mount[/mcp or /mcp-admin]
    Mount --> SDK[AppsSDKFastMCP]
    SDK -->|init| CAP[io.modelcontextprotocol/ui capability]
    SDK -->|tool call| _call_tool_mcp
    _call_tool_mcp -->|AuthRequiredError| Chall[CallToolResult isError + mcp/www_authenticate]
    _call_tool_mcp -->|ok| Tool[user/admin tool function]
    Tool --> DB[get_db background pool]
    Tool --> OPS[app/mcp/tool_ops shared logic]
    OPS --> SVC[app/services/* business layer]
    Tool --> FMT[format_chatgpt_response]
    FMT --> Result[AppsSDKToolResult content + structuredContent + _meta]
    Result -->|ui.resourceUri| WidgetResource[widget HTML resource]
    WidgetResource --> Host2[Host renders iframe]
    Host2 --> Bridge[chatgpt-widgets/src/utils/bridge.ts]
    Bridge -->|window.openai?| OpenAI[OpenAI host path]
    Bridge -->|iframe parent?| MCPApps[MCP Apps JSON-RPC postMessage]
    Bridge -->|else| Standalone[standalone dev mode]
    OAuth[OAuth 2.1 + PKCE] -->|/mcp/oauth/*| Host
    OAuth --> TS[oauth_token_store]
    TS --> Verifier[SupabaseTokenVerifier]
    Verifier --> SDK
```

Auth uses OAuth 2.1 with PKCE. `SupabaseTokenVerifier` in `auth_provider.py` accepts only first-party OAuth access tokens issued by `app/services/oauth_token_store.py` (long random strings without dots, validated against the cache-backed store). Supabase JWTs are no longer accepted on MCP endpoints. When a tool requires auth and the caller is unauthenticated, it calls `raise_auth_required()` which raises `AuthRequiredError` with a `WWW-Authenticate: Bearer resource_metadata="...", error="insufficient_scope", ...` challenge. `AppsSDKFastMCP._call_tool_mcp` catches this and returns a `CallToolResult` with `isError=true` and `_meta["mcp/www_authenticate"]`, triggering the host's OAuth UI. RFC 9728 / RFC 8414 well-known metadata at `/.well-known/oauth-protected-resource/{mcp,mcp-admin}` and `/.well-known/oauth-authorization-server` enables any OAuth 2.1 client to discover endpoints and register dynamically via `/mcp/oauth/register`.

The widget system is the other large piece. Eleven React widgets are built as standalone HTML bundles in `chatgpt-widgets/dist/` and registered as MCP resources with `RESOURCE_MIME_TYPE = "text/html;profile=mcp-app"`. The `WIDGETS` dict in `app/mcp/chatgpt/__init__.py` maps each widget name to its linked tool list, title, and description; `get_widget_for_tool()` does the reverse lookup. Each widget is readable at its stable URI (`ui://widget/<name>.html`) because tool metadata advertises those URIs, and at a content-hashed alias (`?v=<hash>`) for cache-busted result-level hints. The bridge in `chatgpt-widgets/src/utils/bridge.ts` detects the host at module load — `window.openai` present means OpenAI host, `window.parent !== window` means MCP Apps host (JSON-RPC 2.0 over postMessage, MCP Apps protocol `2026-01-26`), else standalone. The exported hooks (`useToolOutput`, `useCallTool`, `useSendMessage`, `useTheme`, `useWidgetState`) have identical signatures across all three runtimes, so widgets work without per-widget changes. Light/dark theme propagates from the host on all runtimes.

`useToolOutput()` normalises the payload shape before handing it to a widget. The `app/mcp/user/*` tools return an `MCPResponse` envelope (`{ok: true, data: {...}}`) while the `app/mcp/chatgpt/*` tools return the payload flat, and widgets read their fields off the top level. `unwrapToolOutput()` in `bridge.ts` unwraps a successful envelope so every widget accepts either shape on every host — without it, a widget fed the envelope renders as permanently empty. Error envelopes (`ok: false`) pass through untouched because widgets read their `error`/`message` keys. When adding a tool, prefer flat `structuredContent`; the unwrap is a safety net, not a licence to nest.

The shared logic layer in `app/mcp/tool_ops/` is critical. Six modules (properties, leases, rent, maintenance, bookings, dashboard) contain the service calls, DB queries, authorisation, and serialization used by both MCP servers and the [AI agent](ai-agent.md) tool bridge. Per the layering rules in [AGENTS.md](../../AGENTS.md), new MCP tools must implement logic in `tool_ops/` first, then wire it through both `user/server.py`/`admin/` and `services/ai_agent/tools/` — no duplication.

## Integration points

- **Service layer**: all tool logic ultimately calls `app/services/*` functions. The [property management](property-management.md), [Ghar Core](ghar-core.md), [360 Stays](stays.md), and [AI agent](ai-agent.md) features are all reachable from MCP tools.
- **OAuth token store**: `app/services/oauth_token_store.py` (backed by `CacheManager`) persists first-party OAuth access tokens and authorization codes.
- **Infrastructure**: server mounting, OAuth endpoint wiring, and lifespan shutdown live in `app/infrastructure/mcp.py` (see [infrastructure](../systems/infrastructure.md)).
- **AI agent**: the [AI agent](ai-agent.md) reuses the same tool implementations via `app/services/ai_agent/tools/` rather than going through the MCP wire protocol.
- **Storage**: widget HTML bundles are served as MCP resources; the built artifacts live in `chatgpt-widgets/dist/`.

## Entry points for modification

Add a new user tool by writing the business logic in `app/mcp/tool_ops/`, registering it in `app/mcp/user/` with `@user_mcp.tool()` annotations (include `readOnlyHint`, `openWorldHint`, `destructiveHint`, `securitySchemes`), and — if it should render a widget — adding an entry to `WIDGETS` in `app/mcp/chatgpt/__init__.py` and a widget component in `chatgpt-widgets/src/widgets/`. New admin tools go in `app/mcp/admin/agent_tools/` and require `_require_agent_or_admin`. Every auth-required tool must use `raise_auth_required()` (not raw `AuthRequiredError`) so the challenge includes `resource_metadata`. Update CLAUDE.md and AGENTS.md when adding tools, widgets, or new MCP protocol capabilities.

## Key source files

| File | Purpose |
|---|---|
| `app/mcp/apps_sdk.py` | AppsSDKFastMCP + dual metadata + auth challenge (11.2 KB) |
| `app/mcp/auth_provider.py` | SupabaseTokenVerifier + OAuth metadata (8.5 KB) |
| `app/mcp/utils.py` | DB session, user resolution, serializers (15.6 KB) |
| `app/mcp/errors.py` | MCPResponse / MCPError envelope |
| `app/mcp/user/server.py` | User MCP instance + tool registration |
| `app/mcp/user/owner.py` | Owner tool implementations (13.7 KB) |
| `app/mcp/user/tenant.py` | Tenant tool implementations |
| `app/mcp/user/booking.py` | Booking tool implementations (11 KB) |
| `app/mcp/admin/server.py` | Admin MCP instance |
| `app/mcp/admin/admin.py` | admin_system_status |
| `app/mcp/admin/agent_tools/` | Agent-scoped tool modules (7 files) |
| `app/mcp/chatgpt/__init__.py` | WIDGETS dict + widget resource registration (270 lines) |
| `app/mcp/chatgpt/discovery_tools.py` | Discovery + guest tools with widget meta (669 lines) |
| `app/mcp/chatgpt/visit_tools.py` | Visit tools with widget meta (15.1 KB) |
| `app/mcp/chatgpt/pm_*.py` | 7 PM tool modules (split from former pm_tools.py) |
| `app/mcp/chatgpt/response_formatter.py` | format_chatgpt_response + helpers (363 lines) |
| `app/mcp/tool_ops/` | Shared tool business logic (6 modules) |
| `chatgpt-widgets/src/utils/bridge.ts` | Multi-host runtime bridge (439 lines) |
| `chatgpt-widgets/src/utils/theme.ts` | Light/dark theme propagation |
| `chatgpt-widgets/src/widgets/` | 11 React widget components |
| `chatgpt-widgets/dist/` | 11 built HTML bundles |
| `app/services/oauth_token_store.py` | OAuth token + code persistence |
| `app/api/api_v1/endpoints/oauth/` | OAuth 2.1 + PKCE endpoints |
