"""Unit tests for MCP lease tool_ops layer.

These tests exercise the shared lease tool_ops functions in
``app/mcp/tool_ops/leases.py`` directly, mocking the DB session and the
pm_authz / user helpers to verify that each function:
- Translates DB rows into the tool_ops dict contract via ``serialize_lease``
- Performs date validation on create
- Returns the expected error payloads (property/lease not found, bad status)
- Honors the active-lease guard on terminate
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import NotFoundException, PropertyNotFoundException
from app.mcp.tool_ops import leases as leases_tool_ops
from app.models.enums import LeaseStatus
from tests.unit.mcp.conftest import make_lease, make_property, make_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value):
    """Build a mock ``db.execute()`` result with sync ``scalar_one_or_none()``.

    The tool_ops code does ``(await db.execute(...)).scalar_one_or_none()``
    (no second await), so the method must be a sync MagicMock that returns
    the value directly.
    """
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _scalars_result(values):
    """Build a mock ``db.execute()`` result whose ``.scalars().all()`` yields ``values``."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _make_lease_obj(
    lease_id: int = 1,
    property_id: int = 1,
    tenant_user_id: int = 10,
    owner_id: int = 10,
    monthly_rent: float = 25000,
    status: LeaseStatus = LeaseStatus.active,
    start_date: str = "2026-01-01",
    end_date: str = "2026-12-31",
) -> MagicMock:
    """Create a mock lease row compatible with ``serialize_lease``.

    ``make_lease`` from conftest stores ``status`` as a plain string, but
    ``serialize_lease`` reads ``status.value``; we override it with the enum.
    """
    lease = make_lease(
        lease_id=lease_id,
        property_id=property_id,
        tenant_user_id=tenant_user_id,
        monthly_rent=monthly_rent,
        status=status.value,
        start_date=start_date,
        end_date=end_date,
    )
    lease.status = status  # enum, so serialize_lease can read .value
    lease.owner_id = owner_id
    lease.lease_terms = None
    lease.special_clauses = None
    lease.late_fee_amount = None
    lease.late_fee_percentage = None
    lease.updated_at = None
    return lease


# ---------------------------------------------------------------------------
# get_tenant_current_lease
# ---------------------------------------------------------------------------


class TestGetTenantCurrentLease:
    async def test_returns_active_lease(self) -> None:
        db = AsyncMock()
        lease = _make_lease_obj(lease_id=7, tenant_user_id=10)
        prop = make_property(property_id=1, title="Green Villa")
        # First execute: lease lookup; second execute: property lookup.
        db.execute = AsyncMock(side_effect=[_scalar_result(lease), _scalar_result(prop)])

        result = await leases_tool_ops.get_tenant_current_lease(db, tenant_user_id=10)

        assert result["lease"] is not None
        assert result["lease"]["id"] == 7
        assert result["lease"]["status"] == "active"
        assert result["lease"]["property"]["title"] == "Green Villa"
        assert result["lease"]["property"]["id"] == 1

    async def test_no_active_lease(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await leases_tool_ops.get_tenant_current_lease(db, tenant_user_id=10)

        assert result["lease"] is None
        assert "No active lease" in result["message"]

    async def test_lease_without_property(self) -> None:
        db = AsyncMock()
        lease = _make_lease_obj(lease_id=7)
        db.execute = AsyncMock(side_effect=[_scalar_result(lease), _scalar_result(None)])

        result = await leases_tool_ops.get_tenant_current_lease(db, tenant_user_id=10)

        assert result["lease"]["id"] == 7
        # Property missing from DB → property payload is None but lease still returned
        assert result["lease"]["property"] is None


# ---------------------------------------------------------------------------
# list_leases
# ---------------------------------------------------------------------------


class TestListLeases:
    async def test_returns_leases(self) -> None:
        db = AsyncMock()
        leases = [_make_lease_obj(lease_id=1), _make_lease_obj(lease_id=2)]
        db.execute = AsyncMock(return_value=_scalars_result(leases))

        result = await leases_tool_ops.list_leases(db, actor=make_user(), limit=20)

        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert result["has_more"] is False
        assert result["next_cursor"] is None
        assert result["limit"] == 20

    async def test_empty_result(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await leases_tool_ops.list_leases(db, actor=make_user())

        assert result["total"] == 0
        assert result["items"] == []
        assert result["has_more"] is False

    async def test_pagination(self) -> None:
        db = AsyncMock()
        # Return limit+1 items to signal has_more=True (limit+1 fetch pattern)
        leases = [_make_lease_obj(lease_id=i) for i in range(6)]
        db.execute = AsyncMock(return_value=_scalars_result(leases))

        result = await leases_tool_ops.list_leases(db, actor=make_user(), limit=5)

        assert result["has_more"] is True
        assert result["next_cursor"] is not None
        assert len(result["items"]) == 5


# ---------------------------------------------------------------------------
# create_lease
# ---------------------------------------------------------------------------


class TestCreateLease:
    async def test_create_success(self) -> None:
        db = AsyncMock()
        actor = make_user()
        prop = make_property(property_id=3, owner_id=10)
        tenant = make_user(user_id=11, full_name="Tenant User")

        async def _refresh(obj, *args, **kwargs):
            obj.id = 42

        db.refresh = AsyncMock(side_effect=_refresh)
        # db.add() is synchronous on AsyncSession; override the AsyncMock attr
        db.add = MagicMock()

        with (
            patch.object(
                leases_tool_ops, "assert_can_access_property", AsyncMock(return_value=prop)
            ),
            patch.object(leases_tool_ops, "get_user_by_id", AsyncMock(return_value=tenant)),
        ):
            result = await leases_tool_ops.create_lease(
                db,
                actor=actor,
                property_id=3,
                tenant_user_id=11,
                start_date="2026-07-01",
                end_date="2027-06-30",
                monthly_rent=30000,
                security_deposit=60000,
            )

        assert result["message"] == "Lease created successfully"
        assert result["lease"]["id"] == 42
        assert result["lease"]["monthly_rent"] == 30000.0
        assert result["lease"]["security_deposit"] == 60000.0
        assert result["lease"]["status"] == "active"
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_end_date_before_start(self) -> None:
        db = AsyncMock()
        actor = make_user()
        prop = make_property(property_id=3)
        tenant = make_user(user_id=11)

        with (
            patch.object(
                leases_tool_ops, "assert_can_access_property", AsyncMock(return_value=prop)
            ),
            patch.object(leases_tool_ops, "get_user_by_id", AsyncMock(return_value=tenant)),
        ):
            result = await leases_tool_ops.create_lease(
                db,
                actor=actor,
                property_id=3,
                tenant_user_id=11,
                start_date="2026-07-01",
                end_date="2026-06-30",  # before start
                monthly_rent=30000,
            )

        assert result["error"] is True
        assert "after start date" in result["message"]
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_property_not_found(self) -> None:
        db = AsyncMock()
        actor = make_user()

        with patch.object(
            leases_tool_ops,
            "assert_can_access_property",
            AsyncMock(side_effect=PropertyNotFoundException(detail="Property not found")),
        ):
            result = await leases_tool_ops.create_lease(
                db,
                actor=actor,
                property_id=999,
                tenant_user_id=11,
                start_date="2026-07-01",
                end_date="2027-06-30",
                monthly_rent=30000,
            )

        assert result["error"] is True
        assert "not found" in result["message"].lower()
        db.add.assert_not_called()
        db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# terminate_lease
# ---------------------------------------------------------------------------


class TestTerminateLease:
    async def test_terminate_success(self) -> None:
        db = AsyncMock()
        actor = make_user()
        lease = _make_lease_obj(lease_id=5, status=LeaseStatus.active)

        with patch.object(
            leases_tool_ops, "assert_can_access_lease", AsyncMock(return_value=lease)
        ):
            result = await leases_tool_ops.terminate_lease(
                db, actor=actor, lease_id=5, reason="Tenant moving out"
            )

        assert result["message"] == "Lease terminated successfully"
        assert lease.status == LeaseStatus.terminated
        assert "Terminated: Tenant moving out" in lease.special_clauses
        assert result["lease"]["status"] == "terminated"
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_lease_not_found(self) -> None:
        db = AsyncMock()
        actor = make_user()

        with patch.object(
            leases_tool_ops,
            "assert_can_access_lease",
            AsyncMock(side_effect=NotFoundException(detail="Lease not found")),
        ):
            result = await leases_tool_ops.terminate_lease(
                db, actor=actor, lease_id=999, reason="N/A"
            )

        assert result["error"] is True
        assert "not found" in result["message"].lower()
        db.commit.assert_not_awaited()

    async def test_already_terminated(self) -> None:
        db = AsyncMock()
        actor = make_user()
        lease = _make_lease_obj(lease_id=5, status=LeaseStatus.terminated)

        with patch.object(
            leases_tool_ops, "assert_can_access_lease", AsyncMock(return_value=lease)
        ):
            result = await leases_tool_ops.terminate_lease(
                db, actor=actor, lease_id=5, reason="N/A"
            )

        assert result["error"] is True
        assert "terminated" in result["message"].lower()
        db.commit.assert_not_awaited()
