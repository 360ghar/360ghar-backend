from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.mcp.chatgpt.pm_shared import (
    _format_lease_summary,
    _format_rent_summary,
    _serialize_lease,
    _serialize_rent_charge,
)


class _EnumLike:
    def __init__(self, value: str):
        self.value = value


def test_serialize_lease_uses_tenant_user_relation_not_legacy_tenant_field():
    tenant_user = SimpleNamespace(
        id=101,
        full_name="Tenant User",
        phone="+911234567890",
        email="tenant@example.com",
    )
    legacy_tenant = SimpleNamespace(
        id=999,
        full_name="Legacy Tenant",
        phone="+910000000000",
        email="legacy@example.com",
    )

    lease = SimpleNamespace(
        id=1,
        property_id=2,
        property=SimpleNamespace(
            id=2,
            title="Flat 2B",
            locality="Sector 1",
            city="Noida",
            full_address="Sector 1, Noida",
            images=[SimpleNamespace(image_url="https://example.com/home.jpg")],
        ),
        owner_id=50,
        tenant_user_id=tenant_user.id,
        tenant_user=tenant_user,
        tenant=legacy_tenant,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        monthly_rent=22000,
        security_deposit=44000,
        payment_due_day=5,
        status=_EnumLike("active"),
        rent_paid_through=date(2026, 1, 31),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    owner = SimpleNamespace(id=50, role="user")
    data = _serialize_lease(lease, owner)

    assert data["tenant"] == {
        "id": 101,
        "display_name": "Tenant User",
        "avatar_url": None,
        "phone": "+911234567890",
        "email": "tenant@example.com",
    }
    assert data["property"]["main_image_url"] == "https://example.com/home.jpg"

    # A caller who is not the owner, an admin or the tenant gets a PublicUserRef only.
    for stranger in (
        SimpleNamespace(id=60, role="agent"),  # an assigned agent is not the owner
        SimpleNamespace(id=61, role="user"),
        None,  # anonymous
    ):
        assert _serialize_lease(lease, stranger)["tenant"] == {
            "id": 101,
            "display_name": "Tenant User",
            "avatar_url": None,
        }
    # Admins and the tenant themself keep the contact fields.
    for allowed in (SimpleNamespace(id=1, role="admin"), SimpleNamespace(id=101, role="user")):
        assert _serialize_lease(lease, allowed)["tenant"]["phone"] == "+911234567890"


def test_serialize_rent_charge_computes_balance_and_late_fee_defaults():
    charge = SimpleNamespace(
        id=10,
        lease_id=20,
        billing_month=date(2026, 2, 1),
        due_date=date(2026, 2, 5),
        amount_due=2000,
        status=_EnumLike("overdue"),
        late_fee_assessed=150,
    )

    serialized = _serialize_rent_charge(charge, amount_paid=500)

    # amount_due is rent plus the assessed late fee, as in list_rent_charges.
    assert serialized["amount_due"] == 2150.0
    assert serialized["amount_paid"] == 500.0
    assert serialized["balance"] == 1650.0
    assert serialized["late_fee"] == 150.0
    assert serialized["status"] == "overdue"


def test_serialize_rent_charge_handles_none_amount_due():
    charge = SimpleNamespace(
        id=10,
        lease_id=20,
        billing_month=None,
        due_date=None,
        amount_due=None,
        status="pending",
        late_fee_assessed=None,
    )

    serialized = _serialize_rent_charge(charge, amount_paid=999)

    assert serialized["amount_due"] == 0
    assert serialized["amount_paid"] == 999.0
    assert serialized["balance"] == 0
    assert serialized["late_fee"] == 0
    assert serialized["status"] == "pending"


def test_serialize_rent_payment_reads_orm_fields():
    """The serializer reads the real RentPayment columns, not guessed names."""
    from app.mcp.utils import serialize_rent_payment
    from app.models.enums import PaymentMethod, RentPaymentStatus
    from app.models.pm_finance import RentPayment

    payment = RentPayment(
        id=50,
        charge_id=10,
        lease_id=3,
        property_id=4,
        owner_id=1,
        paid_at=datetime(2026, 2, 15, 9, 30, tzinfo=timezone.utc),
        amount_paid=1200.456,
        payment_method=PaymentMethod.upi,
        status=RentPaymentStatus.settled,
        reference="TXN-42",
        notes="on time",
        created_at=datetime(2026, 2, 15, tzinfo=timezone.utc),
    )

    serialized = serialize_rent_payment(payment)

    assert serialized["charge_id"] == 10
    assert serialized["amount_paid"] == 1200.46
    assert serialized["paid_at"] == "2026-02-15T09:30:00Z"
    assert serialized["payment_method"] == "upi"
    assert serialized["status"] == "settled"
    assert serialized["reference"] == "TXN-42"
    assert serialized["notes"] == "on time"


def test_format_lease_summary_handles_rent_not_set():
    summary = _format_lease_summary(
        {
            "property": {"title": "Flat 101"},
            "tenant": {"display_name": "Tenant A"},
            "monthly_rent": 0,
            "status": "active",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        }
    )

    assert "Flat 101" in summary
    assert "Tenant A" in summary
    assert "rent not set" in summary


def test_format_lease_summary_handles_an_unloaded_property_and_tenant():
    summary = _format_lease_summary(
        {
            "property": None,
            "tenant": None,
            "monthly_rent": 12000,
            "status": "active",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        }
    )

    assert summary.startswith("Lease for property with tenant.")


def test_serialize_rent_charge_adds_the_pending_late_fee():
    from decimal import Decimal

    charge = SimpleNamespace(
        id=10,
        lease_id=20,
        billing_month=date(2026, 2, 1),
        due_date=date(2026, 2, 5),
        amount_due=2000,
        status=_EnumLike("overdue"),
        late_fee_assessed=0,
    )

    serialized = _serialize_rent_charge(charge, amount_paid=500, pending_fee=Decimal("100.00"))

    assert serialized["amount_due"] == 2100.0
    assert serialized["late_fee"] == 100.0
    assert serialized["balance"] == 1600.0


def test_format_rent_summary_covers_zero_due_and_overdue_paths():
    current_summary = _format_rent_summary(
        [], {"total_due": 0, "total_paid": 1000, "overdue_count": 0}
    )
    overdue_summary = _format_rent_summary(
        [],
        {"total_due": 3500, "total_paid": 500, "overdue_count": 2},
    )

    assert current_summary == "All rent is current. No outstanding balances."
    assert "2 overdue charges require attention" in overdue_summary
