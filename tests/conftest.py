"""
360Ghar Backend Test Suite - Main Configuration

This is the main conftest.py providing:
- PostgreSQL database fixtures with transaction rollback
- Authentication fixtures (user, agent, admin)
- Test client fixtures for API testing
- External service mocking setup
"""

import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Import all models to ensure they're registered with SQLAlchemy
import app.models  # noqa: F401
from app.core.database import Base
from app.core.utils import utc_now_iso
from app.factory import create_app

# =============================================================================
# Configuration
# =============================================================================

# Test database URL - defaults to local PostgreSQL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://test_user:test_password@localhost:5432/test_db",
)

# Check if we're running in CI environment
IS_CI = os.getenv("CI", "false").lower() == "true"


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine():
    """
    Create the test database engine (session-scoped for performance).

    Creates all tables at the start of the test session and drops them
    at the end. Uses NullPool for compatibility with pgbouncer and
    to avoid connection pooling issues in tests.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        connect_args={"prepare_threshold": None},
    )

    # Create all tables
    async with engine.begin() as conn:
        # Drop all tables first for a clean slate (use raw SQL to handle circular deps)
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        # Create required extensions
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup: drop schema to avoid circular dependency issues
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a test database session with automatic transaction rollback.

    Each test function gets its own session wrapped in a transaction
    that is rolled back at the end of the test, ensuring test isolation.

    Uses connection-level transaction with savepoint pattern for proper
    isolation between tests.
    """
    # Create a new connection for this test
    connection = await test_engine.connect()

    # Start a transaction that we'll rollback at the end
    transaction = await connection.begin()

    # Create a session bound to this connection
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
    )

    # Start a nested transaction (savepoint) for the actual test
    nested = await connection.begin_nested()

    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_savepoint(session_sync, transaction_inner):
        """Restart the savepoint when a transaction ends."""
        if transaction_inner.nested and not transaction_inner._parent.nested:
            # Expired savepoint, create a new one
            connection.sync_connection.begin_nested()

    try:
        yield session
    finally:
        # Close the session
        await session.close()

        # Rollback the transaction (this discards all changes)
        await transaction.rollback()

        # Close the connection
        await connection.close()


# NOTE: Removed legacy aliases `db` and `test_db` — use `db_session` directly.
# If you see NameError for `db` or `test_db`, replace with `db_session`.


# =============================================================================
# Application Fixtures
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def test_app(db_session: AsyncSession):
    """
    Create test application with overridden dependencies.

    Overrides the database dependency to use the test session,
    ensuring all database operations in tests use the same
    transaction that will be rolled back.

    Also adds root-level endpoints that are defined in app/main.py
    but not in the factory.
    """
    from app.config import settings
    from app.core.database import get_db

    app = create_app(testing=True)

    # Add root-level endpoints that are normally in main.py
    @app.get("/")
    async def root():
        return {
            "message": "360Ghar Real Estate Platform API",
            "version": "2.0.0",
            "docs": f"{settings.API_V1_STR}/docs",
            "status": "running",
        }

    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": utc_now_iso(),
            "version": "2.0.0",
        }

    # Override database dependency
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    yield app

    # Clear overrides
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for API testing.

    Uses httpx's ASGI transport to make requests directly to the
    application without needing a running server.
    """
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac


# =============================================================================
# Load Fixtures from Submodules
# =============================================================================

# Register fixture plugins from submodules
pytest_plugins = [
    "tests.fixtures.auth",
    "tests.fixtures.factories",
    "tests.fixtures.mocks",
    "tests.fixtures.data",
    "tests.fixtures.common",
]
