"""Fixtures that run a real HTTP request through the real ``get_db`` dependency.

The shared ``client`` fixture overrides ``get_db`` with one rollback-only session, which
hides commit bugs. These fixtures keep ``get_db`` and read the rows back in a NEW session.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import database
from app.core.database import Base
from app.factory import create_app
from tests.conftest import TEST_DATABASE_URL


async def _truncate_all(engine) -> None:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def real_engine(test_engine, monkeypatch):
    engine = create_async_engine(
        TEST_DATABASE_URL, poolclass=NullPool, connect_args={"prepare_threshold": None}
    )
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    # get_db opens ``AsyncSessionLocal()`` at call time: point it at this loop's engine.
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    await _truncate_all(engine)
    yield engine
    await _truncate_all(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def new_session(real_engine):
    """A session separate from the request session. Rows it sees are committed rows."""
    factory = async_sessionmaker(real_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def real_app(real_engine):
    app = create_app(testing=True)
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def real_client(real_app):
    async with AsyncClient(
        transport=ASGITransport(app=real_app), base_url="http://test", timeout=60.0
    ) as ac:
        yield ac


def act_as(app, user) -> None:
    """Make ``user`` the caller. Only auth is overridden; ``get_db`` stays real."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_cached_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import SelfUser

    schema = SelfUser.model_validate(user, from_attributes=True)

    async def _me():
        return schema

    for dep in (
        get_current_user,
        get_current_active_user,
        get_current_cached_active_user,
        get_current_user_optional,
    ):
        app.dependency_overrides[dep] = _me
