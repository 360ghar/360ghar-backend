"""Unit tests for MCP rent tool_ops layer.

These tests exercise the shared rent tool_ops functions in
``app/mcp/tool_ops/rent.py`` directly, mocking the DB session and the
pm_authz helper to verify that each function:
- Computes rent-due items (overdue flags, due totals, pagination) from leases
- Records payments with method validation and lease-access checks
- Aggregates rent history for a tenant
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import NotFoundException
from app.mcp.tool_ops import rent as rent_tool_ops
from tests.unit.mcp.conftest import make_lease, make_user

# Fixed "today" used to make overdue/due math deterministic. We patch the
# module-level ``utc_now`` import in the rent tool_ops module to return this.
FROZEN_NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value):
    """Mock ``db.execute()`` result with sync ``scalar_one_or_none()``."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _scalars_result(values):
    """Mock ``db.execute()`` result whose ``.scalars().all()`` yields ``values``."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _all_result(rows):
    """Mock ``db.execute()`` result whose ``.all()`` yields ``rows`` (raw tuples)."""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


def _make_lease_for_rent(
    lease_id: int = 1,
    property_id: int = 1,
    owner_id: int = 10,
    tenant_user_id: int = 10,
    monthly_rent: float = 25000,
    payment_due_day: int = 1,
    grace_period_days: int = 5,
) -> SimpleNamespace:
    """Create a mock lease with the attributes read by ``compute_rent_due_items``."""
    lease = make_lease(
        lease_id=lease_id,
        property_id=property_id,
        tenant_user_id=tenant_user_id,
        monthly_rent=monthly_rent,
    )
    lease.owner_id = owner_id
    lease.payment_due_day = payment_due_day
    lease.grace_period_days = grace_period_days
    return lease


def _make_payment(
    payment_id: int = 1,
    lease_id: int = 1,
    amount: float = 25000,
    method: str = "upi",
    paid_at: str = "2026-06-05T10:00:00",
    reference: str = "TXN123",
    charge_id: int = 1,
) -> SimpleNamespace:
    """Create a mock RentPayment row compatible with the history serializer."""
    return SimpleNamespace(
        id=payment_id,
        lease_id=lease_id,
        charge_id=charge_id,
        amount_paid=amount,
        paid_at=datetime.fromisoformat(paid_at),
        payment_method=method,
        reference=reference,
        created_at=datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# compute_rent_due_items
# ---------------------------------------------------------------------------


class TestComputeRentDueItems:
    async def test_returns_due_items(self) -> None:
        db = AsyncMock()
        # lease_a: due day 1 → overdue on 2026-06-20 (grace end 06-06)
        lease_a = _make_lease_for_rent(
            lease_id=1, property_id=1, monthly_rent=25000, payment_due_day=1
        )
        # lease_b: due day 25 → not yet due on 2026-06-20
        lease_b = _make_lease_for_rent(
            lease_id=2, property_id=2, monthly_rent=15000, payment_due_day=25
        )
        db.execute = AsyncMock(
            side_effect=[
                _scalars_result([lease_a, lease_b]),
                _all_result([(1, "Green Villa"), (2, "Blue House")]),
            ]
        )

        with patch.object(rent_tool_ops, "utc_now", return_value=FROZEN_NOW):
            result = await rent_tool_ops.compute_rent_due_items(db, owner_ids=[10])

        assert len(result["items"]) == 2
        assert result["overdue_count"] == 1  # only lease_a
        # Only lease_a is due (is_due True) → total_due = 25000
        assert result["total_due"] == 25000.0
        assert result["has_more"] is False

    async def test_no_due_items(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        with patch.object(rent_tool_ops, "utc_now", return_value=FROZEN_NOW):
            result = await rent_tool_ops.compute_rent_due_items(db)

        assert result["items"] == []
        assert result["total_due"] == 0
        assert result["overdue_count"] == 0
        assert result["has_more"] is False
        assert result["next_cursor"] is None
        # No property titles query when there are no leases
        assert db.execute.await_count == 1

    async def test_overdue_only_filter(self) -> None:
        db = AsyncMock()
        lease_overdue = _make_lease_for_rent(
            lease_id=1, property_id=1, monthly_rent=25000, payment_due_day=1
        )
        lease_current = _make_lease_for_rent(
            lease_id=2, property_id=2, monthly_rent=15000, payment_due_day=25
        )
        db.execute = AsyncMock(
            side_effect=[
                _scalars_result([lease_overdue, lease_current]),
                _all_result([(1, "A"), (2, "B")]),
            ]
        )

        with patch.object(rent_tool_ops, "utc_now", return_value=FROZEN_NOW):
            result = await rent_tool_ops.compute_rent_due_items(db, overdue_only=True)

        assert len(result["items"]) == 1
        assert result["items"][0]["lease_id"] == 1
        assert result["items"][0]["is_overdue"] is True
        assert result["items"][0]["property_title"] == "A"


# ---------------------------------------------------------------------------
# record_rent_payment
# ---------------------------------------------------------------------------


class TestRecordRentPayment:
    async def test_record_success(self) -> None:
        db = AsyncMock()
        actor = make_user()
        lease = _make_lease_for_rent(lease_id=5, property_id=3, owner_id=10)

        async def _refresh(obj, *args, **kwargs):
            obj.id = 99

        db.refresh = AsyncMock(side_effect=_refresh)
        # db.add() is synchronous on AsyncSession; override the AsyncMock attr
        db.add = MagicMock()

        with patch.object(
            rent_tool_ops, "assert_can_access_lease", AsyncMock(return_value=lease)
        ):
            result = await rent_tool_ops.record_rent_payment(
                db,
                actor=actor,
                lease_id=5,
                amount=25000,
                payment_date="2026-06-05T10:00:00",
                payment_method="upi",
                transaction_reference="TXN999",
            )

        assert result["message"] == "Payment recorded successfully"
        assert result["payment"]["id"] == 99
        assert result["payment"]["amount"] == 25000.0
        assert result["payment"]["payment_method"] == "upi"
        assert result["payment"]["reference"] == "TXN999"
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_lease_not_found(self) -> None:
        db = AsyncMock()
        actor = make_user()

        with patch.object(
            rent_tool_ops,
            "assert_can_access_lease",
            AsyncMock(side_effect=NotFoundException(detail="Lease not found")),
        ):
            result = await rent_tool_ops.record_rent_payment(
                db,
                actor=actor,
                lease_id=999,
                amount=25000,
                payment_date="2026-06-05",
                payment_method="upi",
            )

        assert result["error"] is True
        assert "not found" in result["message"].lower()
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_invalid_payment_method(self) -> None:
        db = AsyncMock()
        actor = make_user()

        result = await rent_tool_ops.record_rent_payment(
            db,
            actor=actor,
            lease_id=5,
            amount=25000,
            payment_date="2026-06-05",
            payment_method="bitcoin",  # not in valid set
        )

        assert result["error"] is True
        assert "Invalid payment method" in result["message"]
        # Validation happens before lease access / DB writes
        db.add.assert_not_called()
        db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_rent_history
# ---------------------------------------------------------------------------


class TestGetRentHistory:
    async def test_returns_history(self) -> None:
        db = AsyncMock()
        payments = [
            _make_payment(payment_id=1, lease_id=1, amount=25000),
            _make_payment(payment_id=2, lease_id=2, amount=15000),
        ]
        db.execute = AsyncMock(
            side_effect=[
                _all_result([(1,), (2,)]),  # lease ids
                _scalars_result(payments),  # payments
            ]
        )

        result = await rent_tool_ops.get_rent_history(db, tenant_user_id=10, limit=20)

        assert result["total"] == 2
        assert len(result["payments"]) == 2
        assert result["total_collected"] == 40000.0
        assert result["has_more"] is False
        assert result["next_cursor"] is None

    async def test_empty_history(self) -> None:
        db = AsyncMock()
        # No leases for tenant → early return, single execute only
        db.execute = AsyncMock(return_value=_all_result([]))

        result = await rent_tool_ops.get_rent_history(db, tenant_user_id=10)

        assert result["payments"] == []
        assert result["total"] == 0
        assert result["total_collected"] == 0
        assert result["has_more"] is False
        assert db.execute.await_count == 1

    async def test_pagination(self) -> None:
        db = AsyncMock()
        payments = [_make_payment(payment_id=i, amount=5000) for i in range(5)]
        db.execute = AsyncMock(
            side_effect=[
                _all_result([(1,)]),
                _scalars_result(payments),
            ]
        )

        result = await rent_tool_ops.get_rent_history(db, tenant_user_id=10, limit=5)

        assert result["has_more"] is True
        assert result["next_cursor"] is not None
        assert len(result["payments"]) == 5
        assert result["total_collected"] == 25000.0
