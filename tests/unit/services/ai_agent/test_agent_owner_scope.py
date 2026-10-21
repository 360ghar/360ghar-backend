"""Agent tools see only the caller's owners, and writes check access (database-backed).

Two agents each manage one owner. Each owner has one property, lease, rent charge,
maintenance request, and booking. Every check runs against real rows.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.exceptions import BadRequestException, ForbiddenException
from app.models.agents import Agent
from app.models.bookings import Booking
from app.models.enums import (
    AgentType,
    BookingStatus,
    ExperienceLevel,
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    PaymentMethod,
    PaymentStatus,
    PropertyPurpose,
    PropertyType,
    RentChargeStatus,
    RentPaymentStatus,
)
from app.models.pm_finance import RentCharge, RentPayment
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.properties import Property
from app.models.users import User
from app.services.ai_agent.deps import AgentDeps
from app.services.ai_agent.tools import booking as booking_tools
from app.services.ai_agent.tools import owner as owner_tools


def _ctx(user, role: str, db):
    return SimpleNamespace(deps=AgentDeps(user=user, user_role=role, db=db))


@pytest.fixture
async def world(db_session):
    """Two agents, two owners, and one of each row per owner, plus an admin."""
    agent_a = Agent(
        name="RM A",
        contact_number="9000000001",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.beginner,
        is_active=True,
        is_available=True,
    )
    agent_b = Agent(
        name="RM B",
        contact_number="9000000002",
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.beginner,
        is_active=True,
        is_available=True,
    )
    db_session.add_all([agent_a, agent_b])
    await db_session.flush()

    def _user(name, role, agent_id, n):
        return User(
            supabase_user_id=f"scope-{n}",
            phone=f"+9188800000{n:02d}",
            full_name=name,
            role=role,
            agent_id=agent_id,
            is_active=True,
            is_verified=True,
        )

    rm_a = _user("RM A user", "agent", agent_a.id, 1)
    rm_b = _user("RM B user", "agent", agent_b.id, 2)
    owner_a = _user("Owner A", "user", agent_a.id, 3)
    owner_b = _user("Owner B", "user", agent_b.id, 4)
    tenant_a = _user("Tenant A", "user", None, 5)
    tenant_b = _user("Tenant B", "user", None, 6)
    admin = _user("Admin", "admin", None, 7)
    db_session.add_all([rm_a, rm_b, owner_a, owner_b, tenant_a, tenant_b, admin])
    await db_session.flush()

    def _property(title, owner):
        return Property(
            title=title,
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=25000,
            monthly_rent=25000,
            owner_id=owner.id,
            is_managed=True,
            latitude=12.97,
            longitude=77.59,
        )

    prop_a = _property("Flat A", owner_a)
    prop_b = _property("Flat B", owner_b)
    db_session.add_all([prop_a, prop_b])
    await db_session.flush()

    def _lease(prop, owner, tenant):
        return Lease(
            property_id=prop.id,
            owner_id=owner.id,
            tenant_user_id=tenant.id,
            status=LeaseStatus.active,
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 31),
            monthly_rent=25000,
            security_deposit=50000,
            payment_due_day=1,
            grace_period_days=5,
        )

    lease_a = _lease(prop_a, owner_a, tenant_a)
    lease_b = _lease(prop_b, owner_b, tenant_b)
    db_session.add_all([lease_a, lease_b])
    await db_session.flush()

    def _charge(lease, prop, owner, tenant):
        return RentCharge(
            lease_id=lease.id,
            property_id=prop.id,
            owner_id=owner.id,
            tenant_user_id=tenant.id,
            billing_month=date(2026, 10, 1),
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31),
            due_date=date(2026, 10, 1),
            amount_due=25000,
            status=RentChargeStatus.pending,
        )

    charge_a = _charge(lease_a, prop_a, owner_a, tenant_a)
    charge_b = _charge(lease_b, prop_b, owner_b, tenant_b)
    db_session.add_all([charge_a, charge_b])

    def _request(prop, owner, tenant, title):
        return MaintenanceRequest(
            property_id=prop.id,
            owner_id=owner.id,
            tenant_user_id=tenant.id,
            category=MaintenanceCategory.plumbing,
            urgency=MaintenanceUrgency.medium,
            title=title,
            request_status=MaintenanceRequestStatus.open,
        )

    req_a = _request(prop_a, owner_a, tenant_a, "Leaking tap A")
    req_b = _request(prop_b, owner_b, tenant_b, "Leaking tap B")
    db_session.add_all([req_a, req_b])

    def _booking(prop, tenant, ref):
        return Booking(
            user_id=tenant.id,
            property_id=prop.id,
            booking_reference=ref,
            check_in_date=date(2026, 12, 1),
            check_out_date=date(2026, 12, 3),
            nights=2,
            guests=2,
            base_amount=5000,
            taxes_amount=0,
            service_charges=0,
            discount_amount=0,
            total_amount=5000,
            booking_status=BookingStatus.confirmed,
            payment_status=PaymentStatus.pending,
            primary_guest_name="Guest",
            primary_guest_phone="+919000000009",
            primary_guest_email="guest@example.com",
        )

    booking_a = _booking(prop_a, tenant_a, "BK-SCOPE-A")
    booking_b = _booking(prop_b, tenant_b, "BK-SCOPE-B")
    db_session.add_all([booking_a, booking_b])
    await db_session.flush()

    return SimpleNamespace(
        db=db_session,
        rm_a=rm_a,
        rm_b=rm_b,
        owner_a=owner_a,
        owner_b=owner_b,
        tenant_a=tenant_a,
        admin=admin,
        prop_a=prop_a,
        prop_b=prop_b,
        lease_a=lease_a,
        lease_b=lease_b,
        charge_a=charge_a,
        req_a=req_a,
        req_b=req_b,
        booking_a=booking_a,
        booking_b=booking_b,
    )


def _lease_ids(result) -> list[int]:
    return sorted(item["lease_id"] for item in result["items"])


@pytest.mark.asyncio
async def test_rent_due_lists_only_the_callers_owners(world):
    mine = await owner_tools.agent_rent_list_due(_ctx(world.rm_a, "agent", world.db))
    theirs = await owner_tools.agent_rent_list_due(_ctx(world.rm_b, "agent", world.db))
    everything = await owner_tools.agent_rent_list_due(_ctx(world.admin, "admin", world.db))

    assert _lease_ids(mine) == [world.lease_a.id]
    assert _lease_ids(theirs) == [world.lease_b.id]
    assert _lease_ids(everything) == sorted([world.lease_a.id, world.lease_b.id])


@pytest.mark.asyncio
async def test_rent_due_owner_filter_outside_scope_is_empty(world):
    result = await owner_tools.agent_rent_list_due(
        _ctx(world.rm_a, "agent", world.db), owner_id=world.owner_b.id
    )

    assert result["items"] == []
    assert result["totals"]["total_due"] == 0
    assert "counts" not in result


@pytest.mark.asyncio
async def test_dashboard_counts_only_the_callers_portfolio(world):
    mine = await owner_tools.agent_dashboard_overview(_ctx(world.rm_a, "agent", world.db))
    everything = await owner_tools.agent_dashboard_overview(_ctx(world.admin, "admin", world.db))

    assert mine["stats"]["total_properties"] == 1
    assert mine["stats"]["occupied"] == 1
    assert everything["stats"]["total_properties"] == 2


@pytest.mark.asyncio
async def test_leases_list_is_scoped_and_counts_the_scope(world):
    result = await owner_tools.agent_leases_list(
        _ctx(world.rm_a, "agent", world.db), include_total=True
    )

    assert [item["id"] for item in result["leases"]] == [world.lease_a.id]
    assert result["total"] == 1
    # stats cover the caller's whole scope: one active lease at 25000 rent
    assert result["stats"] == {"active_leases": 1, "total_monthly_rent": 25000.0}


@pytest.mark.asyncio
async def test_maintenance_list_is_scoped(world):
    mine = await owner_tools.agent_maintenance_list(_ctx(world.rm_a, "agent", world.db))

    assert [item["id"] for item in mine["items"]] == [world.req_a.id]
    assert mine["total"] is None


@pytest.mark.asyncio
async def test_maintenance_update_outside_scope_is_rejected(world):
    ctx = _ctx(world.rm_a, "agent", world.db)

    with pytest.raises(ForbiddenException):
        await owner_tools.agent_maintenance_update_status(
            ctx, request_id=world.req_b.id, status="completed"
        )

    await world.db.refresh(world.req_b)
    assert world.req_b.request_status == MaintenanceRequestStatus.open


@pytest.mark.asyncio
async def test_bookings_list_all_is_scoped(world):
    result = await booking_tools.agent_bookings_list_all(
        _ctx(world.rm_a, "agent", world.db), include_total=True
    )

    assert [item["id"] for item in result["items"]] == [world.booking_a.id]
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_booking_status_outside_scope_is_rejected(world):
    ctx = _ctx(world.rm_a, "agent", world.db)

    with pytest.raises(ForbiddenException):
        await booking_tools.agent_bookings_update_status(
            ctx, booking_id=world.booking_b.id, status=BookingStatus.checked_in
        )

    await world.db.refresh(world.booking_b)
    assert world.booking_b.booking_status == BookingStatus.confirmed


@pytest.mark.asyncio
async def test_lease_create_on_own_property_writes_the_row(world):
    # One occupying lease per property (uq_leases_property_active): end the seeded lease first.
    world.lease_a.status = LeaseStatus.terminated
    await world.db.flush()

    result = await owner_tools.agent_leases_create(
        _ctx(world.rm_a, "agent", world.db),
        property_id=world.prop_a.id,
        tenant_user_id=world.tenant_a.id,
        start_date=date(2027, 1, 1),
        end_date=date(2028, 1, 1),
        monthly_rent=30000,
        security_deposit=60000,
        terms="No pets",
        notes="Parking spot 4",
    )

    assert "error" not in result
    lease = (
        await world.db.execute(select(Lease).where(Lease.id == result["lease"]["id"]))
    ).scalar_one()
    assert lease.property_id == world.prop_a.id
    assert lease.owner_id == world.owner_a.id
    assert lease.lease_terms == {"terms": "No pets"}
    assert lease.special_clauses == "Parking spot 4"


@pytest.mark.asyncio
async def test_lease_create_on_other_owner_property_is_rejected(world):
    result = await owner_tools.agent_leases_create(
        _ctx(world.rm_a, "agent", world.db),
        property_id=world.prop_b.id,
        tenant_user_id=world.tenant_a.id,
        start_date=date(2027, 1, 1),
        end_date=date(2028, 1, 1),
        monthly_rent=30000,
    )

    assert result["error"] is True
    count = (
        await world.db.execute(select(Lease.id).where(Lease.property_id == world.prop_b.id))
    ).all()
    assert len(count) == 1


@pytest.mark.asyncio
async def test_lease_create_rejects_end_before_start(world):
    result = await owner_tools.agent_leases_create(
        _ctx(world.rm_a, "agent", world.db),
        property_id=world.prop_a.id,
        tenant_user_id=world.tenant_a.id,
        start_date=date(2028, 1, 1),
        end_date=date(2027, 1, 1),
        monthly_rent=30000,
    )

    assert result["error"] is True
    assert "End date" in result["message"]


@pytest.mark.asyncio
async def test_rent_payment_writes_a_settled_row_for_the_callers_lease(world):
    result = await owner_tools.agent_rent_record_payment(
        _ctx(world.rm_a, "agent", world.db),
        lease_id=world.lease_a.id,
        amount=25000,
        payment_date=date(2026, 10, 5),
        payment_method=PaymentMethod.bank_transfer,
        transaction_reference="UTR-1",
    )

    payment = (
        await world.db.execute(select(RentPayment).where(RentPayment.lease_id == world.lease_a.id))
    ).scalar_one()
    assert payment.charge_id == world.charge_a.id
    assert payment.owner_id == world.owner_a.id
    assert float(payment.amount_paid) == 25000.0
    assert payment.payment_method == PaymentMethod.bank_transfer
    assert payment.status == RentPaymentStatus.settled
    assert payment.reference == "UTR-1"
    assert result["payment"]["id"] == payment.id
    assert result["payment"]["charge_id"] == world.charge_a.id


@pytest.mark.asyncio
async def test_rent_payment_on_other_owner_lease_is_rejected(world):
    with pytest.raises(ForbiddenException):
        await owner_tools.agent_rent_record_payment(
            _ctx(world.rm_a, "agent", world.db),
            lease_id=world.lease_b.id,
            amount=25000,
            payment_date=date(2026, 10, 5),
        )

    rows = (
        await world.db.execute(select(RentPayment).where(RentPayment.lease_id == world.lease_b.id))
    ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_rent_payment_without_an_open_charge_is_a_bad_request(world):
    world.charge_a.status = RentChargeStatus.paid
    await world.db.flush()

    with pytest.raises(BadRequestException):
        await owner_tools.agent_rent_record_payment(
            _ctx(world.rm_a, "agent", world.db),
            lease_id=world.lease_a.id,
            amount=25000,
            payment_date=date(2026, 10, 5),
        )


# ---------------------------------------------------------------------------
# Fix round 2: owner contact masking, stats scope, shared rent and maintenance
# operations, opt-in totals. Each admin MCP case runs against the same rows.
# ---------------------------------------------------------------------------


def _yield_db(db):
    async def _gen():
        yield db

    return _gen


@pytest.fixture
def company_number(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", "9000000999")
    return "9000000999"


@pytest.mark.asyncio
async def test_owner_phone_reaches_only_the_owner_and_admin(world):
    from app.mcp.tool_ops import get_property_detail

    world.prop_a.owner_contact = "9000000111"
    await world.db.flush()

    owner_view = await get_property_detail(
        world.db, actor=world.owner_a, property_id=world.prop_a.id
    )
    admin_view = await get_property_detail(world.db, actor=world.admin, property_id=world.prop_a.id)
    tenant_view = await get_property_detail(
        world.db, actor=world.tenant_a, property_id=world.prop_a.id
    )
    agent_view = await get_property_detail(world.db, actor=world.rm_a, property_id=world.prop_a.id)

    # The property carries the owner's assigned agent (agent_a, 9000000001), so non-owner
    # viewers get that number, never the owner's.
    assert owner_view["property"]["owner_phone"] == "9000000111"
    assert admin_view["property"]["owner_phone"] == "9000000111"
    assert tenant_view["property"]["owner_phone"] == "9000000001"
    assert agent_view["property"]["owner_phone"] == "9000000001"


@pytest.mark.asyncio
async def test_agent_and_owner_detail_tools_mask_by_viewer(world):
    world.prop_a.owner_contact = "9000000111"
    await world.db.flush()

    agent_result = await owner_tools.agent_properties_get(
        _ctx(world.rm_a, "agent", world.db), property_id=world.prop_a.id
    )
    owner_result = await owner_tools.owner_properties_get(
        _ctx(world.owner_a, "user", world.db), property_id=world.prop_a.id
    )

    assert agent_result["property"]["owner_phone"] == "9000000001"
    assert owner_result["property"]["owner_phone"] == "9000000111"


@pytest.mark.asyncio
async def test_agent_property_stats_cover_only_the_callers_owners(world):
    # An agent lists one owner at a time; the stats cover that owner only.
    mine = await owner_tools.agent_properties_list(
        _ctx(world.rm_a, "agent", world.db), owner_id=world.owner_a.id
    )
    everything = await owner_tools.agent_properties_list(_ctx(world.admin, "admin", world.db))

    assert mine["stats"]["total_properties"] == 1
    assert everything["stats"]["total_properties"] == 2
    assert mine["total"] is None
    counted = await owner_tools.agent_properties_list(
        _ctx(world.rm_a, "agent", world.db), owner_id=world.owner_a.id, include_total=True
    )
    assert counted["total"] == 1


@pytest.mark.asyncio
async def test_admin_mcp_property_stats_cover_only_the_callers_owners(world, monkeypatch):
    from app.mcp.admin.agent_tools import properties as admin_properties

    monkeypatch.setattr(admin_properties, "get_db", _yield_db(world.db))
    monkeypatch.setattr(admin_properties, "_get_user", AsyncMock(return_value=world.rm_a))

    result = await admin_properties.agent_properties_list(owner_id=world.owner_a.id)

    assert result["ok"] is True
    assert result["data"]["stats"]["total_properties"] == 1
    assert result["data"]["total"] is None


@pytest.mark.asyncio
async def test_owner_properties_list_total_is_opt_in(world):
    plain = await owner_tools.owner_properties_list(_ctx(world.owner_a, "user", world.db))
    counted = await owner_tools.owner_properties_list(
        _ctx(world.owner_a, "user", world.db), include_total=True
    )

    assert plain["total"] is None
    assert counted["total"] == 1
    assert [item["id"] for item in plain["items"]] == [world.prop_a.id]
    assert "has_active_lease" in plain["items"][0]


@pytest.mark.asyncio
async def test_agent_rent_payment_settles_the_charge(world):
    from app.models.enums import RentChargeStatus

    result = await owner_tools.agent_rent_record_payment(
        _ctx(world.rm_a, "agent", world.db),
        lease_id=world.lease_a.id,
        amount=25000,
        payment_date=date(2026, 10, 14),
        transaction_reference="TXN-7",
    )

    assert result["payment"]["amount_paid"] == 25000.0
    assert result["payment"]["status"] == "settled"
    await world.db.refresh(world.charge_a)
    assert world.charge_a.status == RentChargeStatus.paid


@pytest.mark.asyncio
async def test_admin_mcp_rent_payment_settles_the_charge(world, monkeypatch):
    from app.mcp.admin.agent_tools import rent as admin_rent
    from app.models.enums import PaymentMethod, RentChargeStatus, RentPaymentStatus

    monkeypatch.setattr(admin_rent, "get_db", _yield_db(world.db))
    monkeypatch.setattr(admin_rent, "_get_user", AsyncMock(return_value=world.rm_a))

    result = await admin_rent.agent_rent_record_payment(
        lease_id=world.lease_a.id,
        amount=25000,
        payment_date=date(2026, 10, 14),
        payment_method=PaymentMethod.upi,
        transaction_reference="TXN-8",
    )

    assert result["ok"] is True
    payment = result["data"]["payment"]
    assert payment["charge_id"] == world.charge_a.id
    assert payment["status"] == RentPaymentStatus.settled.value
    await world.db.refresh(world.charge_a)
    assert world.charge_a.status == RentChargeStatus.paid


@pytest.mark.asyncio
async def test_agent_maintenance_update_records_vendor_and_costs(world):
    await owner_tools.agent_maintenance_update_status(
        _ctx(world.rm_a, "agent", world.db),
        request_id=world.req_a.id,
        status="in_progress",
        vendor_name="Acme Plumbing",
        vendor_contact="9000000555",
        estimated_cost=800,
    )

    await world.db.refresh(world.req_a)
    assert world.req_a.vendor_name == "Acme Plumbing"
    assert world.req_a.vendor_contact == "9000000555"
    assert world.req_a.estimated_cost == 800


@pytest.mark.asyncio
async def test_admin_mcp_maintenance_open_clears_completion_and_schedule(world, monkeypatch):
    from datetime import UTC, datetime

    from app.mcp.admin.agent_tools import maintenance as admin_maintenance
    from app.models.enums import WorkOrderStatus

    monkeypatch.setattr(admin_maintenance, "get_db", _yield_db(world.db))
    monkeypatch.setattr(admin_maintenance, "_get_user", AsyncMock(return_value=world.rm_a))

    # A completed, scheduled request. "open" must clear both, as the agent tool does.
    req = world.req_a
    req.request_status = MaintenanceRequestStatus.resolved
    req.work_order_status = WorkOrderStatus.completed
    req.completed_at = datetime(2026, 10, 1, tzinfo=UTC)
    req.scheduled_for = datetime(2026, 10, 2, tzinfo=UTC)
    await world.db.flush()

    result = await admin_maintenance.agent_maintenance_update_status(
        request_id=req.id, status="open"
    )

    assert result["ok"] is True
    await world.db.refresh(req)
    assert req.request_status == MaintenanceRequestStatus.open
    assert req.completed_at is None
    assert req.scheduled_for is None


@pytest.mark.asyncio
async def test_user_bookings_total_is_opt_in(world):
    from app.mcp.tool_ops import list_user_bookings

    plain = await list_user_bookings(world.db, user_id=world.tenant_a.id)
    counted = await list_user_bookings(world.db, user_id=world.tenant_a.id, include_total=True)

    assert plain["total"] is None
    assert counted["total"] == 1
    assert [item["id"] for item in plain["items"]] == [world.booking_a.id]


# ---------------------------------------------------------------------------
# Wave 3d: a user embedded in a lease (the tenant) or a property detail (owner, tenant)
# goes through app.services.visibility. phone and email reach the owner of the lease's
# property, admins and the user themself. An assigned agent who is not the owner gets a
# PublicUserRef (id, display_name, avatar_url).
# ---------------------------------------------------------------------------


def _public_ref(user) -> dict:
    return {"id": user.id, "display_name": user.full_name, "avatar_url": None}


def _with_contact(user) -> dict:
    return {**_public_ref(user), "phone": user.phone, "email": user.email}


@pytest.mark.asyncio
async def test_agent_lease_list_gives_a_non_owner_agent_only_the_public_tenant_ref(world):
    result = await owner_tools.agent_leases_list(_ctx(world.rm_a, "agent", world.db))

    assert [lease["tenant"] for lease in result["leases"]] == [_public_ref(world.tenant_a)]
    assert "phone" not in str(result["leases"]) and "email" not in str(result["leases"])


@pytest.mark.asyncio
async def test_agent_lease_list_gives_the_owner_and_an_admin_the_tenant_contact(world):
    as_owner = await owner_tools.agent_leases_list(_ctx(world.owner_a, "user", world.db))
    as_admin = await owner_tools.agent_leases_list(_ctx(world.admin, "admin", world.db))

    assert [lease["tenant"] for lease in as_owner["leases"]] == [_with_contact(world.tenant_a)]
    own_lease_as_admin = next(
        lease for lease in as_admin["leases"] if lease["id"] == world.lease_a.id
    )
    assert own_lease_as_admin["tenant"] == _with_contact(world.tenant_a)


@pytest.mark.asyncio
async def test_admin_mcp_lease_list_masks_the_tenant_for_a_non_owner_agent(world, monkeypatch):
    from app.mcp.admin.agent_tools import leases as admin_leases

    monkeypatch.setattr(admin_leases, "get_db", _yield_db(world.db))
    monkeypatch.setattr(admin_leases, "_get_user", AsyncMock(return_value=world.rm_a))

    result = await admin_leases.agent_leases_list()

    assert result["ok"] is True
    assert [lease["tenant"] for lease in result["data"]["leases"]] == [_public_ref(world.tenant_a)]


@pytest.mark.asyncio
async def test_property_detail_embeds_owner_and_tenant_by_viewer(world):
    from app.mcp.tool_ops import get_property_detail

    as_agent = await get_property_detail(
        world.db, actor=world.rm_a, property_id=world.prop_a.id, include_owner_tenant=True
    )
    as_owner = await get_property_detail(
        world.db, actor=world.owner_a, property_id=world.prop_a.id, include_owner_tenant=True
    )
    as_admin = await get_property_detail(
        world.db, actor=world.admin, property_id=world.prop_a.id, include_owner_tenant=True
    )

    assert as_agent["owner"] == _public_ref(world.owner_a)
    assert as_agent["tenant"] == _public_ref(world.tenant_a)
    for full in (as_owner, as_admin):
        assert full["owner"] == _with_contact(world.owner_a)
        assert full["tenant"] == _with_contact(world.tenant_a)


@pytest.mark.asyncio
async def test_admin_mcp_property_detail_masks_owner_and_tenant_for_a_non_owner_agent(
    world, monkeypatch
):
    from app.mcp.admin.agent_tools import properties as admin_properties

    monkeypatch.setattr(admin_properties, "get_db", _yield_db(world.db))
    monkeypatch.setattr(admin_properties, "_get_user", AsyncMock(return_value=world.rm_a))

    as_agent = await admin_properties.agent_properties_get(property_id=world.prop_a.id)
    monkeypatch.setattr(admin_properties, "_get_user", AsyncMock(return_value=world.admin))
    as_admin = await admin_properties.agent_properties_get(property_id=world.prop_a.id)

    assert as_agent["data"]["owner"] == _public_ref(world.owner_a)
    assert as_agent["data"]["tenant"] == _public_ref(world.tenant_a)
    assert as_admin["data"]["owner"] == _with_contact(world.owner_a)
    assert as_admin["data"]["tenant"] == _with_contact(world.tenant_a)


@pytest.mark.asyncio
async def test_owner_lease_tool_gives_a_stranger_no_tenant_contact(world, monkeypatch):
    """owner_leases_get also serves a tenant. Another user gets no lease at all."""
    from app.mcp.chatgpt import pm_lease_tools
    from tests.unit.mcp.conftest import SessionContext

    monkeypatch.setattr(pm_lease_tools, "AsyncSessionLocal", lambda: SessionContext(world.db))
    for viewer, expected in (
        (world.owner_a, _with_contact(world.tenant_a)),
        (world.tenant_a, _with_contact(world.tenant_a)),
    ):
        monkeypatch.setattr(pm_lease_tools, "_get_optional_user", AsyncMock(return_value=viewer))
        result = await pm_lease_tools.owner_leases_get(lease_id=world.lease_a.id)
        assert result.structured_content["lease"]["tenant"] == expected

    monkeypatch.setattr(pm_lease_tools, "_get_optional_user", AsyncMock(return_value=world.rm_b))
    refused = await pm_lease_tools.owner_leases_get(lease_id=world.lease_a.id)
    assert refused.structured_content["error"] is True
    assert "tenant" not in str(refused.structured_content)


# ---------------------------------------------------------------------------
# Wave 3d: every MCP and agent tool that changes PM state calls the PM service. The caller's
# rights and the transition rules are the REST rules; no tool writes a status itself.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_maintenance_update_walks_the_service_transitions(world):
    from app.models.enums import WorkOrderStatus

    ctx = _ctx(world.rm_a, "agent", world.db)
    req = world.req_a

    await owner_tools.agent_maintenance_update_status(
        ctx, request_id=req.id, status="in_progress", notes="Plumber booked"
    )
    await world.db.refresh(req)
    assert req.request_status == MaintenanceRequestStatus.work_order_created
    assert req.work_order_status == WorkOrderStatus.in_progress
    assert req.completion_notes == "Plumber booked"
    assert req.completed_at is None

    await owner_tools.agent_maintenance_update_status(
        ctx, request_id=req.id, status="completed", notes="Washer replaced", actual_cost=450
    )
    await world.db.refresh(req)
    assert req.request_status == MaintenanceRequestStatus.resolved
    assert req.work_order_status == WorkOrderStatus.completed
    assert req.completed_at is not None
    assert req.completion_notes == "Plumber booked\nWasher replaced"  # notes are appended
    assert req.actual_cost == 450


@pytest.mark.asyncio
async def test_agent_maintenance_update_applies_the_service_transition_rules(world):
    """A completed work order cannot be cancelled (WORK_ORDER_TRANSITIONS). The tool no
    longer overwrites the status pair by hand."""
    from app.models.enums import WorkOrderStatus

    ctx = _ctx(world.rm_a, "agent", world.db)
    await owner_tools.agent_maintenance_update_status(
        ctx, request_id=world.req_a.id, status="completed"
    )

    with pytest.raises(BadRequestException, match="Cannot transition"):
        await owner_tools.agent_maintenance_update_status(
            ctx, request_id=world.req_a.id, status="cancelled"
        )

    await world.db.refresh(world.req_a)
    assert world.req_a.work_order_status == WorkOrderStatus.completed


@pytest.mark.asyncio
async def test_agent_maintenance_update_refuses_a_tenant_and_a_negative_cost(world):
    with pytest.raises(ForbiddenException):
        await owner_tools.agent_maintenance_update_status(
            _ctx(world.tenant_a, "user", world.db), request_id=world.req_a.id, status="completed"
        )
    with pytest.raises(BadRequestException, match="actual_cost"):
        await owner_tools.agent_maintenance_update_status(
            _ctx(world.rm_a, "agent", world.db),
            request_id=world.req_a.id,
            status="completed",
            actual_cost=-5,
        )

    await world.db.refresh(world.req_a)
    assert world.req_a.request_status == MaintenanceRequestStatus.open


@pytest.mark.asyncio
async def test_agent_maintenance_update_of_an_unknown_request_is_an_error_result(world):
    result = await owner_tools.agent_maintenance_update_status(
        _ctx(world.rm_a, "agent", world.db), request_id=999_999, status="open"
    )

    assert result["error"] is True


@pytest.mark.asyncio
async def test_owner_maintenance_tool_goes_through_the_service(world, monkeypatch):
    from app.mcp.chatgpt import pm_maintenance_tools
    from app.models.enums import WorkOrderStatus
    from tests.unit.mcp.conftest import SessionContext

    monkeypatch.setattr(pm_maintenance_tools, "AsyncSessionLocal", lambda: SessionContext(world.db))
    monkeypatch.setattr(
        pm_maintenance_tools, "_get_optional_user", AsyncMock(return_value=world.owner_a)
    )

    done = await pm_maintenance_tools.owner_maintenance_update(
        request_id=world.req_a.id,
        status="scheduled",
        scheduled_date="2026-11-02T09:00:00Z",
        resolution_notes="Visit on 2 Nov",
    )
    assert done.structured_content["request"]["status"] == "scheduled"
    await world.db.refresh(world.req_a)
    assert world.req_a.work_order_status == WorkOrderStatus.assigned
    assert world.req_a.scheduled_for is not None
    assert world.req_a.completion_notes == "Visit on 2 Nov"

    # The service refuses a work order that cannot go back to open from here (the REST rule).
    refused = await pm_maintenance_tools.owner_maintenance_update(
        request_id=world.req_a.id, status="open"
    )
    assert refused.structured_content["code"] == "INVALID_INPUT"
    await world.db.refresh(world.req_a)
    assert world.req_a.work_order_status == WorkOrderStatus.assigned

    # Another owner's request is not theirs to update.
    monkeypatch.setattr(
        pm_maintenance_tools, "_get_optional_user", AsyncMock(return_value=world.owner_b)
    )
    forbidden = await pm_maintenance_tools.owner_maintenance_update(
        request_id=world.req_a.id, status="completed"
    )
    assert forbidden.structured_content["code"] == "FORBIDDEN"
    missing = await pm_maintenance_tools.owner_maintenance_update(
        request_id=999_999, status="completed"
    )
    assert missing.structured_content["code"] == "NOT_FOUND"
    bad_date = await pm_maintenance_tools.owner_maintenance_update(
        request_id=world.req_b.id, status="scheduled", scheduled_date="not-a-date"
    )
    assert bad_date.structured_content["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_lease_terminate_tools_run_the_service(world, monkeypatch):
    """The MCP, admin MCP and agent terminate tools call services.pm_leases.terminate_lease,
    which also clears the property's current lease. A direct status write would not."""
    from app.mcp.admin.agent_tools import leases as admin_leases
    from app.mcp.chatgpt import pm_lease_tools
    from tests.unit.mcp.conftest import SessionContext

    world.prop_a.current_lease_id = world.lease_a.id
    world.prop_a.current_tenant_id = world.tenant_a.id
    await world.db.flush()

    monkeypatch.setattr(pm_lease_tools, "AsyncSessionLocal", lambda: SessionContext(world.db))
    monkeypatch.setattr(pm_lease_tools, "_get_optional_user", AsyncMock(return_value=world.owner_a))
    await pm_lease_tools.owner_leases_terminate(
        lease_id=world.lease_a.id, termination_date="2026-11-30", reason="Moving out"
    )

    await world.db.refresh(world.lease_a)
    await world.db.refresh(world.prop_a)
    assert world.lease_a.status == LeaseStatus.terminated
    assert world.lease_a.termination_date == date(2026, 11, 30)
    assert world.lease_a.termination_reason == "Moving out"
    assert world.prop_a.current_lease_id is None
    assert world.prop_a.current_tenant_id is None

    # The admin MCP and the agent tool refuse a lease outside their scope.
    monkeypatch.setattr(admin_leases, "get_db", _yield_db(world.db))
    monkeypatch.setattr(admin_leases, "_get_user", AsyncMock(return_value=world.rm_a))
    outside = await admin_leases.agent_leases_terminate(lease_id=world.lease_b.id, reason="x")
    assert outside["ok"] is False
    refused = await owner_tools.agent_leases_terminate(
        _ctx(world.rm_a, "agent", world.db), lease_id=world.lease_b.id, reason="x"
    )
    assert refused["error"] is True
    await world.db.refresh(world.lease_b)
    assert world.lease_b.status == LeaseStatus.active
