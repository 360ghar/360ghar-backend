# Dependencies

The 360Ghar backend has a Python dependency tree (the API) and a small JavaScript dependency tree (the ChatGPT widgets). Python deps are managed by `uv` and declared in `pyproject.toml`; JS deps are managed by npm and declared in `chatgpt-widgets/package.json`.

Active contributors: Saksham, Ravi

## Python runtime dependencies

Declared in `pyproject.toml` under `[project].dependencies`. Requires Python `>=3.10`.

### Web framework

- `fastapi[standard]>=0.136.1` - async web framework
- `uvicorn[standard]>=0.46.0` - ASGI server
- `python-multipart>=0.0.27` - form parsing
- `python-dotenv>=1.2.2` - `.env` loading
- `websockets>=15.0,<16` - WebSocket support for AI job and notification streams

### Data layer

- `sqlalchemy[asyncio]>=2.0.49` - ORM with async support
- `geoalchemy2>=0.19.0` - PostGIS integration for geospatial queries
- `pgvector>=0.4.2` - vector embedding storage and similarity search
- `psycopg[binary]>=3.3.4` - Postgres driver
- `redis>=5.0,<8` - Redis client for cache and rate limiting

### Validation and settings

- `pydantic>=2.13.3` - schema validation
- `pydantic-settings>=2.14.0` - environment-driven settings
- `email-validator>=2.3.0` - email field validation

### HTTP and integrations

- `httpx>=0.28.1` - async HTTP client (shared singletons in `app/core/http.py`)
- `supabase>=2.29.0` - Supabase Auth and REST client
- `cloudinary>=1.44.2` - media storage
- `razorpay>=1.4.2` - payments
- `google-auth>=2.50.0` - Google auth (FCM service account)

### AI and ML

- `google-genai>=1.64.0` - Gemini API client
- `pydantic-ai-slim[openai,fastmcp,retries]>=1.0.0` - Pydantic AI agent framework
- `fastmcp>=3.2.4` - MCP server framework
- `tenacity>=9.1.4` - retry logic for AI providers and network calls

### Scraping and parsing

- `beautifulsoup4>=4.14.3` - HTML parsing for data hub scrapers
- `pdfplumber>=0.11.9` - PDF parsing for gazette and jamabandi documents

### Media and utilities

- `Pillow>=12.2.0` - image processing (thumbnails, EXIF)
- `qrcode[pil]>=8.2` - QR code generation
- `bleach>=6.3.0` - HTML sanitization for blog content
- `PyYAML>=6.0.3` - YAML parsing
- `dnspython>=2.8.0` - DNS resolution
- `PyJWT[crypto]>=2.9.0` - JWT verification against Supabase JWKS

### Observability

- `sentry-sdk[fastapi]>=2.58.0` - error tracking and performance monitoring

### Scheduling

- `APScheduler>=3.10.4,<4` - background job scheduler (single shared `AsyncIOScheduler`)

## Python dev dependencies

Declared under `[project.optional-dependencies].dev`. Install with `uv sync --extra dev`.

- `pytest>=9.0.3`, `pytest-asyncio`, `pytest-cov`, `pytest-xdist`, `pytest-timeout` - test runner and plugins
- `respx>=0.23.1` - httpx mocking
- `freezegun>=1.5.5` - time mocking
- `ruff>=0.15.12` - linter and formatter
- `mypy>=1.20.2` - type checker
- `playwright>=1.59.0` - browser automation for e2e tests
- `fastapi-debug-toolbar>=0.6.3` - debug toolbar
- `watchfiles` - hot reload for dev server
- `aiosqlite` - SQLite async driver for tests (with GeoAlchemy2 compile shims)
- `fastapi-cli>=0.0.24` - `fastapi dev` command
- `hypercorn>=0.18.0` - alternative ASGI server

## JavaScript dependencies

Declared in `chatgpt-widgets/package.json`. The widget subsystem is a standalone npm project that builds 11 React widgets into standalone HTML bundles.

### Runtime

- `react@^18.2.0`
- `react-dom@^18.2.0`

### Dev

- `@types/react@^18.2.0`, `@types/react-dom@^18.2.0` - TypeScript types
- `esbuild@^0.20.0` - bundler (custom build script in `chatgpt-widgets/scripts/build-widgets.js`)
- `typescript@^5.3.0` - type checker

The widget bridge (`chatgpt-widgets/src/utils/bridge.ts`) is framework-agnostic React hooks that work on OpenAI and MCP Apps hosts. See [features/mcp-servers.md](../features/mcp-servers.md).

## Version policy

Per `CLAUDE.md` and `AGENTS.md`, the project always uses the latest stable versions of dependencies. `pyproject.toml` uses `>=` lower bounds (not pinned) and `uv.lock` records the resolved versions. When upgrading, review changelogs for breaking changes and verify compatibility with Python 3.10+, FastAPI, SQLAlchemy 2.x async, and Pydantic v2.
