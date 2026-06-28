from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import LeaseStatus, PropertyPurpose, PropertyType, UserRole
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pm_owner(db_session) -> User:
    """A regular user who acts as a PM portfolio owner."""
    import uuid

    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="pm_owner@example.com",
        phone="+919000000001",
        full_name="PM Owner",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def pm_client(test_app, pm_owner) -> AsyncClient:
    """Authenticated client wired to pm_owner."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(pm_owner, from_attributes=True)

    async def override_get_current_user() -> UserSchema:
        return user_schema

    async def override_get_current_active_user() -> UserSchema:
        return user_schema

    async def override_get_current_user_optional() -> UserSchema:
        return user_schema

    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    test_app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_owner_with_leases(db_session, pm_owner) -> list[Lease]:
    """Create >=3 leases owned by pm_owner for pagination tests."""
    leases = []
    today = date.today()

    for i in range(3):
        prop = Property(
            title=f"Pagination Test Property {i}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=30000,
            owner_id=pm_owner.id,
            is_managed=True,
        )
        db_session.add(prop)
        await db_session.flush()

        lease = Lease(
            property_id=prop.id,
            owner_id=pm_owner.id,
            tenant_name=f"Tenant {i}",
            tenant_phone=f"+9100000000{i}",
            status=LeaseStatus.active,
            start_date=today - timedelta(days=30 + i),
            end_date=today + timedelta(days=335 - i),
            monthly_rent=20000.0 + i * 1000,
            security_deposit=40000.0,
            grace_period_days=5,
            payment_due_day=1,
        )
        db_session.add(lease)
        await db_session.flush()
        await db_session.refresh(lease)
        leases.append(lease)

    return leases


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_leases_cursor_paginates(pm_client: AsyncClient, seeded_owner_with_leases: list[Lease]) -> None:
    r1 = await pm_client.get("/api/v1/pm/leases?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/leases?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)  # no overlap across pages


async def test_leases_include_total(pm_client: AsyncClient, seeded_owner_with_leases: list[Lease]) -> None:
    r = await pm_client.get("/api/v1/pm/leases?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_leases_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/leases?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
