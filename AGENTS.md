# Repository Guidelines

This repository contains the 360 Ghar unified real estate platform backend, serving three integrated modules: 360 Ghar Core (buy/rent marketplace), 360 Stays (short-stay bookings), and Property Management (landlord/manager tools).

## Build, Test, and Development Commands

### Setup
```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies and run
docker-compose up -d db redis
```

### Running the API
```bash
python run.py
# or hot reload:
fastapi dev app/main.py --host 0.0.0.0 --port 8000
```

### Running Tests
```bash
pytest tests/ -v                              # all tests
pytest tests/test_user_service.py -v         # specific file
pytest tests/ -k "user" -v                   # by keyword
pytest tests/test_file.py::test_func -v      # single test
pytest tests/ --cov=app --cov-report=html    # with coverage
pytest tests/ -n auto                         # parallel
```

### Data Population
```bash
python populate_data/load_comprehensive_data.py        # full dataset
python populate_data/load_comprehensive_data.py --quick  # reduced data
python populate_data/clear_all_data.py                 # clear data
```

## Coding Style & Conventions

### General
- Python 3.10+, FastAPI, SQLAlchemy 2.x, Pydantic v2
- PEP 8 with 4-space indentation, full type hints everywhere
- **snake_case** for modules/functions/variables; **PascalCase** for classes

### Imports (sorted alphabetically)
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_db
from app.schemas import UserSchema
from app.services import UserService
```

### Error Handling
- Use custom exceptions from `app/core/exceptions.py` (e.g., `UserNotFoundException`)
- Global exception handlers in `app/main.py` return structured errors with codes
- Never expose sensitive data in error responses

### Async Patterns
- All database operations use `async/await`
- Services inject `AsyncSession` via FastAPI dependencies
- Transaction context: `async with db.begin()` for atomic operations

### API Structure
- Endpoints in `app/api/api_v1/endpoints/*.py`
- Wire via router in `app/api/api_v1/api.py`
- Keep business logic in `app/services/`

### Response Models
- Pydantic schemas in `app/schemas/` with `Config.from_attributes = True`
- Use `Optional[]` for nullable fields, avoid `Union[]`
- Request models validate with `@field_validator`

### Database
- Async SQLAlchemy models in `app/models/`
- PostGIS for geospatial queries, full-text search with `__ts_vector__`
- Use repositories in `app/repositories/` for complex queries

### Security
- Supabase JWT authentication via `get_current_user` dependency (clients authenticate directly with Supabase)
- Phone as primary identifier, role-based access (user/agent/admin)
- Backend no longer exposes `/api/v1/auth/*` user-session endpoints; backend only verifies bearer access tokens and authorizes business routes
- Rate limiting: 100 req/min global

## Project Structure
```
app/
  api/api_v1/endpoints/  # REST endpoints
  services/              # async business logic
  models/                # SQLAlchemy models
  schemas/               # Pydantic schemas
  core/                  # config, auth, db, exceptions
  middleware/            # rate limit, security headers
```

## Agent-Specific Instructions
- Keep changes minimal and localized to the module being modified
- Follow existing patterns in the relevant Cursor rules (`.cursor/rules/`)
- Do not introduce new dependencies without rationale
- Never commit secrets; use `.env` and `app.core.config.settings`
