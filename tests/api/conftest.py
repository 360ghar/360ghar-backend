"""
API endpoint test specific fixtures.

Provides authenticated client variants and common request helpers.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# =============================================================================
# Authenticated Client Variants
# =============================================================================

@pytest_asyncio.fixture
async def guest_client(test_app):
    """Unauthenticated client — no auth headers, no dependency overrides."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def user_client(test_app, test_user):
    """Authenticated client with user role."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(test_user, from_attributes=True)

    async def override_get_current_user():
        return user_schema

    async def override_get_current_active_user():
        return user_schema

    async def override_get_current_user_optional():
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def agent_client(test_app, test_agent_user):
    """Authenticated client with agent role."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_agent,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(test_agent_user, from_attributes=True)

    async def override_get_current_user():
        return user_schema

    async def override_get_current_active_user():
        return user_schema

    async def override_get_current_user_optional():
        return user_schema

    async def override_get_current_agent():
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional
    test_app.dependency_overrides[get_current_agent] = override_get_current_agent

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_client(test_app, test_admin_user):
    """Authenticated client with admin role."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_admin,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(test_admin_user, from_attributes=True)

    async def override_get_current_user():
        return user_schema

    async def override_get_current_active_user():
        return user_schema

    async def override_get_current_user_optional():
        return user_schema

    async def override_get_current_admin():
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional
    test_app.dependency_overrides[get_current_admin] = override_get_current_admin

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac
