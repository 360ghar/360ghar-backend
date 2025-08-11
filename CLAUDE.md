# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment (copy and edit .env.example to .env)
cp .env.example .env

# Setup database and run migrations
alembic upgrade head
```

### Running the Application
```bash
# Start the FastAPI server with auto-reload (recommended for development)
python run.py

# Alternative: direct uvicorn command
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run with OpenTelemetry instrumentation
opentelemetry-instrument \
 --traces_exporter otlp \
 --metrics_exporter none \
 --service_name my-fastapi-app \
 uvicorn app.main:app --host 0.0.0.0 --port 8000

# Using Docker Compose (includes PostgreSQL + Redis)
docker-compose up

# Start only database services
docker-compose up db redis
```

### Testing and Quality Assurance
```bash
# Currently no specific test framework is configured
# When adding tests, typically use pytest:
# pip install pytest pytest-asyncio httpx
# pytest tests/

# No specific linting configuration found
# Consider adding flake8, black, or ruff for code formatting:
# pip install ruff black
# ruff check app/
# black app/
```

### Database Operations
```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Check migration history
alembic history

# Rollback migration
alembic downgrade -1

# Check application health (includes database connection test)
curl http://localhost:8000/health
```

### Data Management
```bash
# Load comprehensive sample data (recommended)
python populate_data/load_comprehensive_data.py

# Quick data loading for development
python populate_data/load_comprehensive_data.py --quick

# Clear all existing data before loading
python populate_data/clear_all_data.py

# Environment-specific loading with custom config
PYTHONPATH=/Users/sakshammittal/Documents/360ghar/backend python populate_data/load_comprehensive_data.py
```

## Architecture Overview

### High-Level Architecture
360Ghar is a **Tinder-like real estate platform** that allows users to discover properties through swiping, explore via location-based search, schedule visits, and make short-stay bookings. The backend follows a **layered architecture** pattern with clear separation between API routes, business logic, and data access.

### Core Architecture Patterns
- **FastAPI-based REST API** with async/await for high concurrency
- **Service Layer Pattern** - Business logic separated from API endpoints
- **Repository Pattern** - Database operations abstracted in service modules
- **Dependency Injection** - Database sessions and auth managed via FastAPI dependencies
- **Schema-First Design** - Pydantic models define API contracts

### Key Architectural Decisions
1. **Supabase Integration**: Uses Supabase for both database (PostgreSQL + PostGIS) and authentication, reducing infrastructure complexity
2. **Geospatial Focus**: PostGIS enables efficient location-based queries critical for property discovery
3. **Swipe Optimization**: Custom data model for efficient storage and retrieval of millions of swipes
4. **Mobile-First API**: Designed for mobile app consumption with optimized payloads and pagination

### Core Components

#### Database Layer (`app/models/`)
- **SQLAlchemy models** with async support and PostGIS extensions
- **Optimized indexes** for swipe queries and location searches
- **Relationship mappings** for efficient data loading

#### Repository Layer (`app/repositories/`)
- **Repository Pattern** - Database access abstraction layer
- **Base repository** with common CRUD operations
- **Specialized repositories** for complex domain queries

#### API Layer (`app/api/`)
- **Versioned APIs** under `/api/v1/` for backward compatibility
- **Feature-based organization** (auth, properties, swipes, visits, bookings)
- **Standardized error handling** and response formats

#### Business Logic (`app/services/`)
- **Property Discovery Algorithm** in `swipe.py` - implements recommendation logic
- **Geospatial Services** in `property.py` - radius search and distance calculations
- **Booking Management** - handles availability and scheduling conflicts

#### Data Validation (`app/schemas/`)
- **Request/Response models** with strict validation
- **Shared base schemas** for common patterns (pagination, filters)
- **Computed fields** for API response enrichment

### Key Implementation Details

#### Authentication Flow with Supabase
1. **User Registration/Login**: Frontend calls Supabase Auth directly
2. **Token Validation**: Backend validates Supabase JWT in `app/core/security.py:get_current_user`
3. **User Sync**: `app/api/api_v1/endpoints/auth.py` syncs Supabase users with local database
4. **Protected Routes**: Use `Depends(get_current_user)` for authentication

#### Swipe System Architecture
1. **Efficient Storage**: `UserSwipe` model uses minimal storage with swipe_type enum
2. **Session Tracking**: Groups swipes by session for analytics
3. **Discovery Algorithm**: `app/services/swipe.py:get_discovery_properties` filters already-swiped properties
4. **Undo Capability**: Last swipe tracking enables undo functionality

#### Geospatial Implementation
1. **PostGIS Setup**: Location model uses `Geography` type for coordinates
2. **Distance Queries**: `ST_DWithin` for radius search, `ST_Distance` for sorting
3. **Performance**: Spatial indexes on location columns for fast queries
4. **Coordinate System**: Uses WGS84 (SRID 4326) for GPS compatibility

## Development Guidelines

### Coding Standards and Conventions
This project follows strict coding conventions as defined in `.rules/codingrules.md`:

#### File and Directory Naming
- **Models**: Singular nouns (`user.py`, `property.py`, `booking.py`)
- **Schemas**: Match corresponding model names exactly
- **Services**: Domain-based (`user.py`, `property.py`, `swipe.py`, `analytics.py`)
- **Endpoints**: Plural resource names (`users.py`, `properties.py`, `bookings.py`)

#### Function Naming Patterns
- Use descriptive action-oriented function names: `get_user_by_email()`, `create_property_from_data()`
- Database operation prefixes: `get_entity_by_id()`, `create_entity()`, `update_entity()`, `delete_entity()`
- **Snake_case** for all functions, variables, and module names
- **PascalCase** for classes and enums
- **UPPER_CASE** for constants

#### Database Conventions
- Table names: Lowercase with underscores (`users`, `user_swipes`, `property_images`) 
- Column names: Snake_case with descriptive names
- Foreign keys: `entity_id` pattern (`user_id`, `property_id`)
- Consistent timestamps: `created_at`, `updated_at` in all tables
- Enum values: Lowercase strings (`"available"`, `"sold"`, `"pending"`)

### Critical Development Patterns

#### Async Database Operations
All database operations MUST use async patterns:
```python
# Correct
async def get_property(db: AsyncSession, property_id: int):
    result = await db.execute(select(Property).where(Property.id == property_id))
    return result.scalar_one_or_none()

# Wrong - will cause errors
def get_property(db: AsyncSession, property_id: int):
    return db.query(Property).filter(Property.id == property_id).first()
```

#### Dependency Injection Pattern
Use FastAPI's dependency system for database sessions and authentication:
```python
@router.get("/properties/{id}")
async def get_property(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Implementation
```

#### Error Handling
Always use HTTPException with appropriate status codes:
```python
if not property:
    raise HTTPException(status_code=404, detail="Property not found")
```

### Error Handling Standards
Always use consistent HTTP status codes and error messages:
```python
# Authentication/Authorization errors
raise HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token"
)

# Resource not found
raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, 
    detail="Resource not found"
)

# Validation errors  
raise HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="Invalid input data"
)

# Conflict errors (booking overlaps, etc.)
raise HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Resource conflict"
)
```

### Database Best Practices
1. **Always use migrations** - Never modify database directly
2. **Test migrations locally** before applying to production
3. **Use transactions** for multi-table operations
4. **Eager loading** for relationships to avoid N+1 queries
5. **Handle concurrent access** - Use SELECT FOR UPDATE for race condition prevention
6. **Validate geospatial data** - Ensure lat/lng values are within valid ranges (-90≤lat≤90, -180≤lng≤180)

## Important Files

### Configuration and Core
- `app/core/config.py` - Application settings and environment variables
- `app/core/database.py` - Database connection and session management  
- `app/core/security.py` - Authentication and JWT token handling
- `app/core/supabase_client.py` - Supabase client configuration

### Entry Points and Routing
- `app/main.py` - FastAPI application factory with CORS, exception handling, and health endpoints
- `run.py` - Development server launcher (recommended way to start the app)
- `app/api/api_v1/api.py` - Main API router configuration that includes all endpoint modules

### Middleware (`app/middleware/`)
- `rate_limit.py` - API rate limiting and throttling
- `security.py` - Security middleware for request validation

### Data Models (app/models/)
- `user.py` - User profiles, authentication, and preferences
- `property.py` - Property listings with geospatial data
- `booking.py` - Short-stay booking management
- `visit.py` - Property visit scheduling
- `user_interaction.py` - Swipes, favorites, search history

### Business Logic (app/services/)
- `property.py` - Property search algorithms and geospatial operations
- `swipe.py` - Swipe recommendation engine and deduplication logic
- `booking.py` - Booking availability and pricing calculations
- `user.py` - User management and preference learning
- `visit.py` - Visit scheduling and relationship manager assignment
- `analytics.py` - Usage tracking and analytics

### Data Access Layer (app/repositories/)
- `base.py` - Common CRUD operations and base repository pattern
- `property.py` - Complex property queries and geospatial operations
- `user.py` - User data access and preference management
- `booking.py` - Booking-related database operations
- `visit.py` - Visit scheduling and relationship manager queries
- `user_interaction.py` - Swipe and interaction data operations

### API Endpoints (app/api/api_v1/endpoints/)
- `auth.py` - Authentication, user sync with Supabase
- `properties.py` - Property search, discovery, and details
- `swipes.py` - Swipe recording and undo functionality
- `visits.py` - Visit scheduling and management
- `bookings.py` - Short-stay booking system
- `users.py` - User profile and preference management
- `analytics.py` - Usage analytics and insights

### Schema Validation (app/schemas/)
- Pydantic models for request/response validation following the pattern: `EntityBase`, `EntityCreate`, `EntityUpdate`, `EntityInDB`, `Entity`

## Environment Variables

Required environment variables in `.env`:
```
DATABASE_URL=postgresql://username:password@host:port/database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key
SUPABASE_SECRET_KEY=your_service_role_key
SECRET_KEY=your_jwt_secret_key
REDIS_URL=redis://localhost:6379
```

## API Documentation

- **Swagger UI**: http://localhost:8000/api/v1/docs
- **ReDoc**: http://localhost:8000/api/v1/redoc
- **OpenAPI YAML Export**: http://localhost:8000/api/v1/openapi.yaml
- **Health Check**: http://localhost:8000/health
- **Config Info**: http://localhost:8000/config

## Key Architectural Patterns

### Layered Architecture
The application follows a strict layered architecture pattern:
- **API Layer** (`app/api/`): FastAPI endpoints with dependency injection
- **Schema Layer** (`app/schemas/`): Pydantic validation and serialization  
- **Service Layer** (`app/services/`): Business logic and algorithms
- **Repository Layer** (`app/repositories/`): Database access abstraction
- **Model Layer** (`app/models/`): SQLAlchemy ORM with relationships
- **Database Layer**: PostgreSQL + PostGIS + Redis

### Key Business Workflows
Based on `.rules/userworkflow.md`, the platform supports three core user experiences:
1. **Tinder-like Property Discovery**: Swipe-based property recommendations with learning algorithms
2. **Map-based Property Search**: Location and filter-based exploration with 25+ search filters
3. **Full-Service Property Platform**: Visit scheduling, short-stay bookings, and transaction management

### Critical System Features
- **Recommendation Engine**: Learns from user swipes and preferences for personalized property suggestions
- **Geospatial Search**: PostGIS-powered location queries with radius filtering and distance calculations
- **Swipe Deduplication**: Prevents duplicate swipes and maintains user interaction history
- **Visit Scheduling**: Round-robin relationship manager assignment with conflict resolution
- **Booking System**: Real-time availability checking with overbooking prevention

## Common Development Tasks

### Adding New Endpoints
1. Create route handler in appropriate `app/api/api_v1/endpoints/` file
2. Add request/response schemas in `app/schemas/` following the Entity pattern
3. Implement business logic in `app/services/`
4. Add database models if needed in `app/models/`
5. Update `app/api/api_v1/api.py` to include new router

### Database Schema Changes
1. Modify models in `app/models/`
2. Generate migration: `alembic revision --autogenerate -m "Description"`
3. Review generated migration file in `alembic/versions/`
4. Apply migration: `alembic upgrade head`
5. Test with sample data: `python populate_data/load_comprehensive_data.py --quick`

### Working with Geospatial Data
```python
# Creating location point (from models)
from geoalchemy2 import Geography
location = Geography('POINT', srid=4326, spatial_index=True)

# Querying by distance (PostGIS functions)
from sqlalchemy import func
query = select(Property).where(
    func.ST_DWithin(Property.location, user_location, radius_meters)
)

# Distance calculation for sorting
query = query.order_by(
    func.ST_Distance(Property.location, user_location)
)
```

### Debugging and Development Tools
1. **Check logs**: FastAPI logs all requests and errors
2. **Database queries**: Set `echo=True` in database engine for SQL logging
3. **Interactive API testing**: http://localhost:8000/api/v1/docs (Swagger UI)
4. **Health checks**: http://localhost:8000/health (includes database connectivity test)
5. **Configuration info**: http://localhost:8000/config (non-sensitive settings)
6. **OpenAPI export**: http://localhost:8000/api/v1/openapi.yaml

## Common Issues and Solutions

### PostGIS Not Found
If you get "type geography does not exist":
```bash
# Connect to database
psql $DATABASE_URL
# Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
```

### Alembic Migration Conflicts
If migrations fail due to existing tables:
```bash
# Check current revision
alembic current
# Stamp database with specific revision
alembic stamp head
```

### Supabase Auth Token Issues
1. Ensure `SUPABASE_URL` and `SUPABASE_KEY` are correct
2. Check token expiration in Supabase dashboard
3. Verify JWT secret matches between Supabase and backend

### Async Context Errors
If you see "async context" errors:
- Ensure all database operations use `await`
- Check that route handlers are defined as `async def`
- Verify database session is obtained via `Depends(get_db)`

## Edge Case Handling

### Geospatial Data Validation
```python
def validate_coordinates(latitude: float, longitude: float) -> bool:
    """Validate latitude/longitude values"""
    if not (-90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90")
    if not (-180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180")
    return True
```

### Concurrent Access Handling
- Use `SELECT FOR UPDATE` to prevent race conditions in swipe operations
- Handle booking conflicts with optimistic locking
- Implement retry logic for failed transactions

### Date and Time Validation
- Always use timezone-aware datetimes (`datetime.now(timezone.utc)`)
- Validate booking dates (check-in before check-out, future dates only)
- Handle invalid date formats gracefully with proper error messages

### Pagination and Limits
- Validate page parameters (min: 1)
- Constrain limit parameters (max: 100 items per page)  
- Always include pagination metadata in responses

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.