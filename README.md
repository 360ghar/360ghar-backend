# 360 Ghar Backend

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Framework](https://img.shields.io/badge/framework-FastAPI-green.svg)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/database-PostgreSQL%20+%20PostGIS-blue.svg)](https://www.postgresql.org/)

A high-performance, modern backend powering 360 Ghar's unified real estate platform. Built with FastAPI and PostgreSQL, this API serves three integrated modules:

- **360 Ghar Core**: Real estate marketplace for buying and renting properties with swipe-based discovery, property visits, and agent coordination
- **360 Stays**: Short-stay booking platform for hotels, vacation rentals, and temporary accommodations
- **Property Management**: Comprehensive property management system for landlords and property managers (leases, rent collection, maintenance, reporting)

## Table of Contents

- [About The Project](#about-the-project)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Getting Started](#getting-started)
- [Running with Docker](#running-with-docker)
- [Environment Configuration](#environment-configuration)
- [API Documentation](#api-documentation)
- [MCP HTTP Server](#mcp-http-server)
- [Key Implementation Details](#key-implementation-details)
- [Contributing](#contributing)
- [License](#license)

## About The Project

360 Ghar is a unified real estate platform serving the complete property lifecycle:

- **360 Ghar Core** revolutionizes property discovery through an engaging, swipe-based interface combined with powerful map-based search and professional agent assistance for buying and renting properties.
- **360 Stays** provides a complete short-stay booking system with availability checks, dynamic pricing, and guest management for hotels and vacation rentals.
- **Property Management** empowers landlords and property managers with tools for tenant management, lease tracking, rent collection, maintenance handling, and financial reporting.

All three modules share a common backend infrastructure, user authentication, and property database.

## Overview Video

[![360 Ghar Backend Overview](.wiki/video/overview.mp4)](.wiki/video/overview.mp4)

A 2-3 minute silent walkthrough of the platform's six modules and architecture. Read the [full wiki](https://github.com/360ghar/backend/wiki).

## Key Features

### 360 Ghar Core (Real Estate Marketplace)
- **Tinder-like Property Swiping**: Intuitive swipe interface to like or pass on properties
- **Advanced Property Search**: Unified endpoint supporting geospatial, full-text, and filtered search
- **Property Visit Scheduling**: Agent-managed visit coordination with automatic assignment
- **Agent Management**: Comprehensive agent system with load balancing and performance tracking
- **User Personalization**: Preference learning from user interactions and search history

### 360 Stays (Short-Stay Bookings)
- **Short-stay Bookings**: Complete booking system with availability checks and pricing
- **Dynamic Pricing**: Configurable daily rates and minimum stay requirements
- **Guest Management**: Booking lifecycle from reservation to checkout

### Property Management
- **Tenant & Lease Management**: Track tenants, leases, and rental applications
- **Rent Collection**: Manual-first rent ledger with charge generation and payment tracking
- **Maintenance Requests**: Work order management for property upkeep
- **Document Vault**: Secure storage for leases, receipts, and property documents
- **Financial Reporting**: Rent roll, income statements, P&L, and occupancy reports

### Technical Highlights
- **Modern & Fast**: Built with **FastAPI** for high performance and automatic API documentation
- **Fully Async**: Asynchronous architecture from API to database operations
- **Geospatial Powered**: **PostgreSQL + PostGIS** for efficient location-based queries
- **Secure Authentication**: **Supabase Auth** integration with phone-based primary authentication
- **Performance Optimized**: Designed for **PgBouncer** compatibility and scalable connection pooling
- **Production Ready**: **Sentry** integration, comprehensive logging, and error handling
- **Containerized**: Full **Docker** support with **Docker Compose** for development

## Tech Stack

| Category              | Technology                                                    |
| --------------------- | ------------------------------------------------------------- |
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/)                     |
| **Database**          | [PostgreSQL](https://www.postgresql.org/) + [PostGIS](https://postgis.net/) |
| **ORM**               | [SQLAlchemy 2.0+ (Async)](https://www.sqlalchemy.org/)      |
| **Data Validation**   | [Pydantic](https://docs.pydantic.dev/)                       |
| **Authentication**    | [Supabase Auth](https://supabase.com/docs/guides/auth)       |
| **Caching**           | [Redis](https://redis.io/) (optional)                        |
| **Migrations**        | [Supabase Migrations](https://supabase.com/docs/guides/cli) |
| **Observability**     | [Sentry](https://sentry.io/)                                 |
| **Containerization**  | [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/) |
| **Geospatial**        | [GeoAlchemy2](https://geoalchemy-2.readthedocs.io/)          |

## Project Structure

```
app/
├── api/                 # API endpoints and routing
│   └── api_v1/
│       └── endpoints/   # Individual endpoint modules
├── config/              # Compatibility config package; implementation remains in core/config.py
├── core/                # Core components (config, db, auth, logging)
├── infrastructure/      # App factory helpers, adapters, lifespan, middleware wiring
├── middleware/          # Custom middleware (rate limiting, security)
├── models/              # SQLAlchemy ORM models and enums  
├── modules/             # Reserved namespace for future physical domain packages
├── schemas/             # Pydantic schemas for data validation
├── services/            # Business logic and database operations (legacy implementation layer)
├── shared/              # Reserved namespace for future physical shared packages
└── utils/               # Utility functions

supabase/
└── migrations/          # Database schema migrations

populate_data/           # Legacy data files (preserved for reference)
seed_data/               # Data seeding system (hardcoded, seed, generated categories)
tests/                   # Test files
```

## API Endpoints

All endpoints are prefixed with `/api/v1`.

### 🔑 Authentication Model
- Clients authenticate directly with Supabase Auth SDK (phone-first, email optional).
- Backend expects `Authorization: Bearer <supabase_access_token>` for protected routes.
- Backend no longer exposes `/api/v1/auth/*` user-session endpoints.

### 👤 Users (`/users`)  
- `GET /profile/`: Get current user profile
- `PUT /profile/`: Update user profile information
- `PUT /preferences/`: Update property search preferences
- `PUT /location/`: Update user's current location

### 🏠 Properties (`/properties`)
- `GET /`: **Unified Property Search** with geospatial, text search, and advanced filtering
- `GET /recommendations/`: Get personalized property recommendations  
- `GET /{property_id}/`: Get detailed property information
- `POST /`: Create new property (authenticated users)
- `PUT /{property_id}/`: Update property (property owners)
- `DELETE /{property_id}/`: Delete property (property owners)

### ↔️ Swipes (`/swipes`)
- `POST /`: Record property swipe (like/pass)
- `GET /`: Get swipe history with full search and filtering capabilities
- `DELETE /undo/`: Undo last swipe action
- `PUT /{swipe_id}/toggle/`: Toggle like status of previously swiped property
- `GET /stats/`: Get user swipe statistics

### 📅 Visits (`/visits`)
- `POST /`: Schedule property visit
- `GET /`: List user's visits (all/upcoming/past)  
- `GET /{visit_id}/`: Get visit details
- `POST /reschedule/`: Reschedule existing visit
- `POST /cancel/`: Cancel scheduled visit

### 🏨 Bookings (`/bookings`)
- `POST /`: Create short-stay booking
- `GET /`: List user's bookings  
- `GET /{booking_id}/`: Get booking details
- `POST /check-availability/`: Check property availability
- `POST /calculate-pricing/`: Get booking price breakdown
- `POST /cancel/`: Cancel booking

### 🧑‍💼 Agents (`/agents`)
- `GET /assigned/`: Get user's assigned agent
- `POST /assign/`: Assign agent to user (auto-assigns if no agent specified)
- `GET /available/`: List available agents
- `GET /{agent_id}/`: Get agent details
- `GET /{agent_id}/stats/`: Get agent performance statistics

### 🏢 Property Management (`/pm`)
- `/pm/dashboard`: Portfolio overview and metrics
- `/pm/properties`: Managed properties CRUD
- `/pm/tenants`: Tenant directory
- `/pm/applications`: Rental applications and forms
- `/pm/leases`: Lease management
- `/pm/rent`: Rent charges and payments
- `/pm/expenses`: Expense tracking
- `/pm/maintenance`: Maintenance requests
- `/pm/documents`: Document vault
- `/pm/inspections`: Property inspections
- `/pm/reports`: Financial reports

## Getting Started

### Prerequisites

- [Python 3.10+](https://www.python.org/)
- [Docker](https://www.docker.com/get-started) and [Docker Compose](https://docs.docker.com/compose/install/)
- A [Supabase](https://supabase.com/) project for authentication

### Local Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/360ghar-backend.git
   cd 360ghar-backend
   ```

2. **Install dependencies:**

   **Option A: Using uv (Recommended)**
   ```bash
   # Install uv if not already installed
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Install dependencies (reads pyproject.toml)
   uv sync
   ```

   **Option B: Using pip**
   ```bash
   # Create virtual environment
   python -m venv .venv

   # Activate it (Linux/Mac)
   source .venv/bin/activate
   # Or on Windows:
   # .venv\Scripts\activate

   # Install dependencies
   uv sync
   ```

   > **Note:** This project uses `uv` for dependency management. Dependencies are defined in `pyproject.toml` and locked in `uv.lock`.

4. **Set up environment variables:**
   ```bash
   cp .env.example .env
   ```
   Edit the `.env` file with your database, Supabase, and other credentials.

5. **Start database services:**
   ```bash
   docker-compose up -d db redis
   ```

6. **Apply database migrations:**
   ```bash
   supabase db push
   ```

7. **Load sample data (optional):**
   ```bash
   # Load all seed data (hardcoded + generated)
   uv run python seed_data/01_load_all.py

   # Quick mode — skip generated activity
   uv run python seed_data/01_load_all.py --only hardcoded,seed

   # Clear and reload
   uv run python seed_data/02_clear_data.py --confirm
   uv run python seed_data/01_load_all.py
   ```

8. **Start the application:**

   **If using uv (Recommended):**
   ```bash
   # Run with uv (no need to activate virtual environment)
   uv run python run.py

   # Or using FastAPI CLI with hot reload (recommended for development)
   uv run fastapi dev app/main.py --port 3600 --host 0.0.0.0
   ```

   **If using pip (with activated virtual environment):**
   ```bash
   # Run directly
   python run.py

   # Or using FastAPI CLI with hot reload (recommended for development)
   fastapi dev app/main.py --port 3600 --host 0.0.0.0
   ```

The API will be available at `http://localhost:3600`.

> **💡 Development Tip**: FastAPI CLI provides better hot reload performance and additional development features. It's the recommended way for active development.

## MCP HTTP Server

The backend exposes Model Context Protocol (MCP) HTTP servers for AI assistants and MCP‑aware clients.

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/mcp` | User MCP server (owners, tenants, regular users) |
| `/mcp-admin` | Admin MCP server (agents, administrators) |

### Authentication
Both servers use OAuth 2.1 authentication (phone + password via Supabase):
- **Authorization:** `GET /mcp/oauth/authorize` (browser-based login + consent page)
- **Token:** `POST /mcp/oauth/token`
- **Authorization server metadata:** `GET /.well-known/oauth-authorization-server/mcp/oauth`

### Client Configuration

For end-user applications:
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

For agent/admin applications:
```json
{
  "mcpServers": {
    "ghar360-admin": {
      "transport": "http",
      "url": "https://api.360ghar.com/mcp-admin"
    }
  }
}
```

After configuration, the client will initiate an OAuth flow in the browser; once authorized, it can call tools such as property search, swipes, and visit scheduling over MCP.

## Running with Docker

To run the entire stack in containers:

```bash
# Build and start all services
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

## Environment Configuration

Create a `.env` file based on `.env.example`:

```env
# Database Configuration
DATABASE_URL=postgresql://username:password@localhost:5432/ghar360

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your_publishable_key
SUPABASE_SECRET_KEY=your_service_role_key
# Storage uses Cloudinary (configured via CLOUDINARY_* env vars)

# JWT Configuration
SECRET_KEY=your_jwt_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Optional Services
REDIS_URL=redis://localhost:6379
SENTRY_DSN=your_sentry_dsn_here

# Environment
ENVIRONMENT=development
 
# Push Notifications (FCM + Supabase)
FIREBASE_PROJECT_ID=your_firebase_project_id
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json
ENABLE_NOTIF_SCHEDULER=false
NOTIF_SCHED_TZ=Asia/Kolkata

# Vector Embeddings / Semantic Search
GOOGLE_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite-preview
GEMINI_EMBED_MODEL=text-embedding-004
VECTOR_SYNC_ENABLED=true
# Either provide CRON schedule or interval seconds (defaults to CRON below)
VECTOR_SYNC_CRON=*/10 * * * *
VECTOR_SYNC_INTERVAL_SECONDS=300
VECTOR_SYNC_BATCH_SIZE=500
VECTOR_SYNC_MAX_RETRIES=3

### One-time backfill
Run a single incremental sync pass (first run will process all properties):

```bash
uv run python -m app.vector.backfill
```

The service creates a `property_embeddings` table (pgvector) and tracks incremental progress in `vector_sync_state`.
```

## API Documentation

Once running, access the interactive API documentation:

- **Swagger UI**: [http://localhost:3600/api/v1/docs](http://localhost:3600/api/v1/docs)
- **ReDoc**: [http://localhost:3600/api/v1/redoc](http://localhost:3600/api/v1/redoc)
- **OpenAPI YAML**: [http://localhost:3600/api/v1/openapi.yaml](http://localhost:3600/api/v1/openapi.yaml)

Additional endpoints:
- **Health Check**: [http://localhost:3600/health](http://localhost:3600/health)
- **Config Info**: [http://localhost:3600/config](http://localhost:3600/config)

### Notifications API

- `POST /api/v1/notifications/devices/register` — Register or refresh device token (uses auth header when present)
- `POST /api/v1/notifications/send/token` — Send to a single token (admin only)
- `POST /api/v1/notifications/send/user` — Send to all tokens for a user (admin only)
- `POST /api/v1/notifications/send/topic` — Broadcast to an FCM topic (admin only)
- `POST /api/v1/notifications/send/bulk` — Bulk send to up to 500 tokens (admin only)
- `POST /api/v1/notifications/deliveries/{delivery_id}/opened` — Mark a delivery as opened

## Key Implementation Details

### Authentication System
- **Phone-First Authentication**: Uses phone numbers as primary identifiers with Supabase Auth
- **JWT Token Validation**: Local token verification for optimal performance
- **Flexible Verification**: Supports both email and phone verification
- **User Sync**: Automatic synchronization between Supabase and local database

### Database Architecture
- **Async SQLAlchemy 2.0+**: Modern async database operations
- **PostGIS Integration**: Efficient geospatial queries with proper indexing
- **PgBouncer Ready**: Configured for production connection pooling
- **Full-Text Search**: PostgreSQL native text search capabilities
- **Comprehensive Indexing**: Optimized indexes for common query patterns

### Property Search System
- **Unified Search Endpoint**: Single endpoint supporting multiple search types
- **Geospatial Optimization**: PostGIS `ST_DWithin` for radius-based searches
- **Full-Text Search**: PostgreSQL TSVECTOR for relevant text matching
- **Semantic Search**: Hybrid vector + text relevance scoring for richer discovery
- **Advanced Filtering**: Support for 25+ property filters
- **Pagination**: Efficient cursor-based pagination for large datasets
- **Endpoints**: `GET /api/v1/properties` (set `semantic_search=true&q=` for hybrid) and `GET /api/v1/properties/semantic-search` (pure semantic + filters)

### Agent Management
- **Auto-Assignment**: Round-robin agent assignment based on workload
- **Load Balancing**: Distributes users across available agents
- **Performance Tracking**: Comprehensive agent statistics and metrics
- **Availability Management**: Real-time agent availability tracking

### Performance Optimizations
- **Async Throughout**: Non-blocking operations from API to database
- **Efficient Queries**: Optimized database queries with proper joins and indexes
- **Caching Ready**: Redis integration for caching expensive operations
- **Error Handling**: Comprehensive error handling with Sentry integration

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

**360 Ghar Development Team** - [dev@360ghar.com](mailto:dev@360ghar.com)

Project Link: [https://github.com/your-username/360ghar-backend](https://github.com/your-username/360ghar-backend)
