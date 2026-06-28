"""Cursor-pagination integration tests for pm/applications/forms,
pm/applications, and pm/tenants.

Each endpoint gets:
  - a page-walk test (limit=2, 3 seeded rows, has_more True, no overlap)
  - an invalid-cursor-400 test asserting error.code == "INVALID_CURSOR"

For offset-fallback endpoints (list_applications, list_tenants):
  - at least one include_total assertion.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import (
    LeaseStatus,
    PropertyPurpose,
    PropertyType,
    TenantStatus,
    UserRole,
)
from app.models.pm_leases import Lease
from app.models.pm_tenants import RentalApplication, RentalApplicationForm
from app.models.properties import Property
from app.models.users import User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pm_owner(db_session) -> User:
    """A regular user who acts as a PM portfolio owner."""
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="pm_app_tenant_owner@example.com",
        phone="+919100000099",
        full_name="PM App Tenant Owner",
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
async def pm_property(db_session, pm_owner) -> Property:
    """A property owned by pm_owner."""
    prop = Property(
        title="Test Property for App/Tenant Tests",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=25000,
        owner_id=pm_owner.id,
        is_managed=True,
    )
    db_session.add(prop)
    await db_session.flush()
    await db_session.refresh(prop)
    return prop


# ---------------------------------------------------------------------------
# Fixtures for list_application_forms (keyset DESC on created_at,id)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_application_forms(db_session, pm_owner, pm_property) -> list[RentalApplicationForm]:
    """Create 3 application forms owned by pm_owner."""
    forms = []
    for i in range(3):
        form = RentalApplicationForm(
            owner_id=pm_owner.id,
            property_id=pm_property.id,
            title=f"Form {i}",
            slug=f"form-slug-{uuid.uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(form)
        await db_session.flush()
        await db_session.refresh(form)
        forms.append(form)
    return forms


# ---------------------------------------------------------------------------
# Fixtures for list_applications (offset-fallback)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_applications(db_session, pm_owner, pm_property, seeded_application_forms) -> list[RentalApplication]:
    """Create 3 rental applications linked to the first form."""
    form = seeded_application_forms[0]
    applications = []
    for i in range(3):
        app = RentalApplication(
            form_id=form.id,
            property_id=pm_property.id,
            owner_id=pm_owner.id,
            status=TenantStatus.applicant,
            applicant_full_name=f"Applicant {i}",
            applicant_phone=f"+9100000{i:04d}",
            submitted_at=datetime(2025, 1, i + 1, tzinfo=timezone.utc),
        )
        db_session.add(app)
        await db_session.flush()
        await db_session.refresh(app)
        applications.append(app)
    return applications


# ---------------------------------------------------------------------------
# Fixtures for list_tenants (offset-fallback with group_by)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_tenants(db_session, pm_owner, pm_property) -> list[User]:
    """Create 3 tenant users each with an active lease under pm_owner."""
    tenant_users = []
    today = date.today()

    for i in range(3):
        tenant = User(
            supabase_user_id=str(uuid.uuid4()),
            email=f"tenant_pag_{i}@example.com",
            phone=f"+9190000{i:04d}",
            full_name=f"Tenant User {i}",
            role=UserRole.user.value,
            is_active=True,
            is_verified=True,
        )
        db_session.add(tenant)
        await db_session.flush()

        lease = Lease(
            property_id=pm_property.id,
            owner_id=pm_owner.id,
            tenant_user_id=tenant.id,
            tenant_name=f"Tenant User {i}",
            tenant_phone=f"+9190000{i:04d}",
            status=LeaseStatus.active,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=335),
            monthly_rent=15000.0 + i * 500,
            security_deposit=30000.0,
            grace_period_days=5,
            payment_due_day=1,
        )
        db_session.add(lease)
        await db_session.flush()
        await db_session.refresh(tenant)
        tenant_users.append(tenant)

    return tenant_users


# ---------------------------------------------------------------------------
# Tests: list_application_forms  (GET /pm/applications/forms)
# ---------------------------------------------------------------------------


async def test_application_forms_cursor_paginates(
    pm_client: AsyncClient,
    seeded_application_forms: list[RentalApplicationForm],
) -> None:
    r1 = await pm_client.get("/api/v1/pm/applications/forms?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/applications/forms?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None

    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_application_forms_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/applications/forms?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Tests: list_applications  (GET /pm/applications)
# ---------------------------------------------------------------------------


async def test_applications_cursor_paginates(
    pm_client: AsyncClient,
    seeded_applications: list[RentalApplication],
) -> None:
    r1 = await pm_client.get("/api/v1/pm/applications?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/applications?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None

    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_applications_include_total(
    pm_client: AsyncClient,
    seeded_applications: list[RentalApplication],
) -> None:
    r = await pm_client.get("/api/v1/pm/applications?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert body["total"] == 3


async def test_applications_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/applications?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Tests: list_tenants  (GET /pm/tenants)
# ---------------------------------------------------------------------------


async def test_tenants_cursor_paginates(
    pm_client: AsyncClient,
    seeded_tenants: list[User],
) -> None:
    r1 = await pm_client.get("/api/v1/pm/tenants?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/tenants?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None

    ids1 = {item["user_id"] for item in body1["items"]}
    ids2 = {item["user_id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)


async def test_tenants_include_total(
    pm_client: AsyncClient,
    seeded_tenants: list[User],
) -> None:
    r = await pm_client.get("/api/v1/pm/tenants?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert body["total"] == 3


async def test_tenants_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/tenants?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
