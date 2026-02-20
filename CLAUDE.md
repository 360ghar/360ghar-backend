# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Platform Overview

360 Ghar is a unified real estate platform with three integrated modules:

- **360 Ghar Core**: Real estate marketplace for buying and renting properties with swipe-based discovery, property visits, and agent coordination (`/api/v1/properties`, `/swipes`, `/visits`, `/agents`)
- **360 Stays**: Short-stay booking platform for hotels, vacation rentals, and temporary accommodations (`/api/v1/bookings`)
- **Property Management**: Comprehensive property management system for landlords and property managers (`/api/v1/pm/*`)

## Build and Development Commands

### Running the API
```bash
uv run python run.py                               # Using uv (recommended)
python run.py                                      # Direct Python
fastapi dev app/main.py --host 0.0.0.0 --port 8000 # Hot reload (FastAPI CLI)
```

> **Note:** This project uses `uv` for dependency management. The `pyproject.toml` includes `[tool.setuptools.packages.find]` configuration to prevent "Multiple top-level packages discovered" errors during the build.

### Testing
```bash
uv run pytest tests/ -v                      # All tests (using uv)
pytest tests/ -v                              # All tests
pytest tests/test_user_service.py -v         # Specific file
pytest tests/ -k "user" -v                   # By keyword
pytest tests/test_file.py::test_func -v      # Single test
pytest tests/ --cov=app --cov-report=html    # With coverage
```

### Data Population
```bash
# Using uv (recommended)
uv run python populate_data/load_comprehensive_data.py          # Full dataset (~300 properties)
uv run python populate_data/load_comprehensive_data.py --quick  # Quick load (~51 properties)
uv run python populate_data/load_comprehensive_data.py --clear  # Clear first, then load

# Or with PYTHONPATH
PYTHONPATH=$(pwd) python populate_data/load_comprehensive_data.py          # Full dataset (~300 properties)
PYTHONPATH=$(pwd) python populate_data/load_comprehensive_data.py --quick  # Quick load (~51 properties)
PYTHONPATH=$(pwd) python populate_data/load_comprehensive_data.py --clear  # Clear first, then load
```

### Database
```bash
supabase db reset   # Reset local database
supabase db push    # Apply migrations
supabase db diff    # Check pending changes
```

## Architecture Overview

### Layered Structure
```
app/
├── api/api_v1/endpoints/   # REST endpoints (thin controllers)
├── services/               # Async business logic (main logic layer)
├── repositories/           # Complex database queries
├── models/                 # SQLAlchemy ORM models
├── schemas/                # Pydantic request/response validation
├── core/                   # Config, auth, database, exceptions, logging
└── middleware/             # Rate limiting, security headers
```

### Key Patterns

**Async-First**: All database operations and services use `async/await`. Services inject `AsyncSession` via FastAPI dependencies.

**Authentication Flow**: Client authenticates directly with Supabase Auth → bearer access token → `get_current_user` dependency verifies JWT → local user sync

**Geospatial Search**: PostGIS `ST_DWithin` for radius-based property search, `ST_Distance` for sorting by proximity.

**Full-Text Search**: PostgreSQL `ts_vector` column (`__ts_vector__`) on properties table.

**Semantic Search**: Hybrid vector + text scoring via `property_embeddings` table (pgvector).

### Service Layer Pattern
```python
class PropertyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_properties(self, filters: dict) -> List[Property]:
        # Business logic here
```

### Dependency Injection
```python
@router.get("/properties/")
async def get_properties(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    return await property_service.search(db, current_user)
```

## Key Files

| Purpose | Location |
|---------|----------|
| App factory | `app/factory.py` |
| Main entry | `app/main.py` |
| API router | `app/api/api_v1/api.py` |
| Database config | `app/core/database.py` |
| Auth logic | `app/core/auth.py` |
| Custom exceptions | `app/core/exceptions.py` |
| Settings | `app/core/config.py` |
| Migrations | `supabase/migrations/` |

## Coding Conventions

- **Python 3.10+**, FastAPI, SQLAlchemy 2.x async, Pydantic v2
- **snake_case** for modules/functions/variables; **PascalCase** for classes
- Full type hints everywhere
- Custom exceptions from `app/core/exceptions.py` (e.g., `UserNotFoundException`)
- Pydantic schemas with `Config.from_attributes = True` for ORM mode
- Use `Optional[]` for nullable fields, avoid `Union[]`
- Validation with `@field_validator` decorators

## Database Models

**Core entities**: User, Property, Agent, Booking, Visit, UserSwipe, Amenity

**Property Management entities**: Lease, RentalApplication, RentCharge, RentPayment, Expense, MaintenanceRequest, Document, Inspection

**Key relationships**:
- User → Properties (as owner), Swipes, Visits, Bookings
- Property → Images, Amenities (M2M via PropertyAmenity), Visits, Bookings
- Agent → User (1:1), Visits
- Property (managed) → Leases, Tenants, Rent, Maintenance, Documents

**Enums** (in `app/models/enums.py`):
- PropertyType: house, apartment, builder_floor, room
- PropertyPurpose: buy, rent, short_stay
- BookingStatus: pending, confirmed, checked_in, checked_out, cancelled, completed
- VisitStatus: scheduled, confirmed, completed, cancelled, rescheduled

## Security

- Supabase JWT auth via `get_current_user` dependency
- Phone as primary identifier
- Role-based access: user, agent, admin
- Backend does not provide `/api/v1/auth/*` user-session endpoints; clients own login/refresh/logout via Supabase SDK
- Rate limiting: 100 req/min global
- Input validation via Pydantic schemas

## API Documentation

When running locally:
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc
- OpenAPI YAML: http://localhost:8000/api/v1/openapi.yaml
- Health: http://localhost:8000/health

## MCP Server

360Ghar exposes Model Context Protocol (MCP) servers for AI-powered integrations with OAuth 2.1 authentication (Supabase JWT).

### Server Architecture

| Endpoint | Server | Purpose |
|----------|--------|---------|
| `/mcp` | User MCP | End-user tools for owners, tenants, and regular users |
| `/mcp-admin` | Admin MCP | Administrative tools for agents and platform admins |

Both servers use OAuth 2.1 authentication (Supabase JWT) and share the same authorization endpoints at `/mcp/oauth/*`.

### User MCP Tools (`/mcp`)

**Owner Tools** (prefix: `owner_*`):
- `owner_properties_list` - List owned properties
- `owner_properties_create` - Create new property listing
- `owner_properties_get` - Get property details
- `owner_properties_update` - Update property
- `owner_properties_toggle_availability` - Toggle availability status

**Tenant Tools** (prefix: `tenant_*`):
- `tenant_lease_current` - View current lease
- `tenant_rent_history` - View rent payment history
- `tenant_maintenance_create` - Submit maintenance request
- `tenant_maintenance_list` - List maintenance requests

**Booking Tools** (prefix: `bookings_*`):
- `bookings_create` - Book a property
- `bookings_list` - List user bookings
- `bookings_get` - Get booking details
- `bookings_cancel` - Cancel a booking
- `bookings_check_availability` - Check property availability
- `bookings_get_pricing` - Get pricing information

### Admin MCP Tools (`/mcp-admin`)

**Agent Tools** (prefix: `agent_*`):
- `agent_properties_list` - List properties in agent's portfolio
- `agent_properties_get` - Get detailed property info
- `agent_properties_create_for_owner` - Create property for an owner
- `agent_properties_verify` - Verify/approve property listing
- `agent_leases_list` - List all leases
- `agent_leases_create` - Create new lease agreement
- `agent_leases_terminate` - Terminate a lease
- `agent_rent_list_due` - List overdue rent payments
- `agent_rent_record_payment` - Record rent payment
- `agent_maintenance_list` - List maintenance requests
- `agent_maintenance_update_status` - Update maintenance status
- `agent_bookings_list_all` - List all bookings
- `agent_bookings_update_status` - Update booking status
- `agent_dashboard_overview` - Get dashboard metrics

**Admin Tools** (prefix: `admin_*`):
- `admin_system_status` - System health and statistics

### MCP Client Configuration

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

### Key MCP Files

| Purpose | Location |
|---------|----------|
| User MCP server | `app/mcp/user_server.py` |
| Admin MCP server | `app/mcp/admin_server.py` |
| Shared utilities | `app/mcp/utils.py` |
| Validation schemas | `app/mcp/validation.py` |
| Auth provider | `app/mcp/auth_provider.py` |
| Authorization | `app/services/pm_authz.py` |
