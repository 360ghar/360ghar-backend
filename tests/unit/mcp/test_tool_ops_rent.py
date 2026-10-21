"""Unit tests for the MCP rent tool_ops history reader in ``app/mcp/tool_ops/rent.py``.

The DB session is mocked. Rent-due totals and cursors are covered by
tests/unit/mcp/test_rent_due_db.py (database-backed).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.mcp.tool_ops import rent as rent_tool_ops


def _all_result(rows):
    """Mock ``db.execute()`` result whose ``.all()`` yields ``rows`` (raw tuples)."""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


def _scalars_result(values):
    """Mock ``db.execute()`` result whose ``.scalars().all()`` yields ``values``."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _scalar_one_result(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


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
        property_id=1,
        amount_paid=amount,
        paid_at=datetime.fromisoformat(paid_at).replace(tzinfo=timezone.utc),
        payment_method=method,
        status="settled",
        reference=reference,
        notes=None,
        created_at=datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc),
    )


class TestGetRentHistory:
    async def test_returns_history_items_and_collected_total(self) -> None:
        db = AsyncMock()
        payments = [
            _make_payment(payment_id=1, lease_id=1, amount=25000),
            _make_payment(payment_id=2, lease_id=2, amount=15000),
        ]
        db.execute = AsyncMock(
            side_effect=[
                _all_result([(1,), (2,)]),  # lease ids
                _scalars_result(payments),  # one page of payments
                _scalar_one_result(40000),  # settled total over every payment
            ]
        )

        result = await rent_tool_ops.get_rent_history(db, tenant_user_id=10, limit=20)

        assert [item["id"] for item in result["items"]] == [1, 2]
        assert result["total"] is None
        assert result["total_collected"] == 40000.0
        assert result["has_more"] is False
        assert result["next_cursor"] is None
        assert "payments" not in result

    async def test_include_total_counts_every_payment(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _all_result([(1,)]),
                _scalars_result([_make_payment(payment_id=1)]),
                _scalar_one_result(7),  # count over every payment
                _scalar_one_result(7000),  # collected
            ]
        )

        result = await rent_tool_ops.get_rent_history(
            db, tenant_user_id=10, limit=20, include_total=True
        )

        assert result["total"] == 7
        assert result["total_collected"] == 7000.0

    async def test_empty_history(self) -> None:
        db = AsyncMock()
        # No leases for tenant → early return, single execute only
        db.execute = AsyncMock(return_value=_all_result([]))

        result = await rent_tool_ops.get_rent_history(db, tenant_user_id=10)

        assert result["items"] == []
        assert result["total_collected"] == 0.0
        assert result["has_more"] is False
        assert db.execute.await_count == 1

    async def test_pagination_returns_a_cursor_when_a_page_is_full(self) -> None:
        db = AsyncMock()
        # limit + 1 rows means another page exists.
        payments = [_make_payment(payment_id=i, amount=5000) for i in range(6)]
        db.execute = AsyncMock(
            side_effect=[
                _all_result([(1,)]),
                _scalars_result(payments),
                _scalar_one_result(25000),
            ]
        )

        result = await rent_tool_ops.get_rent_history(db, tenant_user_id=10, limit=5)

        assert result["has_more"] is True
        assert result["next_cursor"] is not None
        assert len(result["items"]) == 5
        assert result["total_collected"] == 25000.0
