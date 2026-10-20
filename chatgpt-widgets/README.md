# 360Ghar MCP Widgets

This directory contains the interactive widget system for 360Ghar's MCP servers, enabling rich UI experiences across **all MCP-compatible hosts** - ChatGPT Apps, Claude Desktop, Cursor, VS Code Copilot, Gemini, MCPJam, and any MCP-compliant client.

## Architecture

The widgets are built on the **Model Context Protocol (MCP)** standard and consist of:

1. **MCP Server** (`/mcp`) - Exposes tools that any MCP client can call
2. **Widget UI** (`chatgpt-widgets/`) - React components rendered in host iframes
3. **Unified Bridge** - Runtime-detected API layer that works on all hosts

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   ChatGPT   │  │   Claude    │  │   Cursor    │  │  VS Code    │
│   (OpenAI)  │  │  Desktop    │  │             │  │  Copilot    │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
       └────────────────┴────────────────┴────────────────┘
                                │
                                ▼
                  ┌─────────────────────────┐
                  │    MCP Server (/mcp)     │────▶ 360Ghar API
                  │  (AppsSDKFastMCP)        │◀──── (Backend)
                  └───────────┬─────────────┘
                              │
                              ▼
                  ┌─────────────────────────┐
                  │  Widget iframe (HTML)    │
                  │  Unified Bridge detects  │
                  │  host at runtime         │
                  └─────────────────────────┘
```

## Features

### For Property Seekers (Guest + Authenticated)
- **Property Search** - Search by location, filters, price range
- **Property Details** - View full property information with images
- **Discovery Feed** - Swipe-based property discovery (like/pass)
- **Visit Scheduling** - Schedule property visits (requires auth)
- **Shortlist** - Save and view liked properties (requires auth)

### For Tenants
- **Lease Information** - View current lease details
- **Rent Dues** - View outstanding rent and payment due dates
- **Rent History** - Track rent payments
- **Maintenance Requests** - Submit and track maintenance issues

### For Property Owners
- **Property Dashboard** - Overview of owned properties with analytics
- **Lease Management** - View, manage, and terminate leases
- **Rent Collection** - Track payments, record transactions, view overdue
- **Maintenance Tracking** - View and update maintenance requests
- **Occupancy Stats** - Track occupied vs vacant units

## Directory Structure

```
app/mcp/chatgpt/
├── __init__.py           # Module initialization & widget registration
├── discovery_tools.py    # Property search, details, swipe tools
├── visit_tools.py        # Visit scheduling tools
├── pm_tools.py           # Property management tools (leases, rent, maintenance)
├── response_formatter.py # Response formatting for all MCP hosts
└── validation.py         # Pydantic schemas for tool inputs

chatgpt-widgets/
├── package.json          # npm configuration
├── tsconfig.json         # TypeScript configuration
├── scripts/
│   └── build-widgets.js  # Build script for HTML bundles
├── src/
│   ├── types/
│   │   └── openai.d.ts   # window.openai TypeScript definitions
│   ├── utils/
│   │   ├── bridge.ts     # Unified bridge hooks (works on all MCP hosts)
│   │   └── theme.ts      # Theme colors for dark/light mode
│   ├── components/
│   │   ├── common/       # Reusable components (Button, Card)
│   │   └── property/     # Property-specific components
│   └── widgets/          # Widget entry points (11 total)
│       ├── PropertySearchWidget.tsx
│       ├── PropertyDetailsWidget.tsx
│       ├── PropertySwipeWidget.tsx
│       ├── VisitSchedulerWidget.tsx
│       ├── VisitListWidget.tsx
│       ├── LeaseDetailsWidget.tsx
│       ├── MaintenanceWidget.tsx
│       ├── OwnerDashboardWidget.tsx
│       ├── LeaseManagementWidget.tsx    # Owner lease management
│       ├── RentCollectionWidget.tsx     # Owner rent tracking
│       └── TenantRentWidget.tsx         # Tenant rent dues
└── dist/                 # Built HTML bundles (11 files)
```

## Development

### Prerequisites

- Node.js 18+
- npm or yarn

### Building Widgets

```bash
cd chatgpt-widgets

# Install dependencies
npm install

# Build all widgets
npm run build

# Watch mode for development
npm run build:watch
```

### Testing Locally

1. Start the FastAPI backend:
   ```bash
   fastapi dev app/main.py --host 0.0.0.0 --port 8000
   ```

2. Use ngrok to expose the server:
   ```bash
   ngrok http 8000
   ```

3. Test with MCP Inspector (universal testing tool):
   ```bash
   npx @mcpjam/inspector --url https://your-ngrok-url.ngrok.io/mcp --oauth --verbose
   ```

4. Connect from your preferred client:
   - **ChatGPT**: Settings > Apps & Connectors > Advanced, add URL + `/mcp`
   - **Claude Desktop**: Add to `claude_desktop_config.json` with `type: "streamable-http"`
   - **Cursor**: Add to `.cursor/mcp.json` with `transport: "streamable-http"`
   - **VS Code Copilot**: Add to `.vscode/mcp.json` with `type: "http"`

## OAuth Compatibility

The MCP server supports standards-based OAuth for multi-client compatibility:

- Single user MCP endpoint: `/mcp`
- Admin MCP endpoint: `/mcp-admin`
- Dynamic client registration: `/mcp/oauth/register`
- Authorization code + PKCE: `/mcp/oauth/authorize`, `/mcp/oauth/token`
- Token revocation: `/mcp/oauth/revoke`
- Discovery metadata:
  - `/.well-known/oauth-protected-resource`
  - `/.well-known/oauth-protected-resource/mcp`
  - `/.well-known/oauth-protected-resource/mcp-admin`
  - `/.well-known/oauth-authorization-server/mcp/oauth`

## Tool Reference

### Discovery Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `discovery_search` | Search properties with filters | No |
| `discovery_property_get` | Get full property details | No |
| `discovery_feed` | Get discovery feed for swiping | No |
| `discovery_amenities` | List available amenities | No |
| `discovery_swipe` | Record like/pass on property | Yes |
| `discovery_shortlist` | Get liked properties | Yes |
| `discovery_recommendations` | Get AI recommendations | Yes |

### Visit Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `visits_schedule` | Schedule a property visit | Yes |
| `visits_list` | List user's visits | Yes |
| `visits_get` | Get visit details | Yes |
| `visits_cancel` | Cancel a scheduled visit | Yes |

### Tenant Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `tenant_lease_current` | Get current lease | Yes |
| `tenant_rent_dues` | View outstanding rent | Yes |
| `tenant_rent_history` | Get rent payment history | Yes |
| `tenant_maintenance_create` | Submit maintenance request | Yes |
| `tenant_maintenance_list` | List maintenance requests | Yes |

### Owner Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `owner_properties_list` | List owned properties | Yes |
| `owner_properties_create` | Create new listing | Yes |
| `owner_properties_get` | Get property details | Yes |
| `owner_properties_update` | Update property | Yes |
| `owner_dashboard_overview` | Get portfolio dashboard | Yes |
| `owner_leases_list` | List leases for properties | Yes |
| `owner_leases_get` | Get lease details | Yes |
| `owner_leases_terminate` | Terminate a lease | Yes |
| `owner_rent_status` | View rent collection status | Yes |
| `owner_rent_record_payment` | Record a rent payment | Yes |
| `owner_rent_history` | View payment history | Yes |
| `owner_maintenance_list` | List maintenance requests | Yes |
| `owner_maintenance_update` | Update maintenance status | Yes |

## Widget Development

### Using the Unified Widget Bridge

The bridge (`src/utils/bridge.ts`) provides identical React hooks regardless of the host runtime. It auto-detects the host at module load - no per-widget configuration needed.

```tsx
import { isToolFailure, useToolOutput, useCallTool, useSendMessage } from '../utils/bridge';

function MyWidget() {
  // Get tool output data - works on all MCP hosts
  const data = useToolOutput<MyDataType>();

  // Call other tools - uses window.openai on ChatGPT, JSON-RPC on other hosts
  const callTool = useCallTool();
  const result = await callTool<SearchOutput>('discovery_search', { city: 'Mumbai' });
  if (isToolFailure(result)) return;

  // Send follow-up messages - adapts to host protocol
  const sendMessage = useSendMessage();
  sendMessage('Show me details for property 123');
}
```

**Available hooks** (all work identically across hosts):

| Hook | OpenAI Host | MCP Apps Host |
|------|-------------|---------------|
| `useToolOutput()` | `window.openai.toolOutput` | JSON-RPC `ui/notifications/tool-result` |
| `useToolMeta()` | `window.openai.toolResponseMetadata` | JSON-RPC `_meta` field |
| `useToolInput()` | `window.openai.toolInput` | JSON-RPC `ui/notifications/tool-input` |
| `useWidgetState()` | `window.openai.setWidgetState()` | In memory only (nothing in browser storage) |
| `useTheme()` | `window.openai.theme` | `ui/notifications/host-context-changed` |
| `useCallTool()` | `window.openai.callTool()` | JSON-RPC `tools/call` |
| `useSendMessage()` | `window.openai.sendFollowUpMessage()` | JSON-RPC `ui/message` |
| `useOpenExternal()` | `window.openai.openExternal()` | `window.open()` fallback |

### Contract rules

The widgets follow `contract-audit/contract-changelog.md` (section 10 and the widgets gate in 11.2).

- **Tool names.** `src/generated/tool-names.json` is written by the backend (`uv run python scripts/export_tool_names.py`) from the tools the MCP servers register. `npm run api:types` turns it into `src/generated/tool-names.ts`. `callTool` takes a `ToolName`, so a name the server does not register fails `npm run typecheck`. `tests/contract/test_tool_names.py` in the backend scans the `callTool('literal'` calls too, so keep the first argument of each single call a string literal.
- **Types.** `openapi/openapi.json` is a copy of `docs/openapi.json` (`npm run api:sync`). `npm run api:types` generates `src/api/schema.gen.ts`. `src/api/wire.ts` aliases the generated enums and widget payload models. The rows inside a payload (`items`, `leases`, `charges`) are free-form objects in OpenAPI, so `wire.ts` declares them by hand from the MCP serializers in `app/mcp/utils.py`.
- **Payload keys.** Each widget reads the keys of its payload model: `items` (list tools), `counts` (visits and bookings), `leases` and `stats` (leases), `charges` and `totals` (rent), `stats` (dashboard). `discovery_feed`, `discovery_recommendations` and `discovery_shortlist` send `properties` instead of `items`. Do not read `success`.
- **Paging.** `usePagedRows` keeps the rows. Load More and refresh call the tool with the arguments of the original call (`useToolInput`) and the new cursor, and merge the RETURNED payload. A cursor is bound to the filters of its call.
- **Tool results.** `useCallTool` unwraps `{ok, data}` and never throws. Test the result with `isToolFailure()` and show `toolFailureMessage()`.
- **Two servers.** A widget can come from `/mcp` (owner, tenant, visits) or `/mcp-admin` (agent). Pass `['owner_leases_list', 'agent_leases_list']` to try the next name only when the host reports an unknown tool.
- **Widget access.** On the OpenAI host a widget can call only tools with `_meta["openai/widgetAccessible"] = true`. `visits_cancel` does not have it yet, so Cancel Visit sends the chat message "Cancel visit N". Call a tool from a widget only after you check its meta (`build_widget_tool_meta` sets it). The fake host in `browser.check.mjs` does not enforce the key.
- **Enums.** Labels live in `src/utils/status.ts` as `Record<EnumValue, ...>`. A new backend enum value fails the typecheck. An unknown wire value shows "Unknown", never a real status.
- **Prices.** `src/utils/property.ts`: rent shows `monthly_rent` per month, short stay shows the nightly rate per night, buy shows `base_price`.
- **Dates.** Instants are UTC (`parseServerTimestamp`). Date-only fields show as the calendar date (`formatDateOnly`).
- **Checks.** `npm test` runs `scripts/contract.test.mjs` (enum tables, helpers, tool names) and `scripts/render.test.mjs` (first render of every widget with payloads in the shape of the backend serializers). `npm run test:browser` runs the built widgets in headless Chrome with a fake host (clicks, Load More, cancel message, create, record payment, both host protocols, an unknown tool resolved as text). It needs `npm run build` first, `PLAYWRIGHT_CORE` (path to `playwright-core`) and `CHROME_PATH`. Without them it skips.

### Theme Support

Themes work on all MCP Apps hosts, not just ChatGPT:

```tsx
import { useThemeColors } from '../utils/theme';

function MyComponent() {
  const colors = useThemeColors();

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text
    }}>
      Content
    </div>
  );
}
```

## Deployment

1. Build widgets: `npm run typecheck && npm test && npm run build` in `chatgpt-widgets/`
2. Deploy backend to production
3. Ensure CORS allows all MCP client origins (`chatgpt.com`, `chat.openai.com`, and any MCP host domains)
4. Configure MCP endpoint at `https://api.360ghar.com/mcp`

## MCP Client Configuration

All clients connect to the same server URL. For end users:

**ChatGPT Apps**: Settings > Apps & Connectors > Advanced, URL: `https://api.360ghar.com/mcp`

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "360ghar": {
      "type": "streamable-http",
      "url": "https://api.360ghar.com/mcp"
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "360ghar": {
      "url": "https://api.360ghar.com/mcp",
      "transport": "streamable-http"
    }
  }
}
```

**VS Code Copilot** (`.vscode/mcp.json`):
```json
{
  "servers": {
    "360ghar": {
      "url": "https://api.360ghar.com/mcp",
      "type": "http"
    }
  }
}
```

> For agent/admin access, use `https://api.360ghar.com/mcp-admin` as the URL.

## Security Considerations

- All sensitive operations require authentication
- OAuth 2.1 with PKCE for secure token exchange
- CSP headers restrict widget network access
- Never embed secrets in widget responses
- Tool handlers are idempotent (safe for retries)
