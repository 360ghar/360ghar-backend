# 360Ghar ChatGPT App

This directory contains the ChatGPT App integration for 360Ghar, enabling users to interact with the real estate platform through ChatGPT's conversational interface.

## Architecture

The ChatGPT App is built on the **Model Context Protocol (MCP)** standard and consists of:

1. **MCP Server** (`/mcp`) - Exposes tools that ChatGPT can call
2. **Widget UI** (`chatgpt-widgets/`) - React components rendered in ChatGPT iframes
3. **Response Formatters** - Format tool outputs for ChatGPT consumption

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     ChatGPT     │────▶│   MCP Server    │────▶│   360Ghar API   │
│  (User Chat)    │◀────│   (/mcp)        │◀────│   (Backend)     │
└────────┬────────┘     └─────────────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐
│  Widget iframe  │
│  (Rich UI)      │
└─────────────────┘
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
├── response_formatter.py # ChatGPT-specific response formatting
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
│   │   ├── bridge.ts     # OpenAI bridge hooks (useToolOutput, etc.)
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

3. Test with MCP Inspector:
   ```bash
   npx @mcpjam/inspector --url https://your-ngrok-url.ngrok.io/mcp --oauth --verbose
   ```

4. Connect to ChatGPT:
   - Go to ChatGPT Settings → Apps & Connectors → Advanced settings
   - Enable developer mode
   - Add a new connector with your ngrok URL + `/mcp`

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
| `discovery.search` | Search properties with filters | No |
| `discovery.property.get` | Get full property details | No |
| `discovery.feed` | Get discovery feed for swiping | No |
| `discovery.amenities` | List available amenities | No |
| `discovery.swipe` | Record like/pass on property | Yes |
| `discovery.shortlist` | Get liked properties | Yes |
| `discovery.recommendations` | Get AI recommendations | Yes |

### Visit Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `visits.schedule` | Schedule a property visit | Yes |
| `visits.list` | List user's visits | Yes |
| `visits.get` | Get visit details | Yes |
| `visits.cancel` | Cancel a scheduled visit | Yes |

### Tenant Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `tenant.lease.current` | Get current lease | Yes |
| `tenant.rent.dues` | View outstanding rent | Yes |
| `tenant.rent.history` | Get rent payment history | Yes |
| `tenant.maintenance.create` | Submit maintenance request | Yes |
| `tenant.maintenance.list` | List maintenance requests | Yes |

### Owner Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `owner.properties.list` | List owned properties | Yes |
| `owner.properties.create` | Create new listing | Yes |
| `owner.properties.get` | Get property details | Yes |
| `owner.properties.update` | Update property | Yes |
| `owner.dashboard.overview` | Get portfolio dashboard | Yes |
| `owner.leases.list` | List leases for properties | Yes |
| `owner.leases.get` | Get lease details | Yes |
| `owner.leases.terminate` | Terminate a lease | Yes |
| `owner.rent.status` | View rent collection status | Yes |
| `owner.rent.record_payment` | Record a rent payment | Yes |
| `owner.rent.history` | View payment history | Yes |
| `owner.maintenance.list` | List maintenance requests | Yes |
| `owner.maintenance.update` | Update maintenance status | Yes |

## Widget Development

### Using the OpenAI Bridge

```tsx
import { useToolOutput, useCallTool, useSendMessage } from '../utils/bridge';

function MyWidget() {
  // Get tool output data
  const data = useToolOutput<MyDataType>();

  // Call other tools
  const callTool = useCallTool();
  await callTool('discovery.search', { city: 'Mumbai' });

  // Send follow-up messages
  const sendMessage = useSendMessage();
  sendMessage('Show me details for property 123');
}
```

### Theme Support

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

1. Build widgets: `npm run build` in `chatgpt-widgets/`
2. Deploy backend to production
3. Ensure CORS allows `chatgpt.com` and `chat.openai.com`
4. Configure MCP endpoint at `https://api.360ghar.com/mcp`

## ChatGPT Client Configuration

For end users connecting to 360Ghar:

```json
{
  "mcpServers": {
    "360ghar": {
      "transport": "http",
      "url": "https://api.360ghar.com/mcp"
    }
  }
}
```

## Security Considerations

- All sensitive operations require authentication
- OAuth 2.1 with PKCE for secure token exchange
- CSP headers restrict widget network access
- Never embed secrets in widget responses
- Tool handlers are idempotent (safe for retries)
