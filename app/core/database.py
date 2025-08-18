from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Base class for all models
class Base(DeclarativeBase):
    pass

# Log database connection info
logger.info(f"Connecting to database with psycopg for PgBouncer compatibility")

# Create async engine using psycopg for better PgBouncer compatibility
engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=settings.DEBUG,
    future=True,
    # Connection settings for PgBouncer compatibility
    connect_args={
        "application_name": "360ghar_backend",  # For monitoring
        "prepare_threshold": None,  # Disable prepared statements for PgBouncer
    }
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

# Dependency for FastAPI
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()