# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment (copy and edit .env.example to .env)
cp .env.example .env

# Automated database setup with sample data
python setup_database.py
```

### Running the Application
```bash
# Start the FastAPI server with auto-reload
python run.py

# Alternative: direct uvicorn command
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Using Docker Compose (includes PostgreSQL + Redis)
docker-compose up

# Start only database services
docker-compose up db redis
```

### Database Operations
```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Check migration history
alembic history

# Test database connection
python test_supabase_connection.py
```

### Data Management
```bash
# Load sample data (comprehensive)
python load_sample_data.py

# Load simple sample data
python load_sample_data_simple.py

# Quick data loading
python quick_data_load.py

# Test API endpoints
python test_api_endpoints.py
```

## Architecture Overview

### Project Structure
- **FastAPI-based REST API** with async/await support
- **Supabase integration** for PostgreSQL + PostGIS database
- **Modular architecture** with clear separation of concerns
- **Pydantic schemas** for request/response validation
- **SQLAlchemy ORM** with async support
- **Supabase Auth integration** for secure user authentication

### Core Components

#### Database Layer (`app/models/`)
- **SQLAlchemy models** with PostGIS support for geospatial data
- **Alembic migrations** for database versioning
- **Supabase client** for additional database operations

#### API Layer (`app/api/`)
- **Versioned APIs** under `/api/v1/`
- **Endpoint modules** organized by feature (auth, properties, swipes, etc.)
- **Dependency injection** for database sessions and authentication

#### Business Logic (`app/services/`)
- **Service layer** for complex business operations
- **Swipe algorithms** for property matching
- **Location-based search** using PostGIS
- **Analytics tracking** for user behavior

#### Data Validation (`app/schemas/`)
- **Pydantic models** for API request/response validation
- **Common schemas** for shared data structures
- **Type safety** throughout the application

### Key Features Implementation

#### Supabase Authentication Integration
- **Supabase Auth** for user registration, login, and session management
- **JWT token validation** with Supabase backend verification
- **Automatic user sync** between Supabase Auth and application database
- **Social login support** via Supabase providers

#### Tinder-like Property Discovery
- **Swipe tracking** with efficient storage in `UserSwipe` model
- **Discovery algorithms** in `app/services/swipe.py`
- **Personalization** based on user preferences and behavior

#### Geospatial Search
- **PostGIS integration** for location-based queries
- **Radius-based search** for property exploration
- **Distance calculations** using geographic functions

#### Multi-purpose Property Platform
- **Rent/Buy properties** with advanced filtering
- **Short-stay bookings** with calendar management
- **Visit scheduling** with relationship manager assignment

## Development Guidelines

### Database Configuration
- Uses **Supabase** as primary database (PostgreSQL + PostGIS)
- **Environment variables** in `.env` file for database credentials
- **Connection pooling** configured in `app/core/database.py`

### Authentication Flow
- **Supabase Auth** for user registration, login, and session management
- **JWT token validation** with Supabase in `app/core/security.py`
- **User profile sync** in `app/api/api_v1/endpoints/auth.py`
- **Protected routes** using Supabase token dependency injection

### API Development Patterns
- **Async route handlers** for all endpoints
- **Database session management** via dependency injection
- **Error handling** with proper HTTP status codes
- **Response models** for consistent API responses

### Testing Strategy
- **Manual API testing** via `test_api_endpoints.py`
- **Health check endpoint** at `/health`
- **Database connection testing** via `test_supabase_connection.py`

## Important Files

### Configuration
- `app/core/config.py` - Application settings and environment variables
- `app/core/database.py` - Database connection and session management
- `app/core/supabase_client.py` - Supabase client configuration

### Entry Points
- `app/main.py` - FastAPI application factory
- `run.py` - Development server launcher
- `app/api/api_v1/api.py` - API router configuration

### Data Models
- `app/models/user.py` - User and authentication models
- `app/models/property.py` - Property and related models
- `app/models/user_interaction.py` - Swipes, favorites, search history

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

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health
- **Config Info**: http://localhost:8000/config

## Common Development Tasks

### Adding New Endpoints
1. Create route handler in appropriate `app/api/api_v1/endpoints/` file
2. Add request/response schemas in `app/schemas/`
3. Implement business logic in `app/services/`
4. Add database models if needed in `app/models/`

### Database Schema Changes
1. Modify models in `app/models/`
2. Generate migration: `alembic revision --autogenerate -m "Description"`
3. Apply migration: `alembic upgrade head`
4. Test with sample data loading scripts

### Adding New Services
1. Create service module in `app/services/`
2. Import and use in relevant API endpoints
3. Add corresponding schemas for data validation
4. Update tests and sample data as needed