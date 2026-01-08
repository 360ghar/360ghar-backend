from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
from app.core.logging import get_logger
from fastapi import HTTPException

logger = get_logger(__name__)

# Base class for all models
class Base(DeclarativeBase):
    pass

# Log database connection info
logger.info(f"Connecting to database with psycopg for PgBouncer compatibility")

# Create async engine using psycopg for better PgBouncer compatibility
# Use NullPool because PgBouncer performs pooling; avoids SQLAlchemy pre-ping
# which can toggle autocommit and conflict with active transactions.
engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    poolclass=NullPool,
    # Connection settings for PgBouncer compatibility
    connect_args={
        "application_name": "360ghar_backend",  # For monitoring
        "prepare_threshold": None,  # Disable prepared statements for PgBouncer
    },
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Dependency for FastAPI
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except HTTPException:
            # Propagate HTTP errors without logging as DB errors
            await session.rollback()
            raise
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        else:
            # Commit only if no exception occurred during the request
            await session.commit()


def get_async_session_factory():
    """
    Get the async session factory for use in background tasks.

    This allows background tasks to create their own database sessions
    independent of the FastAPI request lifecycle.

    Returns:
        async_sessionmaker: The session factory
    """
    return AsyncSessionLocal
