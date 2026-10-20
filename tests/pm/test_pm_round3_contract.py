"""PM residual pass: tenant access while the lease occupies the unit, the lease index,
owner contact on PM routes, application fields read back, exact application fee, and the
lease money and range bounds. Each test names the finding it covers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import LeaseStatus
from app.models.pm_leases import Lease
from app.models.pm_tenants import RentalApplication, RentalApplicationForm
from app.services.pm.lifecycle import expire_leases
from tests.pm.test_pm_contract_wave3 import _client, _lease, _property, _user

pytestmark = pytest.mark.asyncio

FUTURE = (datetime.now(UTC) + timedelta(days=365)).isoformat()
PAST = (datetime.now(UTC) - timedelta(days=1)).isoformat()


def _maintenance_body(prop_id: int, lease_id: int) -> dict:
    return {
        "property_id": prop_id,
        "lease_id": lease_id,
        "category": "plumbing",
        "urgency": "low",
        "title": "Leak",
    }


# ---------------------------------------------------------------------------
# Finding (major, pm_authz): a tenant on an expiring_soon lease keeps access, because the unit
# is still occupied. An expired lease does not.
# ---------------------------------------------------------------------------


async def test_tenant_on_an_expiring_soon_lease_keeps_access(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)  # active, ends 2027-12-31
    await expire_leases(db_session, today=datetime(2027, 12, 1, tzinfo=UTC).date())
    await db_session.refresh(lease)
    assert lease.status == LeaseStatus.expiring_soon

    async with await _client(test_app, tenant) as client:
        detail = await client.get(f"/api/v1/pm/properties/{prop.id}")
        request = await client.post(
            "/api/v1/pm/maintenance/requests", json=_maintenance_body(prop.id, lease.id)
        )

    assert detail.status_code == 200, detail.text
    assert request.status_code == 201, request.text


async def test_tenant_on_an_expired_lease_loses_access(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, tenant)
    await expire_leases(db_session, today=datetime(2028, 1, 10, tzinfo=UTC).date())
    await db_session.refresh(lease)
    assert lease.status == LeaseStatus.expired

    async with await _client(test_app, tenant) as client:
        detail = await client.get(f"/api/v1/pm/properties/{prop.id}")

    assert detail.status_code == 403, detail.text


# ---------------------------------------------------------------------------
# Finding (major, be-pm-26 / be-pm-10): the ORM declares the one-occupying-lease index, so a
# schema built from the models refuses a second occupying lease.
# ---------------------------------------------------------------------------


async def test_orm_declares_one_occupying_lease_per_property(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    await _lease(db_session, owner, prop, None)  # active

    db_session.add(
        Lease(
            property_id=prop.id,
            owner_id=owner.id,
            status=LeaseStatus.expiring_soon,
            start_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
            end_date=datetime(2027, 12, 31, tzinfo=UTC).date(),
            monthly_rent=Decimal("20000.00"),
            security_deposit=Decimal("40000.00"),
            grace_period_days=5,
            payment_due_day=5,
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.flush()
    assert "uq_leases_property_active" in str(exc_info.value.orig)


async def test_create_lease_maps_the_index_violation_to_400(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    await _lease(db_session, owner, prop, None)  # active, found by the pre-check

    body = {
        "property_id": prop.id,
        "status": "active",
        "start_date": "2026-11-01",
        "end_date": "2027-10-31",
        "monthly_rent": 20000,
        "security_deposit": 40000,
    }
    # Simulate the race: the pre-check sees no occupying lease, the index refuses the insert.
    with patch("app.services.pm_leases.OCCUPIED_LEASE_STATUSES", []):
        async with await _client(test_app, owner) as client:
            response = await client.post("/api/v1/pm/leases", json=body)

    assert response.status_code == 400, response.text
    assert "concurrent conflict" in response.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Finding (medium, be-pm-25): PM property routes hide the owner's contact from a tenant.
# ---------------------------------------------------------------------------


async def test_pm_property_routes_hide_the_owner_contact_from_a_tenant(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    tenant = await _user(db_session, name="Tenant")
    prop = await _property(db_session, owner)
    prop.owner_contact = "+919811111111"
    await db_session.flush()
    await _lease(db_session, owner, prop, tenant)

    async with await _client(test_app, owner) as client:
        owner_view = await client.get(f"/api/v1/pm/properties/{prop.id}")
    async with await _client(test_app, tenant) as client:
        tenant_view = await client.get(f"/api/v1/pm/properties/{prop.id}")

    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["property"]["owner_contact"] == "+919811111111"
    assert tenant_view.status_code == 200, tenant_view.text
    assert tenant_view.json()["property"]["owner_contact"] != "+919811111111"


# ---------------------------------------------------------------------------
# Findings r3-est-b-15, r3-est-b-16, r3-est-b-19, r3-est-b-20 (critical and high): the
# application fields are read back, not only the status code.
# ---------------------------------------------------------------------------

CUSTOM_FIELDS = [
    {"id": "occupants", "label": "Occupants", "field_type": "number", "is_required": True},
    {"id": "pets", "label": "Pets", "field_type": "boolean", "is_required": False},
]
# The response and the stored JSON both carry the optional key with its default.
WIRE_FIELDS = [{**field, "options": None} for field in CUSTOM_FIELDS]


async def _form(test_app, owner, prop, **extra) -> dict:
    body = {"title": "Flat application", "property_id": prop.id, **extra}
    async with await _client(test_app, owner) as client:
        created = await client.post("/api/v1/pm/applications/forms", json=body)
    assert created.status_code == 201, created.text
    return created.json()


async def test_form_create_stores_custom_fields_active_flag_and_expiry(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    prop.full_address = "12 MG Road, Pune"
    await db_session.flush()
    form = await _form(
        test_app,
        owner,
        prop,
        custom_fields=CUSTOM_FIELDS,
        is_active=True,
        expires_at=FUTURE,
        application_fee_amount=500,
    )

    async with await _client(test_app, owner) as client:
        detail = await client.get(f"/api/v1/pm/applications/forms/{form['id']}")
    async with await _client(test_app, owner) as client:
        public = await client.get(f"/api/v1/pm/public/applications/{form['slug']}")

    assert detail.status_code == 200, detail.text
    assert detail.json()["custom_fields"] == WIRE_FIELDS
    assert detail.json()["is_active"] is True
    assert detail.json()["expires_at"] == form["expires_at"]
    assert detail.json()["property_name"] == "PM Flat"
    assert detail.json()["property_address"] == "12 MG Road, Pune"
    assert public.status_code == 200, public.text
    assert public.json()["custom_fields"] == WIRE_FIELDS
    assert public.json()["expires_at"] == form["expires_at"]
    assert public.json()["property_name"] == "PM Flat"
    assert public.json()["property_address"] == "12 MG Road, Pune"

    stored = await db_session.get(RentalApplicationForm, form["id"])
    assert stored is not None
    assert stored.questions == WIRE_FIELDS


async def test_submit_is_read_back_in_the_inbox_and_the_detail(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    prop.full_address = "12 MG Road, Pune"
    await db_session.flush()
    form = await _form(test_app, owner, prop, custom_fields=CUSTOM_FIELDS)

    submission = {
        "applicant_full_name": "Asha Verma",
        "applicant_phone": "+919822222222",
        "applicant_email": "asha@example.com",
        "answers": {"occupants": 3, "pets": True},
        "application_data": {"notes": "Moving in January"},
        "emergency_contacts": {"name": "Ravi", "phone": "+919833333333"},
    }
    async with await _client(test_app, owner) as public:
        sent = await public.post(
            f"/api/v1/pm/public/applications/{form['slug']}/submit", json=submission
        )
    assert sent.status_code == 201, sent.text
    assert set(sent.json()) == {"id", "status", "submitted_at"}
    app_id = sent.json()["id"]

    async with await _client(test_app, owner) as client:
        inbox = await client.get("/api/v1/pm/applications")
        detail = await client.get(f"/api/v1/pm/applications/{app_id}")

    assert inbox.status_code == 200, inbox.text
    row = next(i for i in inbox.json()["items"] if i["id"] == app_id)
    assert detail.status_code == 200, detail.text
    for body in (row, detail.json()):
        assert body["applicant_full_name"] == "Asha Verma"
        assert body["applicant_phone"] == "+919822222222"
        assert body["applicant_email"] == "asha@example.com"
        assert body["answers"] == {"occupants": 3, "pets": True}
        assert body["application_data"] == {"notes": "Moving in January"}
        assert body["emergency_contacts"] == {"name": "Ravi", "phone": "+919833333333"}
        assert body["property_name"] == "PM Flat"
        assert body["property_address"] == "12 MG Road, Pune"
        assert body["status"] == "applicant"
    assert "applicant_name" not in row
    assert "custom_field_responses" not in row

    stored = await db_session.get(RentalApplication, app_id)
    assert stored is not None
    assert stored.applicant_full_name == "Asha Verma"
    assert stored.answers == {"occupants": 3, "pets": True}


async def test_decision_notes_are_read_back(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    form = await _form(test_app, owner, prop)
    async with await _client(test_app, owner) as public:
        sent = await public.post(
            f"/api/v1/pm/public/applications/{form['slug']}/submit",
            json={"applicant_full_name": "Asha Verma"},
        )
    app_id = sent.json()["id"]

    async with await _client(test_app, owner) as client:
        decided = await client.post(
            f"/api/v1/pm/applications/{app_id}/decision",
            json={"decision": "approved", "notes": "References checked"},
        )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    assert decided.json()["decision_notes"] == "References checked"


async def test_form_past_expires_at_is_not_found_on_the_public_route(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    form = await _form(test_app, owner, prop, expires_at=PAST)

    async with await _client(test_app, owner) as public:
        read = await public.get(f"/api/v1/pm/public/applications/{form['slug']}")
        sent = await public.post(
            f"/api/v1/pm/public/applications/{form['slug']}/submit",
            json={"applicant_full_name": "Late Applicant"},
        )
    assert read.status_code == 404, read.text
    assert sent.status_code == 404, sent.text


async def test_inactive_form_is_not_found_on_the_public_route(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    form = await _form(test_app, owner, prop, is_active=False)

    async with await _client(test_app, owner) as public:
        read = await public.get(f"/api/v1/pm/public/applications/{form['slug']}")
    assert read.status_code == 404, read.text


async def test_unknown_keys_are_refused_on_submit_and_form_create(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    form = await _form(test_app, owner, prop)

    async with await _client(test_app, owner) as public:
        submit = await public.post(
            f"/api/v1/pm/public/applications/{form['slug']}/submit",
            json={"applicant_name": "Old key", "custom_field_responses": {}},
        )
    async with await _client(test_app, owner) as client:
        create = await client.post(
            "/api/v1/pm/applications/forms",
            json={"title": "F", "property_id": prop.id, "custom_field_responses": {}},
        )
    assert submit.status_code == 422, submit.text
    assert create.status_code == 422, create.text


async def test_application_fee_round_trips_exactly(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    form = await _form(test_app, owner, prop, application_fee_amount=1234.56)

    assert form["application_fee_amount"] == 1234.56
    stored = await db_session.get(RentalApplicationForm, form["id"])
    assert stored is not None
    assert stored.application_fee_amount == Decimal("1234.56")
    async with await _client(test_app, owner) as client:
        read = await client.get(f"/api/v1/pm/applications/forms/{form['id']}")
    assert read.json()["application_fee_amount"] == 1234.56


# ---------------------------------------------------------------------------
# Finding (minor, be-pm-12 / be-pm-14): money and range bounds on the lease write body.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"security_deposit": -1},
        {"grace_period_days": -1},
        {"late_fee_amount": -5},
        {"payment_due_day": 0},
        {"payment_due_day": 29},
        {"monthly_rent": 0},
    ],
)
async def test_lease_create_refuses_out_of_range_money_and_terms(test_app, db_session, override):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    body = {
        "property_id": prop.id,
        "status": "draft",
        "start_date": "2026-11-01",
        "end_date": "2027-10-31",
        "monthly_rent": 20000,
        "security_deposit": 40000,
        **override,
    }
    async with await _client(test_app, owner) as client:
        response = await client.post("/api/v1/pm/leases", json=body)
    assert response.status_code == 422, response.text
