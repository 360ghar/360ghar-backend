# ChatGPT App Integration & MCP Server Guide

This guide explains how to test the 360Ghar backend integration with ChatGPT using the Model Context Protocol (MCP). It covers setup, testing, available tools, and debugging.

---

## Table of Contents

1. [Overview](#overview)
2. [How MCP Server is Connected](#how-mcp-server-is-connected)
3. [Prerequisites](#prerequisites)
4. [Setup Instructions](#setup-instructions)
5. [Authentication](#authentication)
6. [Available Tools/APIs](#available-toolsapis)
7. [Example Prompts & Expected Responses](#example-prompts--expected-responses)
8. [Common Errors & Debugging](#common-errors--debugging)

---

## Overview

The 360Ghar backend exposes a **Model Context Protocol (MCP)** HTTP server that allows AI assistants like ChatGPT to interact with the real estate platform. The MCP server provides tools for:

- **Property Search** - Search and discover properties
- **Property Details** - Get full property information
- **Swipes (Like/Dislike)** - Tinder-like property swiping
- **Visit Scheduling** - Schedule property visits
- **User Profile Management** - View and update user preferences
- **Agent Information** - Get assigned relationship manager details
- **Blog Content** - Search and read blog posts

---

## How MCP Server is Connected

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      ChatGPT / MCP Client                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (OAuth 2.1 Bearer Token)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  /mcp endpoint (FastMCP HTTP Transport)                │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  SupabaseAuthProvider (OAuth 2.1 + JWT)          │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  MCP Tools (properties.search, swipes.like, etc.)│  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              PostgreSQL + Supabase Auth                      │
└─────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Description |
|------|-------------|
| `app/main.py` | Mounts MCP app at `/mcp` endpoint |
| `app/mcp/server.py` | Defines all MCP tools (20+ tools) |
| `app/mcp/auth_provider.py` | Handles OAuth 2.1 & Supabase JWT authentication |
| `app/mcp/validation.py` | Input validation for MCP tools |
| `app/mcp/errors.py` | Standardized error responses |

### Endpoints

| Environment | MCP Endpoint | OAuth Authorize | OAuth Token |
|-------------|--------------|-----------------|-------------|
| **Development** | `http://localhost:8000/mcp` | `http://localhost:8000/mcp/oauth/authorize` | `http://localhost:8000/mcp/oauth/token` |
| **Production** | `https://api.360ghar.com/mcp` | `https://api.360ghar.com/mcp/oauth/authorize` | `https://api.360ghar.com/mcp/oauth/token` |

---

## Prerequisites

Before testing, ensure you have:

1. **Python 3.10+** installed
2. **Backend running locally** (or access to production)
3. **Valid Supabase credentials** (for authentication)
4. **Database with sample data** (optional but recommended)

---

## Setup Instructions

### Step 1: Clone and Install Dependencies

```bash
git clone https://github.com/your-org/360ghar-backend.git
cd 360ghar-backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
DATABASE_URL=postgresql://user:pass@localhost:5432/ghar360
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key
SUPABASE_SECRET_KEY=your_service_role_key
SECRET_KEY=your_jwt_secret
ENVIRONMENT=development
```

### Step 3: Start the Server

```bash
python run.py
```

Or with hot-reload:

```bash
fastapi dev app/main.py --port 8000 --host 0.0.0.0
```

### Step 4: Verify MCP is Running

Open browser and check:
- Health: `http://localhost:8000/health`
- API Docs: `http://localhost:8000/api/v1/docs`

---

## Authentication

The MCP server supports two authentication methods:

### Method 1: Supabase JWT (Recommended for Testing)

1. Login via Supabase Auth to get a JWT token
2. Use the token as Bearer authentication in MCP requests

```json
{
  "Authorization": "Bearer <supabase_jwt_token>"
}
```

### Method 2: OAuth 2.1 Flow (For ChatGPT)

For ChatGPT integration, configure the MCP client:

```json
{
  "mcpServers": {
    "ghar360": {
      "transport": "http",
      "url": "https://api.360ghar.com/mcp"
    }
  }
}
```

The OAuth flow works as follows:
1. Client requests authorization at `/mcp/oauth/authorize`
2. User authenticates via browser (phone + password)
3. Client receives authorization code
4. Client exchanges code for access token at `/mcp/oauth/token`
5. Client uses access token for subsequent MCP tool calls

### Getting a Test Token

For local testing, you can use the `auth.set_jwt` tool:

```python
# Using MCP client
await mcp.call_tool("auth.set_jwt", {"jwt": "your_supabase_jwt_here"})
```

---

## Available Tools/APIs

### 🔐 Authentication Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `auth.set_jwt` | Store JWT for session | No |
| `auth.logout` | Clear session and revoke token | Yes |
| `auth.refresh` | Refresh access token | No |
| `auth.whoami` | Get current authenticated user | Yes |

### 🏠 Property Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `properties.search` | Basic property search | No |
| `properties.search_advanced` | Advanced search with filters | No |
| `properties.get` | Get single property details | No |
| `discovery.feed` | Get personalized property feed | Optional |

### ❤️ Swipe Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `swipes.like` | Like a property | Yes |
| `swipes.dislike` | Dislike a property | Yes |
| `swipes.undo` | Undo last swipe | Yes |
| `shortlist.list` | List liked properties | Yes |

### 📅 Visit Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `visits.schedule` | Schedule a property visit | Yes |
| `visits.list` | List user's visits | Yes |
| `visits.cancel` | Cancel a visit | Yes |

### 👤 User Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `user.profile` | Get full user profile | Yes |
| `user.update_preferences` | Update search preferences | Yes |

### 🧑‍💼 Agent Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `agents.get_assigned` | Get assigned relationship manager | Yes |

### 📝 Blog Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `blog.search` | Search blog posts | No |
| `blog.get` | Get blog post by ID/slug | No |

### ⚙️ System Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `system.status` | Get system status and features | No |

---

## Example Prompts & Expected Responses

### 1. Check System Status

**Prompt:**
```
Check the system status
```

**Tool Called:** `system.status`

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "status": "operational",
    "version": "2.0.0",
    "auth": {
      "status": "unauthenticated",
      "user": null,
      "methods": ["supabase_jwt", "oauth"]
    },
    "features": {
      "properties": { "search": true, "get": true },
      "swipes": { "like": true, "dislike": true },
      "visits": { "schedule": true, "list": true }
    }
  }
}
```

---

### 2. Search Properties

**Prompt:**
```
Search for 2BHK apartments in Gurgaon under 50 lakhs
```

**Tool Called:** `properties.search_advanced`

**Parameters:**
```json
{
  "search_query": "Gurgaon",
  "property_type": "apartment",
  "bedrooms": 2,
  "max_price": 5000000
}
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "total": 15,
    "page": 1,
    "limit": 20,
    "total_pages": 1,
    "items": [
      {
        "id": 101,
        "title": "Modern 2BHK in Sector 49",
        "property_type": "apartment",
        "city": "Gurgaon",
        "locality": "Sector 49",
        "price": 4500000,
        "bedrooms": 2,
        "bathrooms": 2,
        "area_sqft": 1200,
        "main_image_url": "https://..."
      }
    ]
  }
}
```

---

### 3. Get Property Details

**Prompt:**
```
Show me details of property ID 101
```

**Tool Called:** `properties.get`

**Parameters:**
```json
{
  "property_id": 101
}
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "property": {
      "id": 101,
      "title": "Modern 2BHK in Sector 49",
      "description": "Spacious apartment with modern amenities...",
      "property_type": "apartment",
      "purpose": "sale",
      "full_address": "Block A, Sector 49, Gurgaon",
      "city": "Gurgaon",
      "locality": "Sector 49",
      "base_price": 4500000,
      "bedrooms": 2,
      "bathrooms": 2,
      "area_sqft": 1200,
      "amenities": [
        {"id": 1, "title": "Swimming Pool", "icon": "pool"},
        {"id": 2, "title": "Gym", "icon": "fitness"}
      ],
      "images": [
        {"url": "https://...", "caption": "Living Room"}
      ]
    },
    "user_context": null
  }
}
```

---

### 4. Like a Property

**Prompt:**
```
I like this property, add it to my shortlist
```

**Tool Called:** `swipes.like`

**Parameters:**
```json
{
  "property_id": 101
}
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "liked": true,
    "property_id": 101
  }
}
```

---

### 5. Schedule a Visit

**Prompt:**
```
Schedule a visit to property 101 for tomorrow at 3 PM
```

**Tool Called:** `visits.schedule`

**Parameters:**
```json
{
  "property_id": 101,
  "scheduled_date_iso": "2026-01-03T15:00:00+05:30",
  "special_requirements": null
}
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "visit_id": 42,
    "property_id": 101,
    "scheduled_date": "2026-01-03T15:00:00+05:30",
    "status": "scheduled"
  }
}
```

---

### 6. View My Shortlist

**Prompt:**
```
Show me my liked properties
```

**Tool Called:** `shortlist.list`

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "total": 3,
    "page": 1,
    "limit": 20,
    "items": [
      {
        "id": 101,
        "title": "Modern 2BHK in Sector 49",
        "city": "Gurgaon",
        "price": 4500000,
        "bedrooms": 2,
        "liked_at": "2026-01-02T14:30:00Z"
      }
    ]
  }
}
```

---

### 7. Get My Profile

**Prompt:**
```
Show my profile
```

**Tool Called:** `user.profile`

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "user": {
      "id": 1,
      "email": "user@example.com",
      "phone": "+919876543210",
      "full_name": "John Doe",
      "role": "user",
      "is_verified": true
    },
    "preferences": {
      "preferred_cities": ["Gurgaon", "Delhi"],
      "budget_min": 3000000,
      "budget_max": 8000000
    },
    "stats": {
      "total_swipes": 25,
      "liked_count": 8,
      "disliked_count": 17,
      "like_percentage": 32
    },
    "agent": {
      "id": 5,
      "name": "Rahul Sharma",
      "phone": "+919999888877",
      "email": "rahul@360ghar.com"
    }
  }
}
```

---

### 8. Search Blog Posts

**Prompt:**
```
Find articles about home buying tips
```

**Tool Called:** `blog.search`

**Parameters:**
```json
{
  "query": "home buying tips"
}
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "total": 5,
    "items": [
      {
        "id": 10,
        "title": "10 Tips for First-Time Home Buyers",
        "slug": "first-time-home-buyer-tips",
        "excerpt": "Buying your first home is exciting...",
        "categories": ["Buying Guide"],
        "created_at": "2025-12-15T10:00:00Z"
      }
    ]
  }
}
```

---

## Common Errors & Debugging

### Error: "Not authenticated"

**Response:**
```json
{
  "success": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Not authenticated"
  }
}
```

**Cause:** The tool requires authentication but no valid token was provided.

**Solution:**
1. Ensure you've logged in via OAuth or set a JWT
2. Check if the token has expired
3. Verify the token format (should be a valid JWT or OAuth access token)

---

### Error: "Invalid JWT format"

**Response:**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_INPUT",
    "message": "Invalid JWT format"
  }
}
```

**Cause:** The JWT token provided doesn't have the correct structure.

**Solution:**
1. JWT should have 3 parts separated by dots (header.payload.signature)
2. Get a fresh token from Supabase Auth

---

### Error: "Property not found"

**Response:**
```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Property with id 9999 not found"
  }
}
```

**Cause:** The requested property ID doesn't exist in the database.

**Solution:**
1. Verify the property ID is correct
2. Use `properties.search` to find valid property IDs

---

### Error: "Invalid latitude/longitude"

**Response:**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_INPUT",
    "message": "Invalid latitude (must be -90 to 90)"
  }
}
```

**Cause:** Location coordinates are out of valid range.

**Solution:**
- Latitude must be between -90 and 90
- Longitude must be between -180 and 180

---

### Error: "Internal server error"

**Response:**
```json
{
  "success": false,
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Failed to search properties: ..."
  }
}
```

**Cause:** Server-side error (database connection, service failure, etc.)

**Solution:**
1. Check server logs: `python run.py` output
2. Verify database connection in `.env`
3. Check if required services (PostgreSQL) are running
4. Review Sentry dashboard for detailed error traces

---

### Debugging Tips

1. **Enable Debug Logging**
   ```bash
   export LOG_LEVEL=DEBUG
   python run.py
   ```

2. **Check Server Health**
   ```bash
   curl http://localhost:8000/health
   ```

3. **Test API Directly**
   Visit `http://localhost:8000/api/v1/docs` to test REST endpoints

4. **Verify Database**
   ```bash
   python -c "from app.core.database import engine; print('DB OK')"
   ```

5. **Check Token Validity**
   Use `auth.whoami` tool to verify your authentication status

---

## Quick Reference Card

| Action | Tool Name | Key Parameters |
|--------|-----------|----------------|
| Search properties | `properties.search` | `search_query`, `latitude`, `longitude` |
| Advanced search | `properties.search_advanced` | `property_type`, `bedrooms`, `min_price`, `max_price` |
| Get property | `properties.get` | `property_id` |
| Like property | `swipes.like` | `property_id` |
| Dislike property | `swipes.dislike` | `property_id` |
| Schedule visit | `visits.schedule` | `property_id`, `scheduled_date_iso` |
| View visits | `visits.list` | - |
| My shortlist | `shortlist.list` | `page`, `limit` |
| My profile | `user.profile` | - |
| My agent | `agents.get_assigned` | - |

---

## Need Help?

- **API Documentation**: http://localhost:8000/api/v1/docs
- **Health Check**: http://localhost:8000/health
- **Contact**: dev@360ghar.com

---

## Manual Testing (Without ChatGPT)

If ChatGPT OAuth isn't working (e.g., ngrok callback issues), you can test MCP tools manually.

### Option 1: Python Test Script

We've created a test script at `tools/test_mcp_tools.py`:

```bash
# Run all tests
python tools/test_mcp_tools.py

# Interactive mode
python tools/test_mcp_tools.py -i
```

**Before running**, edit the script and update:
```python
TEST_PHONE = "+919876543210"  # Your phone number
TEST_PASSWORD = "your_password"  # Your password
```

### Option 2: Test via REST API (Swagger)

1. Open http://localhost:8000/api/v1/docs
2. Click **Authorize** button
3. Login with your credentials
4. Test any endpoint directly

### Option 3: PowerShell/curl Commands

**Test Health:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health"
```

**Test Property Search (via REST API):**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/properties/?limit=5"
```

**Test MCP OAuth Metadata:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/.well-known/oauth-authorization-server/mcp/oauth"
```

### MCP Tool Testing Flow

1. **Get Access Token** - Login via `/api/v1/auth/login/`
2. **Call MCP Tools** - Use the token in Authorization header
3. **Verify Results** - Check the JSON responses

### Troubleshooting ChatGPT Connection

| Issue | Solution |
|-------|----------|
| "Unsafe URL" | Use ngrok or production HTTPS URL |
| "RFC 7591 not supported" | Ensure Dynamic Client Registration endpoint is deployed |
| "Something went wrong" after login | ngrok callback blocked - try production URL or Cloudflare Tunnel |
| Token exchange fails | Check server logs for errors |

