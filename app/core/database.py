from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Create async engine with transaction pooler compatibility
engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,  # postgresql+asyncpg://...
    echo=False,
    pool_size=20,  # Good for transaction pooler
    max_overflow=10,  # Reasonable overflow
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=1800,  # Recycle connections after 30 minutes
    connect_args={
        "server_settings": {
            "jit": "off"  # Disable JIT for consistent performance
        },
        "command_timeout": 60,  # Standard timeout
        # Disable prepared statements when behind PgBouncer (transaction/statement pooler)
        # asyncpg uses 'prepared_statement_cache_size' (SQLAlchemy wrapper) and 'statement_cache_size' (asyncpg)
        # Setting both ensures compatibility across versions
        "prepared_statement_cache_size": 0,
        "statement_cache_size": 0,
    }
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

class Base(DeclarativeBase):
    """Base class for all models"""
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            # Log unexpected session errors without leaking sensitive data
            logger.exception("DB session error; rolling back")
            await session.rollback()
            raise
        finally:
            await session.close()

@asynccontextmanager
async def get_db_context():
    """Context manager for database operations outside of request context"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            logger.exception("DB context error; rolling back")
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """Close database connections"""
    await engine.dispose()
