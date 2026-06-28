from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.models.enums as enum_module
from app.mcp.apps_sdk import AuthRequiredError
from app.mcp.chatgpt.pm_lease_tools import owner_leases_terminate
from app.mcp.chatgpt.pm_rent_tools import owner_rent_record_payment, owner_rent_status
from app.models.enums import RentChargeStatus


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
        late_fee=0,
    )


def _build_payment():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=5,
        rent_charge_id=3,
        amount=1200,
        payment_date=date(2026, 2, 15),
        payment_method=SimpleNamespace(value="upi"),
        transaction_id="TXN-001",
        notes="partial payment",
        created_at=now,
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
        patch("app.mcp.chatgpt.pm_lease_tools._get_optional_user", new=AsyncMock(return_value=None)),
    ):
        with pytest.raises(AuthRequiredError):
            await owner_leases_terminate(lease_id=1, termination_date="2026-03-15")


@pytest.mark.asyncio
async def test_owner_leases_terminate_invalid_date_returns_validation_error():
    db = AsyncMock()
    user = _build_user()

    with (
        patch("app.mcp.chatgpt.pm_lease_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_lease_tools._get_optional_user", new=AsyncMock(return_value=user)),
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
        patch("app.mcp.chatgpt.pm_lease_tools._get_optional_user", new=AsyncMock(return_value=user)),
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

    assert result.structured_content["success"] is True
    assert result.structured_content["payment"]["rent_charge_id"] == 3
    assert result.structured_content["payment"]["payment_method"] == "upi"
    db.commit.assert_awaited_once()
    assert mock_record.await_count == 1


@pytest.mark.asyncio
async def test_owner_rent_status_summary_all_current_when_no_outstanding_balance():
    db = AsyncMock()
    user = _build_user()

    # No unpaid charges returned for any status
    mock_list = AsyncMock(return_value=([], None, None))

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm_rent.list_rent_charges", new=mock_list),
    ):
        result = await owner_rent_status()

    assert _content_text(result) == "All rent is current. No outstanding balances."
    assert result.structured_content["totals"]["total_due"] == 0
    # list_rent_charges is called once per unpaid status
    assert mock_list.await_count == 3
    called_statuses = [c.kwargs["status"] for c in mock_list.await_args_list]
    assert called_statuses == [RentChargeStatus.pending, RentChargeStatus.partial, RentChargeStatus.overdue]


@pytest.mark.asyncio
async def test_owner_rent_status_includes_overdue_counts_in_summary():
    db = AsyncMock()
    user = _build_user()
    overdue_charge = _build_charge(amount_due=2000, amount_paid=500, status="overdue")

    async def _list_by_status(*args, **kwargs):
        status = kwargs.get("status")
        if status == RentChargeStatus.overdue:
            return ([overdue_charge], None, None)
        return ([], None, None)

    mock_list = AsyncMock(side_effect=_list_by_status)

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm_rent.list_rent_charges", new=mock_list),
    ):
        result = await owner_rent_status()

    assert "1 overdue charges require attention" in _content_text(result)
    assert result.structured_content["totals"]["overdue_count"] == 1
    # list_rent_charges is called once per unpaid status
    assert mock_list.await_count == 3


@pytest.mark.asyncio
async def test_owner_rent_status_include_paid_disables_status_filter():
    db = AsyncMock()
    user = _build_user()
    mock_list = AsyncMock(return_value=([], None, None))

    with (
        patch("app.mcp.chatgpt.pm_rent_tools.AsyncSessionLocal", return_value=_SessionContext(db)),
        patch("app.mcp.chatgpt.pm_rent_tools._get_optional_user", new=AsyncMock(return_value=user)),
        patch("app.schemas.user.User.model_validate", return_value=user),
        patch("app.services.pm_rent.list_rent_charges", new=mock_list),
    ):
        await owner_rent_status(include_paid=True)

    assert mock_list.await_args.kwargs["status"] is None
