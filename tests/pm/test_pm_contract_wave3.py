"""PM contract wave 2, pass B: reference ownership, application status, removed fields, delivery helper."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_user,
    get_current_user_optional,
)
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.agents import Agent
from app.models.enums import (
    AgentType,
    DocumentType,
    ExperienceLevel,
    InspectionType,
    LeaseStatus,
    PropertyPurpose,
    PropertyType,
    UserRole,
)
from app.models.pm_documents import Document
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User
from app.schemas.pm_document import Document as DocumentSchema
from app.schemas.pm_maintenance import MaintenanceRequest as MaintenanceRequestSchema
from app.schemas.user import User as UserSchema
from app.services.cloudinary import CloudinaryService
from app.services.pm_documents import create_document, viewer_file_url
from app.services.pm_inspections import create_inspection_checklist, sign_inspection

pytestmark = pytest.mark.asyncio

RAW_URL = "https://res.cloudinary.com/demo/raw/authenticated/x.pdf"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _user(db, *, role: str = UserRole.user.value, name: str = "PM User") -> User:
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        phone=f"+91{uuid.uuid4().int % 10**10:010d}",
        full_name=name,
        role=role,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _property(db, owner: User) -> Property:
    prop = Property(
        title="PM Flat",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
        owner_id=owner.id,
        is_managed=True,
    )
    db.add(prop)
    await db.flush()
    return prop


async def _lease(db, owner: User, prop: Property, tenant: User | None) -> Lease:
    lease = Lease(
        property_id=prop.id,
        owner_id=owner.id,
        tenant_user_id=tenant.id if tenant else None,
        status=LeaseStatus.active,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        monthly_rent=Decimal("20000.00"),
        security_deposit=Decimal("40000.00"),
        grace_period_days=5,
        payment_due_day=5,
    )
    db.add(lease)
    await db.flush()
    await db.refresh(lease)
    return lease


async def _document(db, owner: User) -> Document:
    doc = Document(
        owner_id=owner.id,
        document_type=DocumentType.id_proof,
        title="ID",
        file_url=RAW_URL,
        file_path="documents/general/id.pdf",
        mime_type="application/pdf",
        shared_with_agent=False,
        shared_with_tenant=False,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def _client(test_app, user: User) -> AsyncClient:
    schema = UserSchema.model_validate(user, from_attributes=True)

    async def _current() -> UserSchema:
        return schema

    test_app.dependency_overrides[get_current_user] = _current
    test_app.dependency_overrides[get_current_active_user] = _current
    test_app.dependency_overrides[get_current_user_optional] = _current
    transport = ASGITransport(app=test_app)
    return AsyncClient(transport=transport, base_url="http://test", timeout=60.0)


@pytest_asyncio.fixture
async def api_owner(db_session) -> User:
    return await _user(db_session, name="API Owner")


# ---------------------------------------------------------------------------
# be-pm-18: referenced ids must exist (404) and belong to the caller's side (403)
# ---------------------------------------------------------------------------


async def test_document_links_must_belong_to_the_owner(db_session):
    owner = await _user(db_session, name="Owner")
    other = await _user(db_session, name="Other owner")
    own_prop = await _property(db_session, owner)
    foreign_prop = await _property(db_session, other)
    foreign_lease = await _lease(db_session, other, foreign_prop, None)
    values = {
        "actor": owner,
        "owner_id": owner.id,
        "document_type": DocumentType.other,
        "title": "Deed",
        "file_url": RAW_URL,
    }

    doc = await create_document(db_session, property_id=own_prop.id, **values)
    assert doc.property_id == own_prop.id

    with pytest.raises(ForbiddenException):
        await create_document(db_session, property_id=foreign_prop.id, **values)
    with pytest.raises(NotFoundException):
        await create_document(db_session, property_id=999_999_999, **values)
    with pytest.raises(ForbiddenException):
        await create_document(db_session, lease_id=foreign_lease.id, **values)
    with pytest.raises(NotFoundException):
        await create_document(db_session, user_id=999_999_999, **values)


async def test_tenant_document_may_link_only_a_lease_it_is_party_to(db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    stranger = await _user(db_session, name="Stranger")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    values = {"document_type": DocumentType.id_proof, "title": "ID", "file_url": RAW_URL}

    doc = await create_document(
        db_session, actor=tenant, owner_id=tenant.id, lease_id=lease.id, **values
    )
    assert doc.lease_id == lease.id

    with pytest.raises(ForbiddenException):
        await create_document(
            db_session, actor=stranger, owner_id=stranger.id, lease_id=lease.id, **values
        )


async def test_maintenance_lease_must_belong_to_the_owner(test_app, db_session, api_owner):
    other = await _user(db_session, name="Other owner")
    prop = await _property(db_session, api_owner)
    foreign_prop = await _property(db_session, other)
    foreign_lease = await _lease(db_session, other, foreign_prop, None)
    body = {"property_id": prop.id, "category": "plumbing", "urgency": "low", "title": "Leak"}

    async with await _client(test_app, api_owner) as client:
        foreign = await client.post(
            "/api/v1/pm/maintenance/requests", json={**body, "lease_id": foreign_lease.id}
        )
        assert foreign.status_code == 403, foreign.text
        missing = await client.post(
            "/api/v1/pm/maintenance/requests", json={**body, "lease_id": 999_999_999}
        )
        assert missing.status_code == 404, missing.text


async def test_maintenance_agent_must_be_the_owners_agent(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    own_agent = Agent(
        name="Own agent",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.intermediate,
    )
    other_agent = Agent(
        name="Other agent",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.intermediate,
    )
    db_session.add_all([own_agent, other_agent])
    await db_session.flush()
    api_owner.agent_id = own_agent.id
    await db_session.flush()
    await db_session.refresh(api_owner)
    body = {"property_id": prop.id, "category": "plumbing", "urgency": "low", "title": "Leak"}

    async with await _client(test_app, api_owner) as client:
        created = await client.post(
            "/api/v1/pm/maintenance/requests",
            json={**body, "assigned_agent_id": own_agent.id},
        )
        assert created.status_code == 201, created.text
        req_id = created.json()["id"]

        foreign = await client.post(
            "/api/v1/pm/maintenance/requests",
            json={**body, "assigned_agent_id": other_agent.id},
        )
        assert foreign.status_code == 403, foreign.text
        missing = await client.post(
            "/api/v1/pm/maintenance/requests",
            json={**body, "assigned_agent_id": 999_999_999},
        )
        assert missing.status_code == 404, missing.text

        patch_foreign = await client.patch(
            f"/api/v1/pm/maintenance/requests/{req_id}",
            json={"assigned_agent_id": other_agent.id},
        )
        assert patch_foreign.status_code == 403, patch_foreign.text

        cleared = await client.patch(
            f"/api/v1/pm/maintenance/requests/{req_id}", json={"assigned_agent_id": None}
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["assigned_agent_id"] is None


async def test_inspection_signature_document_must_belong_to_the_signer(db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    checklist = await create_inspection_checklist(
        db_session,
        actor=owner,
        owner_id=owner.id,
        lease_id=lease.id,
        inspection_type=InspectionType.move_in,
    )
    owner_doc = await _document(db_session, owner)
    tenant_doc = await _document(db_session, tenant)

    with pytest.raises(ForbiddenException):
        await sign_inspection(
            db_session,
            actor=tenant,
            inspection_id=checklist.id,
            tenant_signature_document_id=owner_doc.id,
        )

    signed = await sign_inspection(
        db_session,
        actor=tenant,
        inspection_id=checklist.id,
        tenant_signature_document_id=tenant_doc.id,
    )
    assert signed.tenant_signature_document_id == tenant_doc.id

    with pytest.raises(ForbiddenException):
        await sign_inspection(
            db_session,
            actor=owner,
            inspection_id=checklist.id,
            owner_signature_document_id=tenant_doc.id,
        )


# ---------------------------------------------------------------------------
# be-pm-32: application status has its own enum; decision is approved or rejected
# ---------------------------------------------------------------------------


async def test_application_status_values_and_filter(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    async with await _client(test_app, api_owner) as client:
        form = await client.post(
            "/api/v1/pm/applications/forms", json={"title": "F", "property_id": prop.id}
        )
        slug = form.json()["slug"]

    anonymous = await _client(test_app, await _user(db_session, name="Anon"))
    async with anonymous as public:
        sub = await public.post(
            f"/api/v1/pm/public/applications/{slug}/submit",
            json={"applicant_full_name": "Applicant"},
        )
        assert sub.status_code == 201, sub.text
        assert sub.json()["status"] == "applicant"
        app_id = sub.json()["id"]

    async with await _client(test_app, api_owner) as client:
        tenancy_value = await client.get("/api/v1/pm/applications", params={"status": "active"})
        assert tenancy_value.status_code == 422, tenancy_value.text

        listed = await client.get("/api/v1/pm/applications", params={"status": "applicant"})
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == app_id for item in listed.json()["items"])

        not_a_decision = await client.post(
            f"/api/v1/pm/applications/{app_id}/decision", json={"decision": "active"}
        )
        assert not_a_decision.status_code == 422, not_a_decision.text

        done = await client.post(
            f"/api/v1/pm/applications/{app_id}/decision", json={"decision": "approved"}
        )
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "approved"


# ---------------------------------------------------------------------------
# be-pm-16, be-pm-38, be-pm-40: removed fields stay removed
# ---------------------------------------------------------------------------


async def test_expense_rejects_removed_recurrence_fields(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    body = {
        "property_id": prop.id,
        "category": "maintenance",
        "amount": 100,
        "expense_date": "2026-10-01",
    }
    async with await _client(test_app, api_owner) as client:
        bad = await client.post("/api/v1/pm/expenses", json={**body, "is_recurring": True})
        assert bad.status_code == 422, bad.text

        ok = await client.post("/api/v1/pm/expenses", json=body)
        assert ok.status_code == 201, ok.text
        for key in ("is_recurring", "recurrence_rule", "next_due_date"):
            assert key not in ok.json()


def test_removed_fields_are_absent_from_models_and_responses():
    assert "version" not in DocumentSchema.model_fields
    assert "replaces_document_id" not in DocumentSchema.model_fields
    assert not hasattr(Document, "version")
    assert not hasattr(Document, "replaces_document_id")
    assert "priority" not in MaintenanceRequestSchema.model_fields
    assert not hasattr(MaintenanceRequest, "priority")


# ---------------------------------------------------------------------------
# Private delivery goes through the shared notify helper
# ---------------------------------------------------------------------------


async def test_file_url_is_signed_by_the_shared_delivery_helper(db_session, monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_delivery(self, public_id: str, *, resource_type: str = "raw") -> str:
        calls.append((public_id, resource_type))
        return "https://signed.example/doc"

    monkeypatch.setattr(CloudinaryService, "private_delivery_url", fake_delivery)
    owner = await _user(db_session, name="Owner")
    doc = await _document(db_session, owner)

    assert await viewer_file_url(db_session, doc=doc, actor=owner) == "https://signed.example/doc"
    assert calls == [("documents/general/id.pdf", "raw")]
