from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.models.enums as enum_module
from app.mcp.apps_sdk import AuthRequiredError
from app.mcp.chatgpt.pm_lease_tools import owner_leases_terminate
from app.mcp.chatgpt.pm_rent_tools import (
    owner_rent_history,
    owner_rent_record_payment,
    owner_rent_status,
)


class _SessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _PaymentMethod(str, Enum):
    cash = "cash"
    bank_transfer = "bank_transfer"
    upi = "upi"
    cheque = "cheque"
    online = "online"


def _build_user():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=10,
        role="user",
        supabase_user_id="user-10",
        phone="+911111111111",
        full_name="Owner User",
        email=None,
        is_active=True,
        is_verified=True,
        agent_id=None,
        created_at=now,
        updated_at=now,
    )


def _build_charge(*, amount_due, amount_paid, status):
    return SimpleNamespace(
        id=1,
        lease_id=11,
        billing_month=date(2026, 2, 1),
        due_date=date(2026, 2, 5),
        amount_due=amount_due,
        amount_paid=amount_paid,
        status=status,
        late_fee_assessed=0,
    )


def _build_payment():
    """A real RentPayment row (unsaved), so the serializer reads the ORM columns."""
    from app.models.enums import PaymentMethod, RentPaymentStatus
    from app.models.pm_finance import RentPayment

    return RentPayment(
        id=5,
        charge_id=3,
        lease_id=2,
        property_id=4,
        owner_id=1,
        paid_at=datetime(2026, 2, 15, tzinfo=timezone.utc),
        amount_paid=1200,
        payment_method=PaymentMethod.upi,
        status=RentPaymentStatus.settled,
        reference="TXN-001",
        notes="partial payment",
        created_at=datetime.now(timezone.utc),
    )


def _content_text(result) -> str:
    content = result.content
    if isinstance(content, list) and content:
        block = content[0]
        return getattr(block, "text", str(block))
    return str(content)


@pytest.mark.asyncio
async def test_owner_leases_terminate_requires_authentication():
    db = AsyncMock()

    with (
        patch("app.mcp.chatgpt.pm_lease_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch(
            "app.mcp.chatgpt.pm_lease_tools._get_optional_user", new=AsyncMock(return_value=None)
        ),
    ):
        with pytest.raises(AuthRequiredError):
            await owner_leases_terminate(lease_id=1, termination_date="2026-03-15")


@pytest.mark.asyncio
async def test_owner_leases_terminate_invalid_date_returns_validation_error():
    db = AsyncMock()
    user = _build_user()

    with (
        patch("app.mcp.chatgpt.pm_lease_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch(
            "app.mcp.chatgpt.pm_lease_tools._get_optional_user", new=AsyncMock(return_value=user)
        ),
    ):
        result = await owner_leases_terminate(lease_id=1, termination_date="not-a-date")

    assert result.structured_content["code"] == "INVALID_DATE"
    assert "Invalid date format" in _content_text(result)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_leases_terminate_maps_not_found_errors():
    db = AsyncMock()
    user = _build_user()

    with (
        patch("app.mcp.chatgpt.pm_lease_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch(
            "app.mcp.chatgpt.pm_lease_tools._get_optional_user", new=AsyncMock(return_value=user)
        ),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch(
            "app.services.pm_leases.terminate_lease",
            new=AsyncMock(side_effect=Exception("lease not found")),
        ),
    ):
        result = await owner_leases_terminate(lease_id=99, termination_date="2026-03-15")

    assert result.structured_content["code"] == "NOT_FOUND"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_rent_record_payment_invalid_date_returns_error():
    db = AsyncMock()
    user = _build_user()

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch.object(enum_module, "PaymentMethod", _PaymentMethod, create=True),
    ):
        result = await owner_rent_record_payment(
            rent_charge_id=1,
            amount=1000,
            payment_date="bad-date",
            payment_method="upi",
        )

    assert result.structured_content["code"] == "INVALID_DATE"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_rent_record_payment_invalid_method_returns_allowed_values():
    db = AsyncMock()
    user = _build_user()

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch.object(enum_module, "PaymentMethod", _PaymentMethod, create=True),
    ):
        result = await owner_rent_record_payment(
            rent_charge_id=1,
            amount=1000,
            payment_date="2026-02-15",
            payment_method="crypto",
        )

    assert result.structured_content["code"] == "INVALID_METHOD"
    assert set(result.structured_content["valid_methods"]) == {
        "cash",
        "bank_transfer",
        "upi",
        "cheque",
        "online",
    }
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_rent_record_payment_maps_not_found_errors():
    db = AsyncMock()
    user = _build_user()

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch.object(enum_module, "PaymentMethod", _PaymentMethod, create=True),
        patch(
            "app.services.pm_rent.record_rent_payment",
            new=AsyncMock(side_effect=Exception("rent charge not found")),
        ),
    ):
        result = await owner_rent_record_payment(
            rent_charge_id=999,
            amount=1000,
            payment_date="2026-02-15",
            payment_method="upi",
        )

    assert result.structured_content["code"] == "NOT_FOUND"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_rent_record_payment_success_commits_and_serializes_payment():
    db = AsyncMock()
    user = _build_user()
    payment = _build_payment()
    mock_record = AsyncMock(return_value=payment)

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch.object(enum_module, "PaymentMethod", _PaymentMethod, create=True),
        patch("app.services.pm_rent.record_rent_payment", new=mock_record),
    ):
        result = await owner_rent_record_payment(
            rent_charge_id=3,
            amount=1200,
            payment_date="2026-02-15",
            payment_method="upi",
            transaction_id="TXN-001",
            notes="partial payment",
        )

    assert "success" not in result.structured_content
    assert result.structured_content["payment"]["charge_id"] == 3
    assert result.structured_content["payment"]["amount_paid"] == 1200.0
    assert result.structured_content["payment"]["paid_at"] == "2026-02-15T00:00:00Z"
    assert result.structured_content["payment"]["payment_method"] == "upi"
    assert result.structured_content["payment"]["reference"] == "TXN-001"
    db.commit.assert_awaited_once()
    assert mock_record.await_count == 1


@pytest.mark.asyncio
async def test_owner_rent_record_payment_failure_after_record_does_not_commit():
    """A failure while building the response rolls the write back. A retry cannot double-record."""
    db = AsyncMock()
    user = _build_user()
    payment = _build_payment()
    mock_record = AsyncMock(return_value=payment)

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm_rent.record_rent_payment", new=mock_record),
        patch(
            "app.mcp.chatgpt.pm_rent_tools.serialize_rent_payment",
            side_effect=RuntimeError("serializer broke"),
        ),
    ):
        result = await owner_rent_record_payment(
            rent_charge_id=3,
            amount=1200,
            payment_date="2026-02-15",
            payment_method="upi",
        )

    db.commit.assert_not_awaited()
    assert result.structured_content["error"] is True


@pytest.mark.asyncio
async def test_owner_rent_history_returns_items_with_real_payment_fields():
    db = AsyncMock()
    user = _build_user()
    mock_list = AsyncMock(return_value=([_build_payment()], None, None))

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm_rent.list_rent_payments", new=mock_list),
    ):
        result = await owner_rent_history(property_id=4)

    content = result.structured_content
    assert "payments" not in content
    assert content["items"][0]["charge_id"] == 3
    assert content["items"][0]["amount_paid"] == 1200.0
    assert content["items"][0]["reference"] == "TXN-001"
    assert content["total"] is None


def _page(items=(), totals=None):
    from app.services.pm.rent_due import RentChargePage

    return RentChargePage(
        items=list(items),
        next_payload=None,
        totals=totals
        or {"total_due": 0.0, "total_paid": 0.0, "overdue_count": 0, "charges_count": 0},
    )


@pytest.mark.asyncio
async def test_owner_rent_status_summary_all_current_when_no_outstanding_balance():
    db = AsyncMock()
    user = _build_user()
    mock_page = AsyncMock(return_value=_page())

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm.rent_due.list_rent_charge_page", new=mock_page),
    ):
        result = await owner_rent_status()

    assert _content_text(result) == "All rent is current. No outstanding balances."
    assert result.structured_content["totals"]["total_due"] == 0
    assert mock_page.await_args.kwargs["owner_ids"] == [user.id]
    assert mock_page.await_args.kwargs["unpaid_only"] is True


@pytest.mark.asyncio
async def test_owner_rent_status_summary_counts_overdue_charges_from_the_totals():
    db = AsyncMock()
    user = _build_user()
    totals = {"total_due": 1500.0, "total_paid": 500.0, "overdue_count": 1, "charges_count": 1}
    mock_page = AsyncMock(return_value=_page(totals=totals))

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm.rent_due.list_rent_charge_page", new=mock_page),
    ):
        result = await owner_rent_status()

    assert "1 overdue charges require attention" in _content_text(result)
    assert result.structured_content["totals"]["overdue_count"] == 1


@pytest.mark.asyncio
async def test_owner_rent_status_include_paid_drops_the_unpaid_filter():
    db = AsyncMock()
    user = _build_user()
    mock_page = AsyncMock(return_value=_page())

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm.rent_due.list_rent_charge_page", new=mock_page),
    ):
        await owner_rent_status(include_paid=True)

    assert mock_page.await_args.kwargs["unpaid_only"] is False
