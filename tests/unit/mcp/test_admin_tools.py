"""Tests for MCP admin/agent tools (properties, leases, rent, maintenance, bookings, dashboard)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    InsufficientPermissionsError,
    NotFoundException,
    PropertyNotFoundException,
)
from app.mcp.admin.agent_tools import (
    bookings as bookings_tools,
)
from app.mcp.admin.agent_tools import (
    dashboard as dashboard_tools,
)
from app.mcp.admin.agent_tools import (
    leases as leases_tools,
)
from app.mcp.admin.agent_tools import (
    maintenance as maintenance_tools,
)
from app.mcp.admin.agent_tools import (
    properties as properties_tools,
)
from app.mcp.admin.agent_tools import (
    rent as rent_tools,
)
from app.mcp.apps_sdk import AuthRequiredError
from app.mcp.errors import MCPErrorCode
from app.mcp.tool_ops import TOOL_OPS_FORBIDDEN, TOOL_OPS_NOT_FOUND
from app.models.enums import PaymentMethod
from app.schemas.pagination import encode_cursor, offset_payload
from tests.unit.mcp.conftest import (
    async_gen_db,
    make_agent,
    make_lease,
    make_maintenance_request,
    make_property,
    make_user,
    raise_auth_required,
)

# Re-export to satisfy static analyzers that flags unused imports;
# the constants document the expected error-code contract for tool_ops.
_ = (TOOL_OPS_NOT_FOUND, TOOL_OPS_FORBIDDEN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _execute_result(*, scalar=None, scalars_all=None):
    """Build a MagicMock matching the SQLAlchemy Result interface."""
    result = MagicMock()
    if scalar is not None:
        result.scalar.return_value = scalar
    if scalars_all is not None:
        result.scalars.return_value.all.return_value = scalars_all
    return result


# ===========================================================================
# Properties
# ===========================================================================


class TestAgentPropertiesList:
    @pytest.fixture(autouse=True)
    def _lease_enrichment(self, monkeypatch):
        """Lease enrichment and portfolio stats have their own tests in tool_ops."""

        async def fake_enrich(db, rows):
            return [properties_tools.serialize_property_basic(p) for p in rows], {}

        monkeypatch.setattr(properties_tools, "enrich_properties_with_lease_info", fake_enrich)
        monkeypatch.setattr(
            properties_tools,
            "compute_portfolio_stats",
            AsyncMock(return_value={"total_properties": 0}),
        )

    """Tests for ``agent_properties_list``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(properties_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await properties_tools.agent_properties_list()

    @pytest.mark.asyncio
    async def test_requires_agent_role(self) -> None:
        db = AsyncMock()
        user = make_user(role="user")
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=user)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=False),
        ):
            result = await properties_tools.agent_properties_list()
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INSUFFICIENT_PERMISSIONS.value

    @pytest.mark.asyncio
    async def test_returns_properties(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        prop = make_property(property_id=1, title="Sunset Villa")
        mock_list = AsyncMock(return_value=([prop], None, 1))
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.list_managed_properties", new=mock_list),
            patch.object(properties_tools, "owner_scope", new=AsyncMock(return_value=None)),
            patch.object(
                properties_tools,
                "serialize_property_basic",
                return_value={"id": 1, "title": "Sunset Villa"},
            ),
        ):
            result = await properties_tools.agent_properties_list(include_total=True)
        assert result["ok"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["items"][0]["id"] == 1
        assert result["data"]["has_more"] is False
        assert mock_list.await_args.kwargs["with_total"] is True

    @pytest.mark.asyncio
    async def test_filter_by_owner(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        mock_list = AsyncMock(return_value=([], None, 0))
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.list_managed_properties", new=mock_list),
        ):
            await properties_tools.agent_properties_list(owner_id=42)
        assert mock_list.call_args.kwargs["owner_id"] == 42

    @pytest.mark.asyncio
    async def test_pagination(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        next_payload = {"created_at": "2026-01-01", "id": 5}
        mock_list = AsyncMock(return_value=([make_property()], next_payload, 100))
        valid_cursor = encode_cursor(offset_payload(10))
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.list_managed_properties", new=mock_list),
            patch.object(properties_tools, "owner_scope", new=AsyncMock(return_value=None)),
            patch.object(properties_tools, "serialize_property_basic", return_value={"id": 1}),
        ):
            result = await properties_tools.agent_properties_list(cursor=valid_cursor, limit=10)
        assert result["data"]["limit"] == 10
        assert result["data"]["has_more"] is True
        assert result["data"]["next_cursor"] is not None
        assert mock_list.call_args.kwargs["limit"] == 10


class TestAgentPropertiesGet:
    """Tests for ``agent_properties_get``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(properties_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await properties_tools.agent_properties_get(property_id=1)

    @pytest.mark.asyncio
    async def test_get_existing_property(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        prop = make_property(property_id=7, title="Green Acres")
        mock_detail = AsyncMock(return_value={"property": prop, "active_lease": None})
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.get_managed_property_detail", new=mock_detail),
            patch.object(properties_tools, "attach_owner_agents", new=AsyncMock()),
            patch("app.services.user.get_user_by_id", new=AsyncMock(return_value=None)),
            patch.object(
                properties_tools,
                "serialize_property_full",
                return_value={"id": 7, "title": "Green Acres"},
            ),
        ):
            result = await properties_tools.agent_properties_get(property_id=7)
        assert result["ok"] is True
        assert result["data"]["property"]["id"] == 7
        assert result["data"]["active_lease"] is None

    @pytest.mark.asyncio
    async def test_nonexistent_returns_not_found(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        mock_detail = AsyncMock(side_effect=PropertyNotFoundException())
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.get_managed_property_detail", new=mock_detail),
        ):
            result = await properties_tools.agent_properties_get(property_id=999)
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value

    @pytest.mark.asyncio
    async def test_insufficient_permissions(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        mock_detail = AsyncMock(side_effect=InsufficientPermissionsError())
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.get_managed_property_detail", new=mock_detail),
        ):
            result = await properties_tools.agent_properties_get(property_id=5)
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INSUFFICIENT_PERMISSIONS.value


class TestAgentPropertiesCreateForOwner:
    """Tests for ``agent_properties_create_for_owner``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(properties_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await properties_tools.agent_properties_create_for_owner(
                    owner_id=10,
                    title="Test",
                    property_type="apartment",
                    purpose="rent",
                    full_address="123 Street",
                    city="Delhi",
                    locality="Karol Bagh",
                    latitude=28.6,
                    longitude=77.2,
                    base_price=15000,
                )

    @pytest.mark.asyncio
    async def test_create_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        prop = make_property(property_id=12, title="New Build")
        mock_create = AsyncMock(return_value=prop)
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.create_managed_property", new=mock_create),
            patch.object(
                properties_tools,
                "serialize_property_basic",
                return_value={"id": 12, "title": "New Build"},
            ),
        ):
            result = await properties_tools.agent_properties_create_for_owner(
                owner_id=10,
                title="New Build",
                property_type="apartment",
                purpose="rent",
                full_address="123 Street",
                city="Delhi",
                locality="Karol Bagh",
                latitude=28.6,
                longitude=77.2,
                base_price=15000,
                monthly_rent=15000,
            )
        assert result["ok"] is True
        assert result["data"]["property"]["id"] == 12
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_property_type(self) -> None:
        # Validation happens before auth, so no auth mocks required.
        result = await properties_tools.agent_properties_create_for_owner(
            owner_id=10,
            title="Test",
            property_type="spaceship",
            purpose="rent",
            full_address="123 Street",
            city="Delhi",
            locality="Karol Bagh",
            latitude=28.6,
            longitude=77.2,
            base_price=15000,
        )
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value

    @pytest.mark.asyncio
    async def test_invalid_purpose(self) -> None:
        result = await properties_tools.agent_properties_create_for_owner(
            owner_id=10,
            title="Test",
            property_type="apartment",
            purpose="auction",
            full_address="123 Street",
            city="Delhi",
            locality="Karol Bagh",
            latitude=28.6,
            longitude=77.2,
            base_price=15000,
        )
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


class TestAgentPropertiesVerify:
    """Tests for ``agent_properties_verify``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(properties_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await properties_tools.agent_properties_verify(property_id=1, is_verified=True)

    @pytest.mark.asyncio
    async def test_verify_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        prop = make_property(property_id=3)
        prop.listing_preferences = {}  # type: ignore[attr-defined]
        mock_authz = AsyncMock(return_value=prop)
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_authz.assert_can_access_property", new=mock_authz),
        ):
            result = await properties_tools.agent_properties_verify(
                property_id=3, is_verified=True, verification_notes="Site visit done"
            )
        assert result["ok"] is True
        assert result["data"]["is_verified"] is True
        verification = prop.listing_preferences["verification"]  # type: ignore[attr-defined]
        assert verification["is_verified"] is True
        assert verification["notes"] == "Site visit done"
        db.flush.assert_awaited()
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_nonexistent_property(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        mock_authz = AsyncMock(side_effect=PropertyNotFoundException())
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_authz.assert_can_access_property", new=mock_authz),
        ):
            result = await properties_tools.agent_properties_verify(
                property_id=999, is_verified=True
            )
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value


# ===========================================================================
# Leases
# ===========================================================================


class TestAgentLeasesList:
    """Tests for ``agent_leases_list``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(leases_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await leases_tools.agent_leases_list()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_returns_leases(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        page = {
            "items": [{"id": 1, "status": "active"}],
            "total": None,
            "next_cursor": None,
            "has_more": False,
            "limit": 20,
        }
        mock_list = AsyncMock(return_value=page)
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
            patch("app.mcp.tool_ops.list_leases", new=mock_list),
        ):
            result = await leases_tools.agent_leases_list()
        assert result["ok"] is True
        assert result["data"]["items"][0]["id"] == 1
        assert "leases" not in result["data"]
        # The caller's owner scope is passed to the shared function.
        assert mock_list.await_args.kwargs["accessible_owner_ids"] == [10]

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_filter_by_property(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        page = {"items": [], "total": None, "next_cursor": None, "has_more": False, "limit": 20}
        mock_list = AsyncMock(return_value=page)
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
            patch("app.mcp.tool_ops.list_leases", new=mock_list),
        ):
            result = await leases_tools.agent_leases_list(property_id=55)
        assert result["ok"] is True
        assert mock_list.await_args.kwargs["property_id"] == 55


class TestAgentLeasesCreate:
    """Tests for ``agent_leases_create``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(leases_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await leases_tools.agent_leases_create(
                    property_id=1,
                    tenant_user_id=10,
                    start_date="2026-01-01",
                    end_date="2026-12-31",
                    monthly_rent=25000,
                    security_deposit=50000,
                )

    @pytest.mark.asyncio
    async def test_create_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        prop = make_property(property_id=1, owner_id=10)
        tenant = make_user(user_id=10, full_name="Tenant")
        mock_authz = AsyncMock(return_value=prop)
        created_lease = SimpleNamespace(id=1, property_id=1, owner_id=10, tenant_user_id=10)
        mock_create = AsyncMock(return_value=created_lease)
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_authz.assert_can_access_property", new=mock_authz),
            patch("app.services.user.get_user_by_id", new=AsyncMock(return_value=tenant)),
            patch("app.services.pm_leases.create_lease", new=mock_create),
            patch.object(leases_tools, "serialize_lease", return_value={"id": 1}),
        ):
            result = await leases_tools.agent_leases_create(
                property_id=1,
                tenant_user_id=10,
                start_date="2026-01-01",
                end_date="2026-12-31",
                monthly_rent=25000,
                security_deposit=50000,
            )
        assert result["ok"] is True
        assert result["data"]["lease"]["id"] == 1
        # The PM service writes the row. Unset terms and grace keep the managed defaults.
        kwargs = mock_create.await_args.kwargs
        assert kwargs["owner_id"] == 10
        assert kwargs["grace_period_days"] is None
        assert kwargs["payment_due_day"] is None
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_invalid_dates(self) -> None:
        # End date before start date → invalid input (validated before auth).
        result = await leases_tools.agent_leases_create(
            property_id=1,
            tenant_user_id=10,
            start_date="2026-12-31",
            end_date="2026-01-01",
            monthly_rent=25000,
            security_deposit=50000,
        )
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


class TestAgentLeasesTerminate:
    """Tests for ``agent_leases_terminate``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(leases_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await leases_tools.agent_leases_terminate(lease_id=1, reason="End of term")

    @pytest.mark.asyncio
    async def test_terminate_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        lease = make_lease(lease_id=1, status="active")
        lease.termination_reason = "Existing notes"
        mock_terminate = AsyncMock(return_value=lease)
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_leases.terminate_lease", new=mock_terminate),
        ):
            result = await leases_tools.agent_leases_terminate(lease_id=1, reason="End of term")
        assert result["ok"] is True
        assert result["data"]["lease_id"] == 1
        assert "termination_date" in result["data"]
        mock_terminate.assert_awaited_once()
        terminate_kwargs = mock_terminate.await_args.kwargs
        assert terminate_kwargs["lease_id"] == 1
        assert terminate_kwargs["reason"] == "End of term"
        assert terminate_kwargs["termination_date"] is not None
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_nonexistent_lease(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        mock_terminate = AsyncMock(side_effect=NotFoundException("Lease not found"))
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_leases.terminate_lease", new=mock_terminate),
        ):
            result = await leases_tools.agent_leases_terminate(lease_id=999, reason="End of term")
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.NOT_FOUND.value


# ===========================================================================
# Rent
# ===========================================================================


class TestAgentRentListDue:
    """Tests for ``agent_rent_list_due``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(rent_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await rent_tools.agent_rent_list_due()

    @pytest.mark.asyncio
    async def test_returns_overdue(self) -> None:
        agent = make_agent()
        due = {
            "items": [{"id": 1, "is_overdue": True, "balance": 25000.0}],
            "totals": {
                "total_due": 25000.0,
                "total_paid": 0.0,
                "overdue_count": 1,
                "charges_count": 1,
            },
            "next_cursor": None,
            "has_more": False,
            "limit": 20,
        }
        compute = AsyncMock(return_value=due)
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(AsyncMock())),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(rent_tools, "_require_agent_or_admin", return_value=True),
            patch.object(rent_tools, "compute_rent_due_items", new=compute),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await rent_tools.agent_rent_list_due(overdue_only=True)
        assert result["ok"] is True
        assert compute.await_args.kwargs["overdue_only"] is True
        assert result["data"]["totals"]["overdue_count"] == 1
        assert "counts" not in result["data"]

    @pytest.mark.asyncio
    async def test_returns_all_due(self) -> None:
        agent = make_agent()
        due = {
            "items": [{"id": 2, "is_overdue": False, "balance": 18000.0}],
            "totals": {
                "total_due": 18000.0,
                "total_paid": 0.0,
                "overdue_count": 0,
                "charges_count": 1,
            },
            "next_cursor": None,
            "has_more": False,
            "limit": 20,
        }
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(AsyncMock())),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(rent_tools, "_require_agent_or_admin", return_value=True),
            patch.object(rent_tools, "compute_rent_due_items", new=AsyncMock(return_value=due)),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await rent_tools.agent_rent_list_due(overdue_only=False)
        assert result["ok"] is True
        assert len(result["data"]["items"]) == 1
        assert result["data"]["totals"]["total_due"] == 18000.0


class TestAgentRentRecordPayment:
    """Tests for ``agent_rent_record_payment``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(rent_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await rent_tools.agent_rent_record_payment(
                    lease_id=1, amount=1000, payment_date="2026-06-01", payment_method="upi"
                )

    @pytest.mark.asyncio
    async def test_record_settles_through_the_shared_operation(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        settled = SimpleNamespace(
            id=5,
            charge_id=9,
            lease_id=1,
            property_id=2,
            amount_paid=25000.0,
            paid_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            payment_method="upi",
            status="settled",
            reference="TXN-001",
            notes=None,
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        mock_record = AsyncMock(return_value=settled)
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(rent_tools, "_require_agent_or_admin", return_value=True),
            patch.object(rent_tools, "record_lease_rent_payment", new=mock_record),
        ):
            result = await rent_tools.agent_rent_record_payment(
                lease_id=1,
                amount=25000,
                payment_date=date(2026, 6, 1),
                payment_method=PaymentMethod.upi,
                transaction_reference="TXN-001",
            )
        assert result["ok"] is True
        payment = result["data"]["payment"]
        assert payment["charge_id"] == 9
        assert payment["amount_paid"] == 25000.0
        assert payment["status"] == "settled"
        assert mock_record.await_args.kwargs["payment_method"] == PaymentMethod.upi
        db.commit.assert_awaited()


# ===========================================================================
# Maintenance
# ===========================================================================


class TestAgentMaintenanceList:
    """Tests for ``agent_maintenance_list``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(maintenance_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(maintenance_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(maintenance_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await maintenance_tools.agent_maintenance_list()

    @pytest.mark.asyncio
    async def test_returns_requests(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        req = make_maintenance_request(request_id=1)
        db.execute.return_value = _execute_result(scalars_all=[req])
        with (
            patch.object(maintenance_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(maintenance_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(maintenance_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
            patch.object(
                maintenance_tools,
                "serialize_maintenance_request",
                return_value={"id": 1, "status": "open"},
            ),
        ):
            result = await maintenance_tools.agent_maintenance_list()
        assert result["ok"] is True
        assert result["data"]["total"] is None
        assert result["data"]["items"][0]["id"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_status(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        db.execute.return_value = _execute_result(scalars_all=[])
        with (
            patch.object(maintenance_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(maintenance_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(maintenance_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await maintenance_tools.agent_maintenance_list(status="completed")
        assert result["ok"] is True
        db.execute.assert_awaited_once()


class TestAgentMaintenanceUpdateStatus:
    """Tests for ``agent_maintenance_update_status``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(maintenance_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(maintenance_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(maintenance_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await maintenance_tools.agent_maintenance_update_status(
                    request_id=1, status="in_progress"
                )

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_update_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        req = make_maintenance_request(request_id=1)
        update = AsyncMock(return_value=req)
        with (
            patch.object(maintenance_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(maintenance_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(maintenance_tools, "_require_agent_or_admin", return_value=True),
            patch.object(maintenance_tools, "update_maintenance_status", new=update),
        ):
            result = await maintenance_tools.agent_maintenance_update_status(
                request_id=1, status="in_progress", notes="Vendor assigned"
            )
        assert result["ok"] is True
        assert "request" in result["data"]
        # The PM service does the write and the checks; the tool only commits.
        update.assert_awaited_once()
        assert update.await_args.kwargs["actor"] is agent
        assert update.await_args.kwargs["status"] == "in_progress"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_refused_by_the_service_is_a_permission_failure(self) -> None:
        db = AsyncMock()
        with (
            patch.object(maintenance_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(maintenance_tools, "_get_user", new=AsyncMock(return_value=make_agent())),
            patch.object(maintenance_tools, "_require_agent_or_admin", return_value=True),
            patch.object(
                maintenance_tools,
                "update_maintenance_status",
                new=AsyncMock(side_effect=InsufficientPermissionsError("not in scope")),
            ),
        ):
            result = await maintenance_tools.agent_maintenance_update_status(
                request_id=1, status="completed"
            )
        assert result["ok"] is False
        db.commit.assert_not_awaited()


# ===========================================================================
# Bookings
# ===========================================================================


class TestAgentBookingsListAll:
    """Tests for ``agent_bookings_list_all``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(bookings_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(bookings_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(bookings_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await bookings_tools.agent_bookings_list_all()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_returns_bookings(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        page = {
            "items": [{"id": 1, "booking_reference": "BK-001"}],
            "total": None,
            "limit": 20,
            "next_cursor": None,
            "has_more": False,
        }
        mock_list = AsyncMock(return_value=page)
        with (
            patch.object(bookings_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(bookings_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(bookings_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
            patch("app.mcp.tool_ops.list_managed_bookings", new=mock_list),
        ):
            result = await bookings_tools.agent_bookings_list_all()
        assert result["ok"] is True
        assert result["data"]["items"][0]["id"] == 1
        assert "bookings" not in result["data"]
        assert mock_list.await_args.kwargs["owner_ids"] == [10]


class TestAgentBookingsUpdateStatus:
    """Tests for ``agent_bookings_update_status``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(bookings_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(bookings_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(bookings_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await bookings_tools.agent_bookings_update_status(booking_id=1, status="confirmed")

    @pytest.mark.asyncio
    async def test_update_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        updated = SimpleNamespace(id=1, booking_status="confirmed")
        db.get = AsyncMock(return_value=updated)
        mock_update = AsyncMock(
            return_value={"message": "Booking updated to confirmed", "booking_id": 1}
        )
        with (
            patch.object(bookings_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(bookings_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(bookings_tools, "_require_agent_or_admin", return_value=True),
            patch("app.mcp.tool_ops.update_booking_status", new=mock_update),
            patch.object(
                bookings_tools,
                "serialize_booking",
                return_value={"id": 1, "booking_status": "confirmed"},
            ),
        ):
            result = await bookings_tools.agent_bookings_update_status(
                booking_id=1, status="confirmed"
            )
        assert result["ok"] is True
        assert result["data"]["booking"]["booking_status"] == "confirmed"
        assert mock_update.await_args.kwargs["booking_id"] == 1


# ===========================================================================
# Dashboard
# ===========================================================================


class TestAgentDashboard:
    """Tests for ``agent_dashboard_overview``."""

    @pytest.mark.asyncio
    async def test_requires_auth(self) -> None:
        db = AsyncMock()
        with (
            patch.object(dashboard_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(dashboard_tools, "_get_user", new=AsyncMock(return_value=None)),
            patch.object(dashboard_tools, "_require_auth", side_effect=raise_auth_required),
        ):
            with pytest.raises(AuthRequiredError):
                await dashboard_tools.agent_dashboard_overview()

    @pytest.mark.asyncio
    async def test_returns_metrics(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        # Five scalar queries in order: properties, leases, maintenance, bookings, rent.
        db.execute.side_effect = [
            _execute_result(scalar=10),
            _execute_result(scalar=8),
            _execute_result(scalar=3),
            _execute_result(scalar=2),
            _execute_result(scalar=200000),
        ]
        with (
            patch.object(dashboard_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(dashboard_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(dashboard_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await dashboard_tools.agent_dashboard_overview()
        assert result["ok"] is True
        metrics = result["data"]["metrics"]
        assert metrics["total_properties"] == 10
        assert metrics["active_leases"] == 8
        assert metrics["occupancy_rate"] == 80.0
        assert metrics["open_maintenance_requests"] == 3
        assert metrics["upcoming_bookings"] == 2
        assert metrics["monthly_rent_expected"] == 200000

    @pytest.mark.asyncio
    async def test_empty_portfolio(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        db.execute.side_effect = [
            _execute_result(scalar=0),
            _execute_result(scalar=0),
            _execute_result(scalar=0),
            _execute_result(scalar=0),
            _execute_result(scalar=0),
        ]
        with (
            patch.object(dashboard_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(dashboard_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(dashboard_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await dashboard_tools.agent_dashboard_overview()
        assert result["ok"] is True
        metrics = result["data"]["metrics"]
        assert metrics["total_properties"] == 0
        assert metrics["active_leases"] == 0
        assert metrics["occupancy_rate"] == 0
        assert metrics["monthly_rent_expected"] == 0
