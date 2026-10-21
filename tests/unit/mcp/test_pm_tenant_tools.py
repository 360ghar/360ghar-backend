"""Unit tests for the ChatGPT/AppsSDK-format PM tenant tools.

Scope note
----------
``app/mcp/chatgpt/pm_tenant_tools.py`` only registers ONE ChatGPT-format
tenant tool: ``tenant_rent_dues``. The other tenant tools referenced in the
platform (``tenant_lease_current``, ``tenant_rent_history``,
``tenant_maintenance_create``) live in ``app/mcp/user/tenant.py`` and return
plain ``MCPResponse`` dicts (already covered by ``test_user_tools.py``);
they do NOT have ChatGPT/AppsSDK-format equivalents that return
``AppsSDKToolResult``. This file therefore covers the single genuine
ChatGPT-format PM tenant tool.

``tenant_rent_dues`` returns an ``AppsSDKToolResult`` (via
``format_chatgpt_response``) and raises ``AuthRequiredError`` when the caller
is unauthenticated. These tests mock ``AsyncSessionLocal`` (with a
``SessionContext``), ``_get_optional_user``, ``get_widget_for_tool``, and the
``db.execute`` results to verify each branch.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.apps_sdk import AppsSDKToolResult, AuthRequiredError
from app.mcp.chatgpt.pm_tenant_tools import tenant_rent_dues
from tests.unit.mcp.conftest import SessionContext, make_rent_charge, make_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WIDGET_URI = "ui://widget/tenantrentwidget.html"


def _fetchall_result(rows):
    """Mock ``db.execute()`` result exposing sync ``fetchall()``."""
    result = MagicMock()
    result.fetchall = MagicMock(return_value=rows)
    return result


def _charge_rows_result(charges):
    """Mock ``db.execute()`` result for the charge query: ``.all()`` gives (charge, lease) rows."""
    lease = SimpleNamespace(grace_period_days=5, late_fee_amount=None, late_fee_percentage=None)
    result = MagicMock()
    result.all = MagicMock(return_value=[(charge, lease) for charge in charges])
    return result


@pytest.fixture(autouse=True)
def _business_day_is_within_grace():
    """The fixtures use June 2026 due dates. Freeze the business day inside the grace period."""
    with patch("app.services.pm.rent_rules.business_today", return_value=date(2026, 6, 6)):
        yield


def _content_text(result) -> str:
    """Extract narrative text from an AppsSDKToolResult."""
    content = result.content
    if isinstance(content, list) and content:
        block = content[0]
        return getattr(block, "text", str(block))
    return str(content)


# ---------------------------------------------------------------------------
# tenant_rent_dues
# ---------------------------------------------------------------------------


class TestPMTenantRentDues:
    async def test_requires_auth(self) -> None:
        db = AsyncMock()

        with (
            patch(
                "app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)
            ),
            patch(
                "app.mcp.chatgpt.pm_tenant_tools._get_optional_user",
                new=AsyncMock(return_value=None),
            ),
            patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
        ):
            with pytest.raises(AuthRequiredError):
                await tenant_rent_dues()

        # Auth path bails out before querying leases/charges.
        db.execute.assert_not_awaited()

    async def test_returns_dues(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _fetchall_result([(11,)]),
                _charge_rows_result(
                    [
                        make_rent_charge(
                            charge_id=1,
                            lease_id=11,
                            amount_due=25000,
                            amount_paid=0,
                            status="pending",
                        ),
                        make_rent_charge(
                            charge_id=2,
                            lease_id=11,
                            amount_due=25000,
                            amount_paid=10000,
                            status="partial",
                        ),
                    ]
                ),
                # Settled totals per charge (RentPayment rows): charge 1 unpaid, charge 2 paid 10000.
                SimpleNamespace(all=lambda: [(2, 10000.0)]),
            ]
        )
        user = make_user(user_id=10)

        with (
            patch(
                "app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)
            ),
            patch(
                "app.mcp.chatgpt.pm_tenant_tools._get_optional_user",
                new=AsyncMock(return_value=user),
            ),
            patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
        ):
            result = await tenant_rent_dues()

        assert isinstance(result, AppsSDKToolResult)
        assert result.is_error is False
        data = result.structured_content
        assert data["total_due"] == 40000  # (25000 - 0) + (25000 - 10000)
        assert data["overdue_count"] == 0
        assert len(data["charges"]) == 2
        # Widget URI is propagated into _meta for the host.
        assert result.meta["ui"]["resourceUri"] == WIDGET_URI
        assert "₹40,000" in _content_text(result)

    async def test_no_dues(self) -> None:
        # Tenant has a lease but no outstanding charges -> total_due is 0.
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _fetchall_result([(11,)]),
                _charge_rows_result([]),
            ]
        )
        user = make_user(user_id=10)

        with (
            patch(
                "app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)
            ),
            patch(
                "app.mcp.chatgpt.pm_tenant_tools._get_optional_user",
                new=AsyncMock(return_value=user),
            ),
            patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
        ):
            result = await tenant_rent_dues()

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content["total_due"] == 0
        assert result.structured_content["charges"] == []
        assert result.structured_content["overdue_count"] == 0
        assert _content_text(result) == "Your rent is up to date! No outstanding payments."

    async def test_with_overdue(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _fetchall_result([(11,)]),
                _charge_rows_result(
                    [
                        make_rent_charge(
                            charge_id=3,
                            lease_id=11,
                            amount_due=25000,
                            amount_paid=0,
                            status="overdue",
                        ),
                        make_rent_charge(
                            charge_id=4,
                            lease_id=11,
                            amount_due=25000,
                            amount_paid=5000,
                            status="pending",
                        ),
                    ]
                ),
                SimpleNamespace(all=lambda: [(4, 5000.0)]),
            ]
        )
        user = make_user(user_id=10)

        with (
            patch(
                "app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)
            ),
            patch(
                "app.mcp.chatgpt.pm_tenant_tools._get_optional_user",
                new=AsyncMock(return_value=user),
            ),
            patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
        ):
            result = await tenant_rent_dues()

        assert isinstance(result, AppsSDKToolResult)
        data = result.structured_content
        assert data["total_due"] == 45000  # 25000 + 20000
        assert data["overdue_count"] == 1
        text = _content_text(result)
        assert "₹45,000" in text
        assert "1 payment(s) are overdue" in text

    async def test_no_leases_returns_empty(self) -> None:
        # Tenant has no leases at all -> early-return branch.
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_fetchall_result([])])
        user = make_user(user_id=10)

        with (
            patch(
                "app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)
            ),
            patch(
                "app.mcp.chatgpt.pm_tenant_tools._get_optional_user",
                new=AsyncMock(return_value=user),
            ),
            patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
        ):
            result = await tenant_rent_dues()

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content == {"charges": [], "total_due": 0}
        assert _content_text(result) == "You don't have any active leases."
        # Only the lease-id query ran; the charges query is skipped.
        assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_tenant_rent_dues_serializes_a_real_rent_charge_row() -> None:
    """One real RentCharge (ORM) row; settled payments come from RentPayment totals."""
    from app.models.enums import RentChargeStatus
    from app.models.pm_finance import RentCharge

    db = AsyncMock()
    charge = RentCharge(
        id=7,
        lease_id=11,
        property_id=5,
        owner_id=10,
        tenant_user_id=10,
        billing_month=date(2026, 10, 1),
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        due_date=date(2026, 10, 5),
        amount_due=25000,
        late_fee_assessed=500,
        status=RentChargeStatus.partial,
    )
    db.execute = AsyncMock(
        side_effect=[
            _fetchall_result([(11,)]),
            _charge_rows_result([charge]),
            SimpleNamespace(all=lambda: [(7, 10000.0)]),
        ]
    )
    user = make_user(user_id=10)

    with (
        patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
        patch(
            "app.mcp.chatgpt.pm_tenant_tools._get_optional_user", new=AsyncMock(return_value=user)
        ),
        patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
    ):
        result = await tenant_rent_dues()

    assert result.is_error is False
    data = result.structured_content
    row = data["charges"][0]
    assert row["amount_due"] == 25500.0  # rent plus the assessed late fee
    assert row["amount_paid"] == 10000.0
    assert row["balance"] == 15500.0
    assert data["total_due"] == 15500.0


@pytest.mark.asyncio
async def test_pending_charge_past_grace_reads_as_overdue() -> None:
    """A pending charge past its grace period is overdue, as in the owner and agent tools (be-pm-21)."""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _fetchall_result([(11,)]),
            _charge_rows_result([make_rent_charge(charge_id=1, lease_id=11, status="pending")]),
            SimpleNamespace(all=lambda: []),
        ]
    )
    user = make_user(user_id=10)

    with (
        patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
        patch(
            "app.mcp.chatgpt.pm_tenant_tools._get_optional_user", new=AsyncMock(return_value=user)
        ),
        patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
        patch("app.services.pm.rent_rules.business_today", return_value=date(2026, 6, 20)),
    ):
        result = await tenant_rent_dues()

    data = result.structured_content
    assert data["charges"][0]["status"] == "overdue"
    assert data["overdue_count"] == 1


async def test_three_charges_of_500_10_total_exactly_1500_30() -> None:
    """Finding be-pm-14 (rest of the rent path): the dues total is a Decimal sum, not a float sum.

    Float addition gives 1500.3000000000002 for three balances of 500.10.
    """
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _fetchall_result([(11,)]),
            _charge_rows_result(
                [
                    make_rent_charge(charge_id=1, lease_id=11, amount_due=500.10, status="pending"),
                    make_rent_charge(charge_id=2, lease_id=11, amount_due=500.10, status="pending"),
                    make_rent_charge(charge_id=3, lease_id=11, amount_due=500.10, status="pending"),
                ]
            ),
            # No settled payments yet.
            SimpleNamespace(all=lambda: []),
        ]
    )
    user = make_user(user_id=10)

    with (
        patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
        patch(
            "app.mcp.chatgpt.pm_tenant_tools._get_optional_user",
            new=AsyncMock(return_value=user),
        ),
        patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
    ):
        result = await tenant_rent_dues()

    assert isinstance(result, AppsSDKToolResult)
    assert result.structured_content["total_due"] == 1500.3
    assert [c["balance"] for c in result.structured_content["charges"]] == [500.1, 500.1, 500.1]
