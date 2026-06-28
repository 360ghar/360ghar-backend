"""Cursor-pagination integration tests for pm/properties, pm/expenses,
pm/maintenance/requests, and pm/inspections.

Each endpoint gets:
  - a page-walk test (limit=2, ≥3 seeded rows, has_more True, no overlap)
  - an invalid-cursor-400 test asserting error.code == "INVALID_CURSOR"

At least one endpoint also asserts include_total.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import (
    ExpenseCategory,
    InspectionType,
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    PropertyPurpose,
    PropertyType,
    UserRole,
)
from app.models.pm_finance import Expense
from app.models.pm_inspections import InspectionChecklist
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
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
        email="pm_owner_batch_a1@example.com",
        phone="+919111111111",
        full_name="PM Owner Batch A1",
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
async def owner_property(db_session, pm_owner) -> Property:
    """A managed property owned by pm_owner."""
    prop = Property(
        title="Batch A1 Test Property Base",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
        owner_id=pm_owner.id,
        is_managed=True,
    )
    db_session.add(prop)
    await db_session.flush()
    await db_session.refresh(prop)
    return prop


@pytest_asyncio.fixture
async def owner_lease(db_session, pm_owner, owner_property) -> Lease:
    """An active lease for the owner property (needed for inspections)."""
    today = date.today()
    lease = Lease(
        property_id=owner_property.id,
        owner_id=pm_owner.id,
        tenant_name="Test Tenant",
        tenant_phone="+919222222222",
        status=LeaseStatus.active,
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=335),
        monthly_rent=20000.0,
        security_deposit=40000.0,
        grace_period_days=5,
        payment_due_day=1,
    )
    db_session.add(lease)
    await db_session.flush()
    await db_session.refresh(lease)
    return lease


# ---------------------------------------------------------------------------
# pm/properties pagination
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_properties(db_session, pm_owner) -> list[Property]:
    """3 managed properties owned by pm_owner."""
    props = []
    for i in range(3):
        prop = Property(
            title=f"Pagination Prop {i}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=25000 + i * 1000,
            owner_id=pm_owner.id,
            is_managed=True,
        )
        db_session.add(prop)
        await db_session.flush()
        await db_session.refresh(prop)
        props.append(prop)
    return props


async def test_properties_cursor_paginates(
    pm_client: AsyncClient, seeded_properties: list[Property]
) -> None:
    r1 = await pm_client.get("/api/v1/pm/properties?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/properties?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None


async def test_properties_include_total(
    pm_client: AsyncClient, seeded_properties: list[Property]
) -> None:
    r = await pm_client.get("/api/v1/pm/properties?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_properties_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/properties?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# pm/expenses pagination
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_expenses(db_session, pm_owner, owner_property) -> list[Expense]:
    """3 expenses owned by pm_owner for pagination tests."""
    expenses = []
    today = date.today()
    for i in range(3):
        exp = Expense(
            property_id=owner_property.id,
            owner_id=pm_owner.id,
            category=ExpenseCategory.maintenance,
            amount=1000.0 + i * 500,
            expense_date=today - timedelta(days=i),
            description=f"Expense {i}",
            is_recurring=False,
        )
        db_session.add(exp)
        await db_session.flush()
        await db_session.refresh(exp)
        expenses.append(exp)
    return expenses


async def test_expenses_cursor_paginates(
    pm_client: AsyncClient, seeded_expenses: list[Expense]
) -> None:
    r1 = await pm_client.get("/api/v1/pm/expenses?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/expenses?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None


async def test_expenses_include_total(
    pm_client: AsyncClient, seeded_expenses: list[Expense]
) -> None:
    r = await pm_client.get("/api/v1/pm/expenses?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_expenses_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/expenses?cursor=notvalid!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# pm/maintenance/requests pagination
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_maintenance(
    db_session, pm_owner, owner_property
) -> list[MaintenanceRequest]:
    """3 maintenance requests owned by pm_owner."""
    reqs = []
    for i in range(3):
        req = MaintenanceRequest(
            property_id=owner_property.id,
            owner_id=pm_owner.id,
            category=MaintenanceCategory.plumbing,
            urgency=MaintenanceUrgency.medium,
            title=f"Maintenance Issue {i}",
            description=f"Description {i}",
            request_status=MaintenanceRequestStatus.open,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)
        reqs.append(req)
    return reqs


async def test_maintenance_cursor_paginates(
    pm_client: AsyncClient, seeded_maintenance: list[MaintenanceRequest]
) -> None:
    r1 = await pm_client.get("/api/v1/pm/maintenance/requests?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(
        f"/api/v1/pm/maintenance/requests?limit=2&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None


async def test_maintenance_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/maintenance/requests?cursor=bad!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# pm/inspections pagination
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_inspections(
    db_session, pm_owner, owner_property, owner_lease
) -> list[InspectionChecklist]:
    """3 inspection checklists owned by pm_owner."""
    inspections = []
    now = datetime.now(timezone.utc)
    for i in range(3):
        checklist = InspectionChecklist(
            property_id=owner_property.id,
            lease_id=owner_lease.id,
            owner_id=pm_owner.id,
            inspection_type=InspectionType.routine,
            conducted_by_user_id=pm_owner.id,
            conducted_at=now - timedelta(days=i),
        )
        db_session.add(checklist)
        await db_session.flush()
        await db_session.refresh(checklist)
        inspections.append(checklist)
    return inspections


async def test_inspections_cursor_paginates(
    pm_client: AsyncClient, seeded_inspections: list[InspectionChecklist]
) -> None:
    r1 = await pm_client.get("/api/v1/pm/inspections?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/inspections?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
    assert body2["has_more"] is False
    assert body2["next_cursor"] is None


async def test_inspections_include_total(
    pm_client: AsyncClient, seeded_inspections: list[InspectionChecklist]
) -> None:
    r = await pm_client.get("/api/v1/pm/inspections?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_inspections_invalid_cursor_400(pm_client: AsyncClient) -> None:
    r = await pm_client.get("/api/v1/pm/inspections?cursor=junk!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
