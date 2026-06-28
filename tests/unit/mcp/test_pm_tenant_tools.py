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


def _scalars_result(items):
    """Mock ``db.execute()`` result exposing ``scalars().all()``."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=items)
    result.scalars = MagicMock(return_value=scalars_mock)
    return result


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
            patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
            patch("app.mcp.chatgpt.pm_tenant_tools._get_optional_user", new=AsyncMock(return_value=None)),
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
                _scalars_result(
                    [
                        make_rent_charge(charge_id=1, lease_id=11, amount_due=25000, amount_paid=0, status="pending"),
                        make_rent_charge(charge_id=2, lease_id=11, amount_due=25000, amount_paid=10000, status="partial"),
                    ]
                ),
            ]
        )
        user = make_user(user_id=10)

        with (
            patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
            patch("app.mcp.chatgpt.pm_tenant_tools._get_optional_user", new=AsyncMock(return_value=user)),
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
                _scalars_result([]),
            ]
        )
        user = make_user(user_id=10)

        with (
            patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
            patch("app.mcp.chatgpt.pm_tenant_tools._get_optional_user", new=AsyncMock(return_value=user)),
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
                _scalars_result(
                    [
                        make_rent_charge(charge_id=3, lease_id=11, amount_due=25000, amount_paid=0, status="overdue"),
                        make_rent_charge(charge_id=4, lease_id=11, amount_due=25000, amount_paid=5000, status="pending"),
                    ]
                ),
            ]
        )
        user = make_user(user_id=10)

        with (
            patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
            patch("app.mcp.chatgpt.pm_tenant_tools._get_optional_user", new=AsyncMock(return_value=user)),
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
            patch("app.mcp.chatgpt.pm_tenant_tools.AsyncSessionLocal", return_value=SessionContext(db)),
            patch("app.mcp.chatgpt.pm_tenant_tools._get_optional_user", new=AsyncMock(return_value=user)),
            patch("app.mcp.chatgpt.pm_tenant_tools.get_widget_for_tool", return_value=WIDGET_URI),
        ):
            result = await tenant_rent_dues()

        assert isinstance(result, AppsSDKToolResult)
        assert result.structured_content == {"charges": [], "total_due": 0}
        assert _content_text(result) == "You don't have any active leases."
        # Only the lease-id query ran; the charges query is skipped.
        assert db.execute.await_count == 1
