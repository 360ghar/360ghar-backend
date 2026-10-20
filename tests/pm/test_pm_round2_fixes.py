"""PM contract fix round 2: tenant PII, one occupying lease per property, public submit rate
limit, agent file URLs and the business date. Each test names the reviewer finding it covers.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.core.exceptions import BadRequestException
from app.models.agents import Agent
from app.models.enums import AgentType, DocumentType, ExperienceLevel, LeaseStatus, UserRole
from app.models.pm_documents import Document
from app.services import pm_documents
from app.services.pm import rent_rules
from app.services.pm.lifecycle import expire_leases
from app.services.pm_leases import renew_lease
from tests.pm.test_pm_contract_wave3 import _client, _lease, _property, _user

pytestmark = pytest.mark.asyncio

PUBLIC_RAW = "https://res.cloudinary.com/demo/raw/upload/360ghar/documents/general/id.pdf"


def _lease_body(property_id: int, *, status: str) -> dict:
    return {
        "property_id": property_id,
        "tenant_name": "Typed Tenant",
        "tenant_phone": "+919000000001",
        "tenant_email": "typed@example.com",
        "status": status,
        "start_date": "2026-11-01",
        "end_date": "2027-10-31",
        "monthly_rent": 20000,
        "security_deposit": 40000,
    }


# ---------------------------------------------------------------------------
# Finding 1 (blocker, be-pm-0): an owner who links any user id to a lease must not read that
# user's account PII. The tenant detail and list return the contact fields the owner typed.
# ---------------------------------------------------------------------------


async def test_owner_cannot_read_a_linked_users_account_details(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    account_holder = await _user(db_session, name="Account Holder")
    prop = await _property(db_session, owner)
    async with await _client(test_app, owner) as client:
        created = await client.post(
            "/api/v1/pm/leases",
            json={**_lease_body(prop.id, status="active"), "tenant_user_id": account_holder.id},
        )
        assert created.status_code == 201, created.text

        detail = await client.get(f"/api/v1/pm/tenants/{account_holder.id}")
        assert detail.status_code == 200, detail.text
        listing = await client.get("/api/v1/pm/tenants")
        assert listing.status_code == 200, listing.text

    for body in (detail.text, listing.text):
        assert account_holder.email not in body
        assert account_holder.phone not in body
        assert "Account Holder" not in body

    assert detail.json()["full_name"] == "Typed Tenant"
    assert detail.json()["email"] == "typed@example.com"
    row = next(i for i in listing.json()["items"] if i["user_id"] == account_holder.id)
    assert row["full_name"] == "Typed Tenant"
    assert row["phone"] == "+919000000001"


# ---------------------------------------------------------------------------
# Finding 4 (major, be-pm-10): expiring_soon still occupies the property.
# ---------------------------------------------------------------------------


async def test_active_lease_is_refused_while_another_is_expiring_soon(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease_a = await _lease(db_session, owner, prop, None)  # active, ends 2027-12-31
    await expire_leases(db_session, today=date(2027, 12, 1))
    await db_session.refresh(lease_a)
    assert lease_a.status == LeaseStatus.expiring_soon

    async with await _client(test_app, owner) as client:
        second = await client.post("/api/v1/pm/leases", json=_lease_body(prop.id, status="active"))
        assert second.status_code == 400, second.text
        # A draft does not occupy the unit, so it is still allowed.
        draft = await client.post("/api/v1/pm/leases", json=_lease_body(prop.id, status="draft"))
        assert draft.status_code == 201, draft.text


async def test_renew_is_refused_while_another_lease_occupies_the_property(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    old = await _lease(db_session, owner, prop, None)
    await expire_leases(db_session, today=date(2027, 12, 1))
    await db_session.refresh(old)
    assert old.status == LeaseStatus.expiring_soon
    # A second occupying lease, as rows created before the unique index could hold. The index
    # is dropped for this transaction only, so the test rolls it back with everything else.
    conn = await db_session.connection()
    await conn.exec_driver_sql("DROP INDEX uq_leases_property_active")
    await _lease(db_session, owner, prop, None)

    with pytest.raises(BadRequestException):
        await renew_lease(
            db_session,
            actor=owner,  # type: ignore[arg-type]
            lease_id=old.id,
            start_date=date(2028, 1, 1),
            end_date=date(2028, 12, 31),
            make_active=True,
        )


# ---------------------------------------------------------------------------
# Finding 6 (major, be-pm-15): 11 anonymous submits from one client give 429 on the 11th.
# ---------------------------------------------------------------------------


async def test_public_submit_is_rate_limited_per_client(test_app, db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    async with await _client(test_app, owner) as client:
        form = await client.post(
            "/api/v1/pm/applications/forms", json={"title": "F", "property_id": prop.id}
        )
        assert form.status_code == 201, form.text
        slug = form.json()["slug"]

    store: dict[str, int] = {}

    class _MemoryCache:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value, ttl=None):
            store[key] = value

    applicant = await _client(test_app, await _user(db_session, name="Applicant"))
    responses = []
    with patch("app.middleware.rate_limit.get_cache_manager", return_value=_MemoryCache()):
        async with applicant as public:
            for _ in range(11):
                responses.append(
                    await public.post(
                        f"/api/v1/pm/public/applications/{slug}/submit",
                        json={"applicant_full_name": "Applicant"},
                    )
                )

    assert [r.status_code for r in responses[:10]] == [201] * 10
    limited = responses[10]
    assert limited.status_code == 429, limited.text
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.headers["Retry-After"] == "60"


# ---------------------------------------------------------------------------
# Finding 16 (minor, be-pm-1): the helper checks the owner-agent link itself.
# ---------------------------------------------------------------------------


async def test_agent_file_url_needs_the_owner_to_be_assigned_to_that_agent(db_session):
    owner = await _user(db_session, name="Owner")
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
    owner.agent_id = own_agent.id
    own_user = await _user(db_session, role=UserRole.agent.value, name="Own agent user")
    own_user.agent_id = own_agent.id
    foreign_user = await _user(db_session, role=UserRole.agent.value, name="Foreign agent user")
    foreign_user.agent_id = other_agent.id
    await db_session.flush()

    doc = Document(
        owner_id=owner.id,
        document_type=DocumentType.id_proof,
        title="ID",
        file_url=PUBLIC_RAW,
        file_path="documents/general/id.pdf",
        mime_type="application/pdf",
        shared_with_agent=True,
    )

    assert await pm_documents.viewer_file_url(db_session, doc=doc, actor=own_user) == PUBLIC_RAW
    # The document is shared with agents, but this agent does not manage the owner.
    assert await pm_documents.viewer_file_url(db_session, doc=doc, actor=foreign_user) is None


# ---------------------------------------------------------------------------
# Finding 14 (minor): one business date for the daily job and read-time overdue.
# ---------------------------------------------------------------------------


def test_business_date_follows_the_business_timezone(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # 20:00 UTC on 14 October is 01:30 on 15 October in Asia/Kolkata.
    fixed_utc = datetime(2026, 10, 14, 20, 0, tzinfo=ZoneInfo("UTC"))

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_utc.astimezone(tz)

    monkeypatch.setattr(rent_rules, "datetime", _FixedDatetime)
    monkeypatch.setattr(rent_rules.settings, "NOTIF_SCHED_TZ", "Asia/Kolkata")
    assert rent_rules.business_today() == date(2026, 10, 15)
