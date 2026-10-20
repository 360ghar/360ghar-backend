"""PM contract wave 2: late fees, grace, lease expiry, visibility, money and enum wire rules."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import cloudinary
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.exceptions import ForbiddenException, InsufficientPermissionsError
from app.models.agents import Agent
from app.models.enums import (
    AgentType,
    DocumentType,
    ExperienceLevel,
    LeaseStatus,
    PropertyPurpose,
    PropertyType,
    RentChargeStatus,
    RentPaymentStatus,
    UserRole,
)
from app.models.pm_documents import Document
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.properties import Property
from app.models.users import User
from app.schemas.user import User as UserSchema
from app.services.cloudinary import get_cloudinary_service
from app.services.pm.lifecycle import assess_overdue_charges, expire_leases
from app.services.pm.occupancy import OCCUPIED_LEASE_STATUSES
from app.services.pm.rent_rules import grace_days, is_overdue, late_fee
from app.services.pm_documents import update_document, viewer_file_url
from app.services.pm_leases import renew_lease
from app.services.pm_rent import generate_rent_charges, record_rent_payment

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 10, 14)


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


async def _property(db, owner: User, **extra) -> Property:
    prop = Property(
        title="PM Flat",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=30000,
        owner_id=owner.id,
        is_managed=True,
        **extra,
    )
    db.add(prop)
    await db.flush()
    return prop


async def _lease(db, owner: User, prop: Property, tenant: User | None, **kwargs) -> Lease:
    values = {
        "property_id": prop.id,
        "owner_id": owner.id,
        "tenant_user_id": tenant.id if tenant else None,
        "status": LeaseStatus.active,
        "start_date": date(2026, 1, 1),
        "end_date": date(2027, 12, 31),
        "monthly_rent": Decimal("20000.00"),
        "security_deposit": Decimal("40000.00"),
        "grace_period_days": 5,
        "payment_due_day": 5,
    }
    values.update(kwargs)
    lease = Lease(**values)
    db.add(lease)
    await db.flush()
    await db.refresh(lease)
    return lease


async def _charge(
    db, owner: User, lease: Lease, *, due: date, status=RentChargeStatus.pending
) -> RentCharge:
    charge = RentCharge(
        lease_id=lease.id,
        property_id=lease.property_id,
        owner_id=owner.id,
        tenant_user_id=lease.tenant_user_id,
        billing_month=due.replace(day=1),
        period_start=due.replace(day=1),
        period_end=due.replace(day=28),
        due_date=due,
        amount_due=float(lease.monthly_rent),
        late_fee_assessed=0.0,
        status=status,
    )
    db.add(charge)
    await db.flush()
    await db.refresh(charge)
    return charge


async def _client(test_app, user: User) -> AsyncClient:
    schema = UserSchema.model_validate(user, from_attributes=True)

    async def _current() -> UserSchema:
        return schema

    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )

    test_app.dependency_overrides[get_current_user] = _current
    test_app.dependency_overrides[get_current_active_user] = _current
    test_app.dependency_overrides[get_current_user_optional] = _current
    transport = ASGITransport(app=test_app)
    return AsyncClient(transport=transport, base_url="http://test", timeout=60.0)


# ---------------------------------------------------------------------------
# Rules (pure)
# ---------------------------------------------------------------------------


def test_late_fee_fixed_amount_wins_over_percentage():
    assert late_fee(20000, 500, 10) == 500.0
    assert late_fee(20000, None, 10) == 2000.0
    assert late_fee(20000, None, None) == 0.0


def test_grace_zero_stays_zero_and_none_uses_default():
    assert grace_days(0) == 0
    assert grace_days(None) == 5


def test_overdue_only_after_grace_with_balance():
    due = date(2026, 10, 5)
    assert not is_overdue(due, 5, date(2026, 10, 10), 100.0)  # still in grace
    assert is_overdue(due, 5, date(2026, 10, 11), 100.0)
    assert not is_overdue(due, 5, date(2026, 10, 11), 0.0)  # nothing owed


def test_occupancy_includes_notice_window():
    assert LeaseStatus.expiring_soon in OCCUPIED_LEASE_STATUSES
    assert LeaseStatus.expired not in OCCUPIED_LEASE_STATUSES


# ---------------------------------------------------------------------------
# Daily lifecycle: overdue, late fee, expiry
# ---------------------------------------------------------------------------


async def test_daily_job_marks_overdue_and_assesses_fee_once(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant, late_fee_percentage=10.0)
    charge = await _charge(db_session, owner, lease, due=date(2026, 9, 5))

    first = await assess_overdue_charges(db_session, today=TODAY)
    assert first["charges_overdue"] == 1
    assert first["late_fees_assessed"] == 1
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.overdue
    assert float(charge.late_fee_assessed) == 2000.0

    second = await assess_overdue_charges(db_session, today=TODAY)
    assert second["late_fees_assessed"] == 0
    await db_session.refresh(charge)
    assert float(charge.late_fee_assessed) == 2000.0


async def test_grace_period_defers_overdue_and_fee(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(
        db_session, owner, prop, None, late_fee_amount=Decimal("300.00"), grace_period_days=10
    )
    charge = await _charge(db_session, owner, lease, due=date(2026, 9, 1))

    stats = await assess_overdue_charges(
        db_session, today=TODAY
    )  # 43 days late, grace 10 -> overdue
    assert stats["charges_overdue"] == 1
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.overdue

    early = await _charge(db_session, owner, lease, due=date(2026, 10, 10))
    stats = await assess_overdue_charges(
        db_session, today=date(2026, 10, 15)
    )  # 5 days late, grace 10
    assert stats["charges_overdue"] == 0
    await db_session.refresh(early)
    assert early.status == RentChargeStatus.pending

    stats = await assess_overdue_charges(db_session, today=date(2026, 10, 21))  # 11 days late
    assert stats["charges_overdue"] == 1
    await db_session.refresh(early)
    assert early.status == RentChargeStatus.overdue


async def test_lease_expiry_moves_by_end_date(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    prop = await _property(db_session, owner)
    soon = await _lease(db_session, owner, prop, None, end_date=TODAY + timedelta(days=10))
    prop2 = await _property(db_session, owner)
    gone = await _lease(db_session, owner, prop2, None, end_date=TODAY - timedelta(days=1))

    stats = await expire_leases(db_session, today=TODAY)
    assert stats["leases_expiring_soon"] >= 1
    assert stats["leases_expired"] >= 1
    await db_session.refresh(soon)
    await db_session.refresh(gone)
    assert soon.status == LeaseStatus.expiring_soon
    assert gone.status == LeaseStatus.expired


async def test_overdue_filter_matches_without_job(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, None)
    await _charge(db_session, owner, lease, due=date(2026, 8, 1))  # stored as pending

    items, _, _ = await _list_overdue(db_session, owner)
    assert [it["status"] for it in items] == [RentChargeStatus.overdue]


async def _list_overdue(db, owner):
    from app.models.enums import RentChargeStatus as RCS
    from app.services.pm_rent import list_rent_charges

    return await list_rent_charges(
        db, actor=owner, owner_id=owner.id, status=RCS.overdue, cursor_payload={}, limit=20
    )


# ---------------------------------------------------------------------------
# Rent payments: tenant claims, settled payments, generation
# ---------------------------------------------------------------------------


async def test_tenant_claim_is_pending_and_keeps_charge_status(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    charge = await _charge(db_session, owner, lease, due=TODAY + timedelta(days=3))

    claim = await record_rent_payment(
        db_session, actor=tenant, charge_id=charge.id, amount_paid=5000
    )
    assert claim.status == RentPaymentStatus.pending
    await db_session.refresh(charge)
    assert charge.status == RentChargeStatus.pending


async def test_generate_charges_bills_expiring_soon_leases(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    prop = await _property(db_session, owner)
    await _lease(db_session, owner, prop, None, status=LeaseStatus.expiring_soon)
    result = await generate_rent_charges(
        db_session, actor=owner, owner_id=owner.id, start_month=date(2026, 10, 1), months=1
    )
    assert result == {"created": 1, "skipped": 0}


async def test_renew_only_from_active_or_expiring_soon(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, None, status=LeaseStatus.terminated)
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException):
        await renew_lease(
            db_session,
            actor=owner,
            lease_id=lease.id,
            start_date=date(2028, 1, 1),
            end_date=date(2028, 12, 31),
            make_active=True,
        )


async def test_owner_payment_is_settled(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, None)
    charge = await _charge(db_session, owner, lease, due=TODAY)
    await record_rent_payment(db_session, actor=owner, charge_id=charge.id, amount_paid=8000)
    rows = (
        await db_session.execute(select(RentPayment).where(RentPayment.charge_id == charge.id))
    ).scalars()
    assert [r.status for r in rows] == [RentPaymentStatus.settled]


# ---------------------------------------------------------------------------
# Wire formats (API)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def api_owner(db_session) -> User:
    return await _user(db_session, role=UserRole.user.value, name="API Owner")


async def test_money_is_a_json_number_on_lease_create(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    async with await _client(test_app, api_owner) as client:
        r = await client.post(
            "/api/v1/pm/leases",
            json={
                "property_id": prop.id,
                "start_date": "2026-01-01",
                "end_date": "2027-12-31",
                "monthly_rent": 25000.5,
                "security_deposit": 50000,
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert isinstance(body["monthly_rent"], float)
    assert body["monthly_rent"] == 25000.5
    assert body["created_at"].endswith("Z")
    assert isinstance(body["payment_due_day"], int)


async def test_lease_create_rejects_zero_rent(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    async with await _client(test_app, api_owner) as client:
        r = await client.post(
            "/api/v1/pm/leases",
            json={
                "property_id": prop.id,
                "start_date": "2026-01-01",
                "end_date": "2027-12-31",
                "monthly_rent": 0,
                "security_deposit": 0,
            },
        )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_generate_charges_body_is_first_of_month(test_app, db_session, api_owner):
    async with await _client(test_app, api_owner) as client:
        bad = await client.post("/api/v1/pm/rent/charges/generate", json={"start_month": "2026-10"})
        assert bad.status_code == 422, bad.text
        none = await client.post("/api/v1/pm/rent/charges/generate")
        assert none.status_code == 200, none.text
        assert set(none.json()) == {"created", "skipped"}


async def test_payment_method_is_an_enum(test_app, db_session, api_owner):
    async with await _client(test_app, api_owner) as client:
        r = await client.post(
            "/api/v1/pm/rent/payments",
            json={"charge_id": 1, "amount_paid": 10, "payment_method": "card"},
        )
    assert r.status_code == 422, r.text


async def test_tenant_detail_requires_a_lease_link(test_app, db_session, api_owner):
    stranger = await _user(db_session, name="Stranger")
    async with await _client(test_app, api_owner) as client:
        r = await client.get(f"/api/v1/pm/tenants/{stranger.id}")
    assert r.status_code == 404, r.text


async def test_property_create_accepts_image_and_amenity_keys(test_app, db_session, api_owner):
    async with await _client(test_app, api_owner) as client:
        r = await client.post(
            "/api/v1/pm/properties",
            json={
                "title": "Managed Flat",
                "property_type": "apartment",
                "purpose": "rent",
                "base_price": 50000,
                "monthly_rent": 25000,
                "city": "Bengaluru",
                "image_urls": [],
                "amenity_ids": [],
                "payment_due_day": 5,
                "grace_period_days": 7,
                "management_status": "active",
            },
        )
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Managed Flat"


async def test_managed_update_rejects_unknown_key_and_null_title(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    async with await _client(test_app, api_owner) as client:
        unknown = await client.patch(f"/api/v1/pm/properties/{prop.id}", json={"bogus": 1})
        assert unknown.status_code == 422, unknown.text
        null_title = await client.patch(f"/api/v1/pm/properties/{prop.id}", json={"title": None})
        assert null_title.status_code == 422, null_title.text
        archived = await client.patch(
            f"/api/v1/pm/properties/{prop.id}", json={"management_status": "archived"}
        )
        assert archived.status_code == 200, archived.text


async def test_expense_title_round_trip_and_delete(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    async with await _client(test_app, api_owner) as client:
        created = await client.post(
            "/api/v1/pm/expenses",
            json={
                "property_id": prop.id,
                "category": "repairs",
                "title": "Tap fix",
                "amount": 1500.5,
                "expense_date": "2026-10-01",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["title"] == "Tap fix"
        assert body["property_name"] == "PM Flat"
        assert body["amount"] == 1500.5
        gone = await client.delete(f"/api/v1/pm/expenses/{body['id']}")
        assert gone.status_code == 204, gone.text


async def test_maintenance_keeps_cost_schedule_and_urgency(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    async with await _client(test_app, api_owner) as client:
        created = await client.post(
            "/api/v1/pm/maintenance/requests",
            json={
                "property_id": prop.id,
                "category": "plumbing",
                "urgency": "medium",
                "title": "Leak",
                "estimated_cost": 800,
                "scheduled_for": "2026-10-20T09:00:00+05:30",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["estimated_cost"] == 800.0
        assert body["scheduled_for"] == "2026-10-20T03:30:00Z"
        assert body["property_title"] == "PM Flat"
        req_id = body["id"]
        bad = await client.patch(
            f"/api/v1/pm/maintenance/requests/{req_id}", json={"priority": "high"}
        )
        assert bad.status_code == 422, bad.text
        ok = await client.patch(
            f"/api/v1/pm/maintenance/requests/{req_id}", json={"urgency": "high"}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["urgency"] == "high"


async def test_application_submit_rules(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    other = await _property(db_session, await _user(db_session, name="Other"))
    async with await _client(test_app, api_owner) as client:
        form = await client.post(
            "/api/v1/pm/applications/forms",
            json={
                "title": "Flat form",
                "custom_fields": [
                    {
                        "id": "employer",
                        "label": "Employer",
                        "field_type": "text",
                        "is_required": True,
                    }
                ],
                "is_active": True,
            },
        )
        assert form.status_code == 201, form.text
        slug = form.json()["slug"]
        assert form.json()["custom_fields"][0]["id"] == "employer"

    anonymous = await _client(test_app, await _user(db_session, name="Anon"))
    async with anonymous as public:
        missing = await public.post(
            f"/api/v1/pm/public/applications/{slug}/submit",
            json={"applicant_full_name": "A", "property_id": prop.id, "answers": {}},
        )
        assert missing.status_code == 400, missing.text
        unknown = await public.post(
            f"/api/v1/pm/public/applications/{slug}/submit",
            json={"applicant_full_name": "A", "property_id": 999999, "answers": {"employer": "x"}},
        )
        assert unknown.status_code == 404, unknown.text
        foreign = await public.post(
            f"/api/v1/pm/public/applications/{slug}/submit",
            json={
                "applicant_full_name": "A",
                "property_id": other.id,
                "answers": {"employer": "x"},
            },
        )
        assert foreign.status_code == 404, foreign.text
        ok = await public.post(
            f"/api/v1/pm/public/applications/{slug}/submit",
            json={"applicant_full_name": "A", "property_id": prop.id, "answers": {"employer": "x"}},
        )
        assert ok.status_code == 201, ok.text
        assert set(ok.json()) == {"id", "status", "submitted_at"}


async def test_application_decision_notes_and_enum(test_app, db_session, api_owner):
    prop = await _property(db_session, api_owner)
    async with await _client(test_app, api_owner) as client:
        form = await client.post(
            "/api/v1/pm/applications/forms", json={"title": "F", "property_id": prop.id}
        )
        slug = form.json()["slug"]
    anonymous = await _client(test_app, await _user(db_session, name="Anon"))
    async with anonymous as public:
        sub = await public.post(
            f"/api/v1/pm/public/applications/{slug}/submit", json={"applicant_full_name": "B"}
        )
        assert sub.status_code == 201, sub.text
        app_id = sub.json()["id"]
    async with await _client(test_app, api_owner) as client:
        pending = await client.post(
            f"/api/v1/pm/applications/{app_id}/decision", json={"decision": "pending"}
        )
        assert pending.status_code == 422, pending.text
        done = await client.post(
            f"/api/v1/pm/applications/{app_id}/decision",
            json={"decision": "approved", "notes": "Strong references"},
        )
        assert done.status_code == 200, done.text
        body = done.json()
        assert body["decision_notes"] == "Strong references"
        assert body["decided_by_user_id"] == api_owner.id
        assert body["decision_at"].endswith("Z")
        assert body["property_name"] == "PM Flat"


# ---------------------------------------------------------------------------
# Documents: visibility, private delivery, edit rights
# ---------------------------------------------------------------------------


async def _document(db, owner: User, **kwargs) -> Document:
    values = {
        "owner_id": owner.id,
        "document_type": DocumentType.lease_agreement,
        "title": "Lease",
        "file_url": "https://res.cloudinary.com/demo/raw/authenticated/x.pdf",
        "file_path": "documents/general/x.pdf",
        "mime_type": "application/pdf",
        "shared_with_agent": False,
        "shared_with_tenant": False,
    }
    values.update(kwargs)
    doc = Document(**values)
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def test_file_url_only_for_permitted_viewers(db_session):
    cloudinary.config(cloud_name="demo", api_key="k", api_secret="s")
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    agent = await _user(db_session, role=UserRole.agent.value, name="Agent")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    doc = await _document(db_session, owner, lease_id=lease.id, shared_with_agent=False)

    assert (await viewer_file_url(db_session, doc=doc, actor=owner)).startswith(
        "https://res.cloudinary.com/"
    )
    assert await viewer_file_url(db_session, doc=doc, actor=agent) is None
    assert await viewer_file_url(db_session, doc=doc, actor=tenant) is None

    doc.shared_with_agent = True
    doc.shared_with_tenant = True
    # An agent sees a shared file only for an owner assigned to that agent.
    linked = Agent(
        name="Linked agent",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.intermediate,
    )
    db_session.add(linked)
    await db_session.flush()
    owner.agent_id = linked.id
    agent.agent_id = linked.id
    await db_session.flush()
    assert await viewer_file_url(db_session, doc=doc, actor=agent) is not None
    assert await viewer_file_url(db_session, doc=doc, actor=tenant) is not None


async def test_private_delivery_url_is_authenticated_and_signed():
    cloudinary.config(cloud_name="demo", api_key="k", api_secret="s")
    url = get_cloudinary_service().private_delivery_url(
        "documents/general/x.pdf", resource_type="raw"
    )
    assert "/authenticated/" in url
    assert "s--" in url


async def test_tenant_cannot_change_document(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    doc = await _document(db_session, owner, lease_id=lease.id, shared_with_tenant=True)
    with pytest.raises((ForbiddenException, InsufficientPermissionsError)):
        await update_document(db_session, actor=tenant, document_id=doc.id, shared_with_agent=True)


# ---------------------------------------------------------------------------
# Reports: inclusive end day
# ---------------------------------------------------------------------------


async def test_income_end_day_is_inclusive(db_session):
    from app.services.pm_reports import income_report

    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, None)
    charge = await _charge(db_session, owner, lease, due=date(2026, 7, 5))
    db_session.add(
        RentPayment(
            charge_id=charge.id,
            lease_id=lease.id,
            property_id=prop.id,
            owner_id=owner.id,
            paid_at=datetime(2026, 7, 31, 23, 30, tzinfo=UTC),
            amount_paid=1234.5,
            status=RentPaymentStatus.settled,
        )
    )
    await db_session.flush()
    report = await income_report(
        db_session, actor=owner, owner_id=owner.id, start=date(2026, 7, 1), end=date(2026, 7, 31)
    )
    assert report["total_income"] == pytest.approx(1234.5)


async def test_legacy_public_document_keeps_its_stored_url(db_session):
    owner = await _user(db_session, role=UserRole.user.value, name="Owner")
    legacy_url = "https://res.cloudinary.com/demo/image/upload/legacy.pdf"
    doc = await _document(
        db_session, owner, file_url=legacy_url, file_path="documents/general/legacy.pdf"
    )
    assert await viewer_file_url(db_session, doc=doc, actor=owner) == legacy_url


def test_pdf_delivery_uses_the_raw_resource_type_of_its_upload():
    cloudinary.config(cloud_name="demo", api_key="k", api_secret="s")
    service = get_cloudinary_service()
    assert "/raw/authenticated/" in service.private_delivery_url(
        "documents/general/x.pdf", resource_type="raw"
    )
    assert "/image/authenticated/" in service.private_delivery_url(
        "documents/general/x.png", resource_type="image"
    )


async def test_scheduled_job_runs_under_the_advisory_lock(db_session, monkeypatch):
    """The scheduled entry point opens a session, takes the lock and returns the step counts."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import pm_scheduler

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(pm_scheduler, "get_bg_session_factory", lambda: factory)
    stats = await pm_scheduler.run_pm_daily_lifecycle()
    assert set(stats) >= {
        "charges_overdue",
        "late_fees_assessed",
        "leases_expired",
        "leases_expiring_soon",
    }
