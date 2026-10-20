"""
Authentication fixtures for testing.

Provides fixtures for creating test users with different roles
and generating mock JWT tokens for authenticated requests.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
import pytest_asyncio

from app.models.enums import AuthMethod, UserRole
from app.models.users import User

# =============================================================================
# JWT Token Creation
# =============================================================================

# Mock secret used for test JWT tokens
TEST_JWT_SECRET = "mock_jwt_secret_for_testing_purposes_only_32chars"


def create_test_jwt(
    user_id: str,
    phone: str = "+919876543210",
    email: str = "test@example.com",
    role: str = "authenticated",
    exp_hours: int = 24,
) -> str:
    """
    Create a mock JWT token for testing.

    Args:
        user_id: Supabase user ID (UUID string)
        phone: User's phone number
        email: User's email address
        role: Token role (usually 'authenticated')
        exp_hours: Hours until token expires

    Returns:
        Encoded JWT token string
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "phone": phone,
        "email": email,
        "email_verified": True,
        "phone_verified": True,
        "user_metadata": {"full_name": "Test User"},
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=exp_hours)).timestamp()),
        "aud": "authenticated",
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def decode_test_jwt(token: str) -> dict | None:
    """
    Decode a test JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload or None if invalid
    """
    try:
        return jwt.decode(
            token,
            TEST_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except Exception:
        return None


# =============================================================================
# User Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_user(db_session) -> User:
    """
    Create a standard test user.

    Returns:
        User object with role='user'
    """
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="testuser@example.com",
        phone="+919876543210",
        full_name="Test User",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
        email_verified=True,
        phone_verified=True,
        last_auth_method=AuthMethod.email_password.value,
        preferences={},
        notification_settings={},
        privacy_settings={},
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user_2(db_session) -> User:
    """
    Create a second standard test user for multi-user scenarios.

    Returns:
        User object with role='user'
    """
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="testuser2@example.com",
        phone="+919876543211",
        full_name="Test User 2",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
        email_verified=True,
        phone_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_agent_user(db_session) -> User:
    """
    Create a test user with agent role.

    Returns:
        User object with role='agent'
    """
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="agent@example.com",
        phone="+919876543212",
        full_name="Test Agent",
        role=UserRole.agent.value,
        is_active=True,
        is_verified=True,
        email_verified=True,
        phone_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_admin_user(db_session) -> User:
    """
    Create a test user with admin role.

    Returns:
        User object with role='admin'
    """
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="admin@example.com",
        phone="+919876543213",
        full_name="Test Admin",
        role=UserRole.admin.value,
        is_active=True,
        is_verified=True,
        email_verified=True,
        phone_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


# =============================================================================
# Auth Header Fixtures
# =============================================================================

@pytest.fixture
def user_auth_headers(test_user) -> dict[str, str]:
    """
    Generate authorization headers for test_user.

    Returns:
        Dict with Authorization header containing Bearer token
    """
    token = create_test_jwt(
        user_id=test_user.supabase_user_id,
        phone=test_user.phone,
        email=test_user.email,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(user_auth_headers) -> dict[str, str]:
    """Alias for user_auth_headers."""
    return user_auth_headers


@pytest.fixture
def agent_auth_headers(test_agent_user) -> dict[str, str]:
    """
    Generate authorization headers for test_agent_user.

    Returns:
        Dict with Authorization header containing Bearer token
    """
    token = create_test_jwt(
        user_id=test_agent_user.supabase_user_id,
        phone=test_agent_user.phone,
        email=test_agent_user.email,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers(test_admin_user) -> dict[str, str]:
    """
    Generate authorization headers for test_admin_user.

    Returns:
        Dict with Authorization header containing Bearer token
    """
    token = create_test_jwt(
        user_id=test_admin_user.supabase_user_id,
        phone=test_admin_user.phone,
        email=test_admin_user.email,
    )
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# Auth Mocking Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase_verify():
    """
    Mock Supabase token verification to accept test JWTs.

    Use this fixture in tests that make authenticated API calls
    to bypass actual Supabase token verification.
    """
    with patch("app.core.auth.verify_supabase_token") as mock:

        async def verify_token(token: str):
            """Verify test JWT and return payload."""
            return decode_test_jwt(token)

        mock.side_effect = verify_token
        yield mock


@pytest.fixture
def mock_get_or_create_user():
    """
    Mock the get_or_create_user_from_supabase function.

    Returns a mock that can be configured to return specific users.
    """
    with patch(
        "app.api.api_v1.dependencies.auth.get_or_create_user_from_supabase"
    ) as mock:
        mock.return_value = AsyncMock()
        yield mock


@pytest.fixture
def mock_supabase_auth_client():
    """
    Mock the Supabase auth client for registration/login tests.

    Returns a mock client with auth methods that can be configured.
    """
    with patch("app.core.auth.get_supabase_auth_client") as mock:
        mock_client = MagicMock()
        mock_client.auth = MagicMock()

        # Mock sign_up method
        mock_client.auth.sign_up = MagicMock(
            return_value=MagicMock(
                user=MagicMock(id=str(uuid.uuid4())),
                session=MagicMock(access_token="mock_access_token"),
            )
        )

        # Mock sign_in_with_password method
        mock_client.auth.sign_in_with_password = MagicMock(
            return_value=MagicMock(
                user=MagicMock(id=str(uuid.uuid4())),
                session=MagicMock(access_token="mock_access_token"),
            )
        )

        # Mock sign_in_with_otp method
        mock_client.auth.sign_in_with_otp = MagicMock(return_value=None)

        # Mock verify_otp method
        mock_client.auth.verify_otp = MagicMock(
            return_value=MagicMock(
                user=MagicMock(id=str(uuid.uuid4())),
                session=MagicMock(access_token="mock_access_token"),
            )
        )

        mock.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_supabase_service_client():
    """
    Mock the Supabase service client for admin operations.

    Returns a mock client with table operations.
    """
    with patch("app.core.auth.get_supabase_service_client") as mock:
        mock_client = MagicMock()

        # Mock table operations
        mock_table = MagicMock()
        mock_table.select.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.delete.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        mock_client.table.return_value = mock_table
        mock.return_value = mock_client

        yield mock_client


@pytest.fixture
def mock_supabase_client(mock_supabase_service_client):
    """Alias for mock_supabase_service_client for convenience."""
    return mock_supabase_service_client


# =============================================================================
# Authenticated Client Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def authenticated_client(test_app, test_user):
    """
    Create an authenticated async HTTP client with user auth.

    Overrides auth dependencies to return the test_user.
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_cached_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import SelfUser as UserSchema

    # Create schema from test user
    user_schema = UserSchema.model_validate(test_user, from_attributes=True)

    async def override_get_current_user():
        return user_schema

    async def override_get_current_active_user():
        return user_schema

    async def override_get_current_user_optional():
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_cached_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_authenticated_client(test_app, test_admin_user):
    """
    Create an authenticated async HTTP client with admin auth.

    Overrides auth dependencies to return the test_admin_user.
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_admin,
        get_current_cached_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import SelfUser as UserSchema

    # Create schema from test admin user
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
    test_app.dependency_overrides[get_current_cached_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional
    test_app.dependency_overrides[get_current_admin] = override_get_current_admin

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def agent_authenticated_client(test_app, test_agent_user):
    """
    Create an authenticated async HTTP client with agent auth.

    Overrides auth dependencies to return the test_agent_user.
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_agent,
        get_current_cached_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import SelfUser as UserSchema

    # Create schema from test agent user
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
    test_app.dependency_overrides[get_current_cached_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional
    test_app.dependency_overrides[get_current_agent] = override_get_current_agent

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=60.0,
    ) as ac:
        yield ac
