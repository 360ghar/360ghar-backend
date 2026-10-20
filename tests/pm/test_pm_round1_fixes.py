"""PM contract fix round 1: lease authority, billing authority, empty sign, tenant lists,
document upload and delivery, lease defaults, dashboard activity, tenant summary, rent claims,
managed property create. Each test names the ledger id it covers.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile
from sqlalchemy import select
from starlette.datastructures import Headers

from app.api.api_v1.dependencies.auth import get_current_cached_active_user
from app.models.agents import Agent
from app.models.enums import (
    AgentType,
    DocumentType,
    ExperienceLevel,
    InspectionType,
    LeaseStatus,
    RentChargeStatus,
    UserRole,
)
from app.models.pm_documents import Document
from app.models.pm_finance import RentCharge
from app.models.properties import Amenity, PropertyAmenity, PropertyImage
from app.schemas.user import User as UserSchema
from app.services import pm_documents
from app.services.cloudinary import CloudinaryService
from app.services.pm_inspections import create_inspection_checklist
from app.services.property import crud as property_crud
from tests.pm.test_pm_contract_wave3 import _client, _document, _lease, _property, _user

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n" + b"0" * 64
RAW_URL = "https://res.cloudinary.com/demo/raw/authenticated/v1/360ghar/documents/general/id.pdf"
IMAGE_URL = (
    "https://res.cloudinary.com/demo/image/authenticated/v1/360ghar/documents/general/id.pdf"
)


def _fake_cloud(monkeypatch, *, secure_url: str = RAW_URL, resource_type: str = "raw") -> MagicMock:
    """A real CloudinaryService with the SDK handles mocked. Captures upload and signing calls."""
    svc = CloudinaryService.__new__(CloudinaryService)
    svc.root = "360ghar"
    svc._uploader = MagicMock()
    svc._uploader.upload.return_value = {
        "public_id": "360ghar/documents/general/id.pdf",
        "secure_url": secure_url,
        "bytes": len(PDF),
        "resource_type": resource_type,
    }
    svc._api = MagicMock()
    svc._url = MagicMock(return_value=("https://signed.example/doc", {}))
    monkeypatch.setattr(pm_documents, "get_cloudinary_service", lambda: svc)
    return svc


async def _checklist(db, owner, lease, inspection_type=InspectionType.move_in):
    return await create_inspection_checklist(
        db,
        actor=owner,
        owner_id=owner.id,
        lease_id=lease.id,
        inspection_type=inspection_type,
    )


# ---------------------------------------------------------------------------
# be-pm-11, be-pm-18: only the owner side manages a lease (tenant gets 403)
# ---------------------------------------------------------------------------


async def test_tenant_cannot_terminate_a_lease_owner_can(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)

    async with await _client(test_app, tenant) as client:
        denied = await client.post(f"/api/v1/pm/leases/{lease.id}/terminate", json={})
        assert denied.status_code == 403, denied.text
    await db_session.refresh(lease)
    assert lease.status == LeaseStatus.active

    async with await _client(test_app, owner) as client:
        done = await client.post(
            f"/api/v1/pm/leases/{lease.id}/terminate", json={"reason": "Moved out"}
        )
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "terminated"


async def test_tenant_cannot_renew_a_lease_owner_can(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    body = {
        "start_date": "2028-01-01",
        "end_date": "2028-12-31",
        "make_active": True,
    }

    async with await _client(test_app, tenant) as client:
        denied = await client.post(f"/api/v1/pm/leases/{lease.id}/renew", json=body)
        assert denied.status_code == 403, denied.text
    await db_session.refresh(lease)
    assert lease.status == LeaseStatus.active

    async with await _client(test_app, owner) as client:
        done = await client.post(f"/api/v1/pm/leases/{lease.id}/renew", json=body)
        assert done.status_code == 201, done.text
        assert done.json()["status"] == "active"


async def test_tenant_cannot_upload_a_signed_lease_owner_can(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    doc = await _document(db_session, owner)
    body = {"lease_document_id": doc.id, "signed_by_owner": True}

    async with await _client(test_app, tenant) as client:
        denied = await client.post(f"/api/v1/pm/leases/{lease.id}/upload-signed", json=body)
        assert denied.status_code == 403, denied.text
    await db_session.refresh(lease)
    assert lease.signed_by_owner_at is None

    async with await _client(test_app, owner) as client:
        done = await client.post(f"/api/v1/pm/leases/{lease.id}/upload-signed", json=body)
        assert done.status_code == 200, done.text
        assert done.json()["signed_by_owner_at"] is not None
        assert done.json()["lease_document_id"] == doc.id


# ---------------------------------------------------------------------------
# Major: a tenant cannot generate rent charges for its own lease
# ---------------------------------------------------------------------------


async def test_tenant_cannot_generate_charges_for_its_lease(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    body = {"lease_id": lease.id, "start_month": "2026-10-01", "months": 2}

    async with await _client(test_app, tenant) as client:
        denied = await client.post("/api/v1/pm/rent/charges/generate", json=body)
        assert denied.status_code == 403, denied.text
    charges = (
        await db_session.execute(select(RentCharge).where(RentCharge.lease_id == lease.id))
    ).all()
    assert charges == []

    async with await _client(test_app, owner) as client:
        done = await client.post("/api/v1/pm/rent/charges/generate", json=body)
        assert done.status_code == 200, done.text
        assert done.json() == {"created": 2, "skipped": 0}


# ---------------------------------------------------------------------------
# r3-est-a-25, major 3: inspection create, empty sign and document sign
# ---------------------------------------------------------------------------


async def test_inspection_create_and_empty_sign_record_the_acting_party(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    stranger = await _user(db_session, name="Stranger")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)

    async with await _client(test_app, owner) as client:
        created = await client.post(
            "/api/v1/pm/inspections",
            json={"lease_id": lease.id, "inspection_type": "move_in"},
        )
        assert created.status_code == 201, created.text
        checklist_id = created.json()["id"]
        assert created.json()["signed_by_tenant_at"] is None

    async with await _client(test_app, stranger) as client:
        denied = await client.post(f"/api/v1/pm/inspections/{checklist_id}/sign")
        assert denied.status_code == 403, denied.text

    async with await _client(test_app, tenant) as client:
        tenant_sign = await client.post(f"/api/v1/pm/inspections/{checklist_id}/sign", json={})
        assert tenant_sign.status_code == 200, tenant_sign.text
        assert tenant_sign.json()["signed_by_tenant_at"] is not None
        assert tenant_sign.json()["signed_by_owner_at"] is None

    async with await _client(test_app, owner) as client:
        owner_sign = await client.post(f"/api/v1/pm/inspections/{checklist_id}/sign")
        assert owner_sign.status_code == 200, owner_sign.text
        assert owner_sign.json()["signed_by_owner_at"] is not None


async def test_inspection_document_sign_records_the_signer(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    checklist = await _checklist(db_session, owner, lease)
    tenant_doc = await _document(db_session, tenant)

    async with await _client(test_app, tenant) as client:
        signed = await client.post(
            f"/api/v1/pm/inspections/{checklist.id}/sign",
            json={"tenant_signature_document_id": tenant_doc.id},
        )
        assert signed.status_code == 200, signed.text
        body = signed.json()
        assert body["tenant_signature_document_id"] == tenant_doc.id
        assert body["signed_by_tenant_at"] is not None
        assert body["signed_by_owner_at"] is None


# ---------------------------------------------------------------------------
# be-pm-23 (list half): tenant lists use as_tenant and see only what they are party to
# ---------------------------------------------------------------------------


async def test_tenant_lists_its_own_leases_inspections_and_shared_documents(
    test_app, db_session, monkeypatch
):
    _fake_cloud(monkeypatch)
    monkeypatch.setattr(
        CloudinaryService,
        "private_delivery_url",
        lambda self, public_id, *, resource_type="raw": "https://signed.example/doc",
    )
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    other_tenant = await _user(db_session, name="Other tenant")
    lease = await _lease(db_session, owner, await _property(db_session, owner), tenant)
    other_lease = await _lease(db_session, owner, await _property(db_session, owner), other_tenant)
    checklist = await _checklist(db_session, owner, lease)
    await _checklist(db_session, owner, other_lease)

    def _doc(lease_id: int, shared: bool, title: str) -> Document:
        return Document(
            owner_id=owner.id,
            lease_id=lease_id,
            document_type=DocumentType.lease_agreement,
            title=title,
            file_url=RAW_URL,
            file_path=f"documents/general/{title}.pdf",
            mime_type="application/pdf",
            shared_with_tenant=shared,
            shared_with_agent=False,
        )

    shared = _doc(lease.id, True, "shared")
    db_session.add_all(
        [shared, _doc(lease.id, False, "private"), _doc(other_lease.id, True, "other")]
    )
    await db_session.flush()

    async with await _client(test_app, tenant) as client:
        docs = await client.get("/api/v1/pm/documents", params={"as_tenant": "true"})
        assert docs.status_code == 200, docs.text
        assert [item["id"] for item in docs.json()["items"]] == [shared.id]
        assert docs.json()["items"][0]["file_url"] == "https://signed.example/doc"

        own_portfolio = await client.get("/api/v1/pm/documents")
        assert own_portfolio.status_code == 200, own_portfolio.text
        assert own_portfolio.json()["items"] == []

        leases = await client.get("/api/v1/pm/leases", params={"as_tenant": "true"})
        assert leases.status_code == 200, leases.text
        assert [item["id"] for item in leases.json()["items"]] == [lease.id]

        checklists = await client.get("/api/v1/pm/inspections", params={"as_tenant": "true"})
        assert checklists.status_code == 200, checklists.text
        assert [item["id"] for item in checklists.json()["items"]] == [checklist.id]


async def test_as_tenant_is_refused_for_agents(test_app, db_session):
    agent_user = await _user(db_session, role=UserRole.agent.value, name="Agent")
    async with await _client(test_app, agent_user) as client:
        for path in ("/api/v1/pm/leases", "/api/v1/pm/inspections", "/api/v1/pm/documents"):
            r = await client.get(path, params={"as_tenant": "true"})
            assert r.status_code == 403, (path, r.text)


# ---------------------------------------------------------------------------
# Major 5: PDF upload options and signing resource type
# ---------------------------------------------------------------------------


async def test_pdf_upload_sends_raw_and_authenticated_and_is_signed_as_raw(db_session, monkeypatch):
    svc = _fake_cloud(monkeypatch)
    owner = await _user(db_session, name="Owner")
    upload = UploadFile(
        file=BytesIO(PDF), filename="id.pdf", headers=Headers({"content-type": "application/pdf"})
    )

    stored = await pm_documents.store_private_document(upload, owner_id=owner.id)

    options = svc._uploader.upload.call_args.kwargs
    assert options["resource_type"] == "raw"
    assert options["type"] == "authenticated"
    assert "fetch_format" not in options
    assert stored["file_url"] == RAW_URL

    doc = Document(
        owner_id=owner.id,
        document_type=DocumentType.id_proof,
        title="ID",
        file_url=stored["file_url"],
        file_path=stored["file_path"],
        mime_type="application/pdf",
        shared_with_agent=True,
    )
    assert await pm_documents.viewer_file_url(db_session, doc=doc, actor=owner) == (
        "https://signed.example/doc"
    )
    assert svc._url.call_args.kwargs["resource_type"] == "raw"
    assert svc._url.call_args.kwargs["type"] == "authenticated"


async def test_signing_uses_the_resource_type_cloudinary_stored(db_session, monkeypatch):
    svc = _fake_cloud(monkeypatch)
    owner = await _user(db_session, name="Owner")
    doc = Document(
        owner_id=owner.id,
        document_type=DocumentType.id_proof,
        title="ID",
        file_url=IMAGE_URL,
        file_path="documents/general/id.pdf",
        mime_type="application/pdf",
    )

    await pm_documents.viewer_file_url(db_session, doc=doc, actor=owner)

    assert svc._url.call_args.kwargs["resource_type"] == "image"


async def test_document_upload_without_title_uses_the_file_name(test_app, db_session, monkeypatch):
    _fake_cloud(monkeypatch)
    monkeypatch.setattr(
        CloudinaryService,
        "private_delivery_url",
        lambda self, public_id, *, resource_type="raw": "https://signed.example/doc",
    )
    owner = await _user(db_session, name="Owner")

    async with await _client(test_app, owner) as client:
        r = await client.post(
            "/api/v1/pm/documents/upload",
            files={"file": ("id.pdf", PDF, "application/pdf")},
            data={"document_type": "id_proof"},
        )
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "id.pdf"
    assert r.json()["file_url"] == "https://signed.example/doc"


# ---------------------------------------------------------------------------
# be-pm-8, admin-pm-11: a new lease copies the managed property's due day and grace period
# ---------------------------------------------------------------------------


async def test_lease_copies_due_day_and_grace_from_the_property(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    prop.payment_due_day = 12
    prop.grace_period_days = 3
    await db_session.flush()

    async with await _client(test_app, owner) as client:
        created = await client.post(
            "/api/v1/pm/leases",
            json={
                "property_id": prop.id,
                "tenant_name": "Tenant",
                "status": "active",
                "start_date": "2026-01-01",
                "end_date": "2027-12-31",
                "monthly_rent": 20000,
                "security_deposit": 40000,
            },
        )
        assert created.status_code == 201, created.text
        lease_id = created.json()["id"]
        assert created.json()["payment_due_day"] == 12
        assert created.json()["grace_period_days"] == 3

        generated = await client.post(
            "/api/v1/pm/rent/charges/generate",
            json={"lease_id": lease_id, "start_month": "2026-10-01"},
        )
        assert generated.status_code == 200, generated.text

    charge = (
        await db_session.execute(select(RentCharge).where(RentCharge.lease_id == lease_id))
    ).scalar_one()
    assert charge.due_date == date(2026, 10, 12)


# ---------------------------------------------------------------------------
# r3-est-b-10: dashboard activity carries title, description and a UTC datetime
# ---------------------------------------------------------------------------


async def test_dashboard_activity_items_carry_title_description_and_datetime(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    # The dashboard reads the cached-user dependency, so override it like the other PM tests.
    schema = UserSchema.model_validate(owner, from_attributes=True)

    async def _cached_user() -> UserSchema:
        return schema

    test_app.dependency_overrides[get_current_cached_active_user] = _cached_user

    async with await _client(test_app, owner) as client:
        req = await client.post(
            "/api/v1/pm/maintenance/requests",
            json={
                "property_id": prop.id,
                "category": "plumbing",
                "urgency": "low",
                "title": "Leaking tap",
                "description": "Kitchen sink drips",
            },
        )
        assert req.status_code == 201, req.text

        feed = await client.get("/api/v1/pm/dashboard/activity")
        assert feed.status_code == 200, feed.text
        items = [i for i in feed.json()["items"] if i["type"] == "maintenance_request"]
        assert items, feed.json()
        item = items[0]
        assert item["title"] == "Maintenance request: Leaking tap"
        assert item["description"] == "Kitchen sink drips"
        assert item["at"].endswith("Z")


# ---------------------------------------------------------------------------
# r3-est-b-22: tenant summary reports status and property name, and hides another owner's name
# ---------------------------------------------------------------------------


async def test_tenant_summary_reports_status_and_property_name(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    other_owner = await _user(db_session, name="Other owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    prop.title = "Owner Flat"
    lease = await _lease(db_session, owner, prop, tenant)

    async with await _client(test_app, owner) as client:
        active = await client.get("/api/v1/pm/tenants")
        assert active.status_code == 200, active.text
        row = next(i for i in active.json()["items"] if i["user_id"] == tenant.id)
        assert row["status"] == "active"
        assert row["property_name"] == "Owner Flat"

    # The same tenant holds a lease with another owner. That owner's title must not show here.
    other_prop = await _property(db_session, other_owner)
    other_prop.title = "Other Flat"
    await _lease(db_session, other_owner, other_prop, tenant)
    async with await _client(test_app, owner) as client:
        scoped = await client.get("/api/v1/pm/tenants")
        row = next(i for i in scoped.json()["items"] if i["user_id"] == tenant.id)
        assert row["property_name"] == "Owner Flat"

    lease.status = LeaseStatus.terminated
    await db_session.flush()
    async with await _client(test_app, owner) as client:
        vacated = await client.get("/api/v1/pm/tenants")
        row = next(i for i in vacated.json()["items"] if i["user_id"] == tenant.id)
        assert row["status"] == "vacated"
        assert row["property_name"] is None


# ---------------------------------------------------------------------------
# Minor 8: a tenant claim waits for the owner. The owner settles it, or the tenant or owner removes it.
# ---------------------------------------------------------------------------


async def _generated_charge(test_app, db_session, owner, tenant):
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    async with await _client(test_app, owner) as client:
        r = await client.post(
            "/api/v1/pm/rent/charges/generate",
            json={"lease_id": lease.id, "start_month": "2026-10-01"},
        )
        assert r.status_code == 200, r.text
    charge = (
        await db_session.execute(select(RentCharge).where(RentCharge.lease_id == lease.id))
    ).scalar_one()
    return charge


async def test_tenant_claim_is_settled_only_by_the_owner(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    charge = await _generated_charge(test_app, db_session, owner, tenant)

    async with await _client(test_app, tenant) as client:
        claim = await client.post(
            "/api/v1/pm/rent/payments",
            json={"charge_id": charge.id, "amount_paid": 5000, "payment_method": "upi"},
        )
        assert claim.status_code == 201, claim.text
        assert claim.json()["status"] == "pending"
        payment_id = claim.json()["id"]

        denied = await client.post(f"/api/v1/pm/rent/payments/{payment_id}/settle")
        assert denied.status_code == 403, denied.text

    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.pending  # a pending claim does not move the charge

    async with await _client(test_app, owner) as client:
        settled = await client.post(f"/api/v1/pm/rent/payments/{payment_id}/settle")
        assert settled.status_code == 200, settled.text
        assert settled.json()["status"] == "settled"

        again = await client.post(f"/api/v1/pm/rent/payments/{payment_id}/settle")
        assert again.status_code == 400, again.text

    await db_session.refresh(charge)
    assert charge.status in {RentChargeStatus.partial, RentChargeStatus.overdue}


async def test_pending_claim_is_withdrawn_or_rejected_but_not_a_settled_payment(
    test_app, db_session
):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    stranger = await _user(db_session, name="Stranger")
    charge = await _generated_charge(test_app, db_session, owner, tenant)
    body = {"charge_id": charge.id, "amount_paid": 1000}

    async with await _client(test_app, tenant) as client:
        withdrawn = (await client.post("/api/v1/pm/rent/payments", json=body)).json()["id"]
        gone = await client.delete(f"/api/v1/pm/rent/payments/{withdrawn}")
        assert gone.status_code == 204, gone.text

        rejected_later = (await client.post("/api/v1/pm/rent/payments", json=body)).json()["id"]
        to_settle = (await client.post("/api/v1/pm/rent/payments", json=body)).json()["id"]

    async with await _client(test_app, stranger) as client:
        blocked = await client.delete(f"/api/v1/pm/rent/payments/{rejected_later}")
        assert blocked.status_code == 403, blocked.text

    async with await _client(test_app, owner) as client:
        rejected = await client.delete(f"/api/v1/pm/rent/payments/{rejected_later}")
        assert rejected.status_code == 204, rejected.text

        settled = await client.post(f"/api/v1/pm/rent/payments/{to_settle}/settle")
        assert settled.status_code == 200, settled.text
        blocked_settled = await client.delete(f"/api/v1/pm/rent/payments/{to_settle}")
        assert blocked_settled.status_code == 400, blocked_settled.text


# ---------------------------------------------------------------------------
# Minor 9: a lease cannot be created already ended
# ---------------------------------------------------------------------------


async def test_lease_create_rejects_ended_statuses(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    body = {
        "property_id": prop.id,
        "start_date": "2026-01-01",
        "end_date": "2027-12-31",
        "monthly_rent": 20000,
        "security_deposit": 40000,
    }
    async with await _client(test_app, owner) as client:
        for ended in ("expired", "terminated", "renewed", "expiring_soon"):
            r = await client.post("/api/v1/pm/leases", json={**body, "status": ended})
            assert r.status_code == 422, (ended, r.text)
        ok = await client.post("/api/v1/pm/leases", json={**body, "status": "draft"})
        assert ok.status_code == 201, ok.text


# ---------------------------------------------------------------------------
# Major 6 / be-pm-3: a managed create with non-empty image_urls and amenity_ids persists them
# ---------------------------------------------------------------------------


async def test_managed_create_persists_image_urls_and_amenities(test_app, db_session, monkeypatch):
    owner = await _user(db_session, name="Owner")
    amenity = Amenity(title="Lift", is_active=True)
    db_session.add(amenity)
    await db_session.flush()

    async def _all_reachable(urls):
        return list(urls), []

    monkeypatch.setattr(property_crud.ValidationUtils, "verify_image_urls_async", _all_reachable)
    monkeypatch.setattr(property_crud, "_schedule_async_image_verification", lambda *a, **k: None)
    urls = ["https://images.example.com/a.jpg", "https://images.example.com/b.jpg"]

    async with await _client(test_app, owner) as client:
        r = await client.post(
            "/api/v1/pm/properties",
            json={
                "title": "Managed Flat",
                "property_type": "apartment",
                "purpose": "rent",
                "base_price": 50000,
                "monthly_rent": 25000,
                "city": "Bengaluru",
                "image_urls": urls,
                "amenity_ids": [amenity.id],
                "payment_due_day": 5,
                "grace_period_days": 7,
                "management_status": "active",
            },
        )
    assert r.status_code == 201, r.text
    property_id = r.json()["id"]

    stored_urls = (
        (
            await db_session.execute(
                select(PropertyImage.image_url).where(PropertyImage.property_id == property_id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(stored_urls) == sorted(urls)
    stored_amenities = (
        (
            await db_session.execute(
                select(PropertyAmenity.amenity_id).where(PropertyAmenity.property_id == property_id)
            )
        )
        .scalars()
        .all()
    )
    assert stored_amenities == [amenity.id]


# ---------------------------------------------------------------------------
# be-pm-1: a file URL reaches an agent only when the owner shared the document with agents
# ---------------------------------------------------------------------------


async def test_agent_sees_a_file_url_only_for_documents_shared_with_agents(db_session, monkeypatch):
    monkeypatch.setattr(
        CloudinaryService,
        "private_delivery_url",
        lambda self, public_id, *, resource_type="raw": "https://signed.example/doc",
    )
    owner = await _user(db_session, name="Owner")
    agent_row = Agent(
        name="Agent",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.intermediate,
    )
    db_session.add(agent_row)
    await db_session.flush()
    owner.agent_id = agent_row.id
    agent_user = await _user(db_session, role=UserRole.agent.value, name="Agent user")
    agent_user.agent_id = agent_row.id
    await db_session.flush()

    def _doc(shared_with_agent: bool) -> Document:
        return Document(
            owner_id=owner.id,
            document_type=DocumentType.id_proof,
            title="ID",
            file_url=RAW_URL,
            file_path="documents/general/id.pdf",
            mime_type="application/pdf",
            shared_with_agent=shared_with_agent,
        )

    shared, private = _doc(True), _doc(False)
    assert await pm_documents.viewer_file_url(db_session, doc=shared, actor=agent_user)
    assert await pm_documents.viewer_file_url(db_session, doc=private, actor=agent_user) is None
    assert await pm_documents.viewer_file_url(db_session, doc=private, actor=owner)


# ---------------------------------------------------------------------------
# be-pm-15: a tied form ignores the body property_id. Unknown ids on an untied form give 404.
# ---------------------------------------------------------------------------


async def test_tied_form_ignores_the_body_property_id(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    async with await _client(test_app, owner) as client:
        form = await client.post(
            "/api/v1/pm/applications/forms", json={"title": "F", "property_id": prop.id}
        )
        assert form.status_code == 201, form.text
        slug = form.json()["slug"]

    applicant = await _client(test_app, await _user(db_session, name="Applicant"))
    async with applicant as public:
        for body_property in (999_999_999, prop.id):
            sub = await public.post(
                f"/api/v1/pm/public/applications/{slug}/submit",
                json={"applicant_full_name": "Applicant", "property_id": body_property},
            )
            assert sub.status_code == 201, (body_property, sub.text)


# ---------------------------------------------------------------------------
# r3-est-a-17: terminated_at is not a field. The client must send termination_date.
# ---------------------------------------------------------------------------


async def test_terminate_rejects_the_old_terminated_at_key(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, None)
    async with await _client(test_app, owner) as client:
        bad = await client.post(
            f"/api/v1/pm/leases/{lease.id}/terminate", json={"terminated_at": "2026-10-01"}
        )
        assert bad.status_code == 422, bad.text
        ok = await client.post(
            f"/api/v1/pm/leases/{lease.id}/terminate", json={"termination_date": "2026-10-01"}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["termination_date"] == "2026-10-01"


# ---------------------------------------------------------------------------
# r3-est-a-8, r3-est-a-9: a managed PATCH persists core and PM fields it accepts
# ---------------------------------------------------------------------------


async def test_managed_patch_persists_core_and_pm_fields(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    async with await _client(test_app, owner) as client:
        r = await client.patch(
            f"/api/v1/pm/properties/{prop.id}",
            json={
                "city": "Pune",
                "monthly_rent": 25000,
                "payment_due_day": 9,
                "grace_period_days": 2,
                "management_status": "archived",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["city"] == "Pune"
    assert body["monthly_rent"] == 25000
    assert body["payment_due_day"] == 9
    assert body["grace_period_days"] == 2
    assert body["management_status"] == "archived"
