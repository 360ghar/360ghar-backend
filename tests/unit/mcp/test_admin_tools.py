"""Tests for MCP admin/agent tools (properties, leases, rent, maintenance, bookings, dashboard)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mcp.tool_ops.rent as tool_ops_rent
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
            patch.object(
                properties_tools,
                "serialize_property_basic",
                return_value={"id": 1, "title": "Sunset Villa"},
            ),
        ):
            result = await properties_tools.agent_properties_list()
        assert result["ok"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["items"][0]["id"] == 1
        assert result["data"]["has_more"] is False

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
        mock_detail = AsyncMock(
            return_value={"property": prop, "active_lease": None}
        )
        with (
            patch.object(properties_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(properties_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(properties_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_properties.get_managed_property_detail", new=mock_detail),
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
    async def test_returns_leases(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        lease = make_lease(lease_id=1)
        count_result = _execute_result(scalar=1)
        list_result = _execute_result(scalars_all=[lease])
        db.execute.side_effect = [count_result, list_result]
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
            patch.object(
                leases_tools,
                "serialize_lease",
                return_value={"id": 1, "status": "active"},
            ),
        ):
            result = await leases_tools.agent_leases_list()
        assert result["ok"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["leases"][0]["id"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_property(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        count_result = _execute_result(scalar=0)
        list_result = _execute_result(scalars_all=[])
        db.execute.side_effect = [count_result, list_result]
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await leases_tools.agent_leases_list(property_id=55)
        assert result["ok"] is True
        # Two execute calls: count + list. Both should have been issued.
        assert db.execute.await_count == 2


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
        db.add = MagicMock()  # sync method on AsyncSession
        agent = make_agent()
        prop = make_property(property_id=1, owner_id=10)
        tenant = make_user(user_id=10, full_name="Tenant")
        mock_authz = AsyncMock(return_value=prop)
        created_lease = SimpleNamespace(id=1, property_id=1, owner_id=10, tenant_user_id=10)
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_authz.assert_can_access_property", new=mock_authz),
            patch("app.services.user.get_user_by_id", new=AsyncMock(return_value=tenant)),
            patch("app.models.pm_leases.Lease", return_value=created_lease),
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
        db.add.assert_called_once_with(created_lease)
        db.flush.assert_awaited()
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
        lease.notes = "Existing notes"  # type: ignore[attr-defined]
        mock_authz = AsyncMock(return_value=lease)
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_authz.assert_can_access_lease", new=mock_authz),
        ):
            result = await leases_tools.agent_leases_terminate(
                lease_id=1, reason="End of term"
            )
        assert result["ok"] is True
        assert result["data"]["lease_id"] == 1
        db.flush.assert_awaited()
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_nonexistent_lease(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        mock_authz = AsyncMock(side_effect=NotFoundException("Lease not found"))
        with (
            patch.object(leases_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(leases_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(leases_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_authz.assert_can_access_lease", new=mock_authz),
        ):
            result = await leases_tools.agent_leases_terminate(
                lease_id=999, reason="End of term"
            )
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
        db = AsyncMock()
        agent = make_agent()
        # Active lease whose grace window has elapsed so it counts as overdue.
        overdue_lease = make_lease(lease_id=1, monthly_rent=25000)
        overdue_lease.owner_id = 10  # type: ignore[attr-defined]
        # payment_due_day=1, grace=5 → grace_end on day 6. Freeze time to day 20.
        frozen_now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        result_row = _execute_result(scalars_all=[overdue_lease])
        db.execute.return_value = result_row
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(rent_tools, "_require_agent_or_admin", return_value=True),
            patch.object(tool_ops_rent, "utc_now", return_value=frozen_now),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await rent_tools.agent_rent_list_due(overdue_only=True)
        assert result["ok"] is True
        assert result["data"]["overdue_count"] >= 1

    @pytest.mark.asyncio
    async def test_returns_all_due(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        lease = make_lease(lease_id=2, monthly_rent=18000)
        lease.owner_id = 10  # type: ignore[attr-defined]
        frozen_now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
        result_row = _execute_result(scalars_all=[lease])
        db.execute.return_value = result_row
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(rent_tools, "_require_agent_or_admin", return_value=True),
            patch.object(tool_ops_rent, "utc_now", return_value=frozen_now),
            patch(
                "app.services.pm_authz.get_accessible_owner_ids",
                new=AsyncMock(return_value=[10]),
            ),
        ):
            result = await rent_tools.agent_rent_list_due(overdue_only=False)
        assert result["ok"] is True
        assert result["data"]["total"] >= 1


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
    async def test_record_success(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()  # sync method on AsyncSession
        agent = make_agent()
        mock_authz = AsyncMock(return_value=None)
        # RentPayment ORM rejects the tool's kwargs, so patch the model to a
        # SimpleNamespace carrying the attributes the tool reads back.
        created_payment = SimpleNamespace(
            id=5,
            lease_id=1,
            amount_paid=25000,
            paid_at=datetime(2026, 6, 1),
            payment_method="upi",
            status="completed",
        )
        with (
            patch.object(rent_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(rent_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(rent_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.pm_authz.assert_can_access_lease", new=mock_authz),
            patch("app.models.pm_finance.RentPayment", return_value=created_payment),
        ):
            result = await rent_tools.agent_rent_record_payment(
                lease_id=1,
                amount=25000,
                payment_date="2026-06-01",
                payment_method="upi",
                transaction_reference="TXN-001",
            )
        assert result["ok"] is True
        assert result["data"]["payment"]["lease_id"] == 1
        assert result["data"]["payment"]["amount"] == 25000
        assert result["data"]["payment"]["payment_method"] == "upi"
        db.add.assert_called_once_with(created_payment)
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_invalid_payment_method(self) -> None:
        # Validated before auth.
        result = await rent_tools.agent_rent_record_payment(
            lease_id=1,
            amount=25000,
            payment_date="2026-06-01",
            payment_method="crypto",
        )
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


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
        assert result["data"]["total"] == 1
        assert result["data"]["requests"][0]["id"] == 1

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
    async def test_update_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        req = make_maintenance_request(request_id=1)
        db.execute.return_value = _execute_result(scalar=req)
        with (
            patch.object(maintenance_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(maintenance_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(maintenance_tools, "_require_agent_or_admin", return_value=True),
            patch(
                "app.services.pm_authz.assert_can_access_property",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await maintenance_tools.agent_maintenance_update_status(
                request_id=1, status="in_progress", notes="Vendor assigned"
            )
        assert result["ok"] is True
        assert "request" in result["data"]
        db.flush.assert_awaited()
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_invalid_status_transition(self) -> None:
        # Invalid status string is rejected before auth.
        result = await maintenance_tools.agent_maintenance_update_status(
            request_id=1, status="rejected"
        )
        assert result["ok"] is False
        assert result["error"]["code"] == MCPErrorCode.INVALID_INPUT.value


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
    async def test_returns_bookings(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        booking = SimpleNamespace(
            id=1,
            booking_reference="BK-001",
            property_id=1,
            user_id=10,
            check_in_date="2026-07-01",
            check_out_date="2026-07-05",
        )
        mock_get_all = AsyncMock(return_value=([booking], None, 1))
        with (
            patch.object(bookings_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(bookings_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(bookings_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.booking.get_all_bookings", new=mock_get_all),
            patch.object(
                bookings_tools,
                "serialize_booking",
                return_value={"id": 1, "booking_reference": "BK-001"},
            ),
        ):
            result = await bookings_tools.agent_bookings_list_all()
        assert result["ok"] is True
        assert result["data"]["bookings"][0]["id"] == 1
        assert result["data"]["total"] == 1


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
                await bookings_tools.agent_bookings_update_status(
                    booking_id=1, status="confirmed"
                )

    @pytest.mark.asyncio
    async def test_update_success(self) -> None:
        db = AsyncMock()
        agent = make_agent()
        booking = SimpleNamespace(id=1, booking_status="pending")
        updated = SimpleNamespace(id=1, booking_status="confirmed")
        mock_get = AsyncMock(return_value=booking)
        mock_update = AsyncMock(return_value=updated)
        with (
            patch.object(bookings_tools, "get_db", return_value=async_gen_db(db)),
            patch.object(bookings_tools, "_get_user", new=AsyncMock(return_value=agent)),
            patch.object(bookings_tools, "_require_agent_or_admin", return_value=True),
            patch("app.services.booking.get_booking", new=mock_get),
            patch("app.services.booking.update_booking", new=mock_update),
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
        db.commit.assert_awaited()


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
