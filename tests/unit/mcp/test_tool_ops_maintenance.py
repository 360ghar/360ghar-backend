"""Unit tests for MCP maintenance tool_ops layer.

These tests exercise the shared maintenance tool_ops functions in
``app/mcp/tool_ops/maintenance.py`` directly, mocking the DB session to
verify that each function:
- Validates category / priority before creating a request
- Enforces the active-lease tenant guard (FORBIDDEN when none)
- Serializes requests via ``serialize_maintenance_request``
- Builds status filters (status updates: tests/unit/mcp/test_maintenance_status_service.py)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.mcp.tool_ops import maintenance as maint_tool_ops
from tests.unit.mcp.conftest import make_maintenance_request

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value):
    """Mock ``db.execute()`` result with sync ``scalar_one_or_none()``."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar_one = MagicMock(return_value=value)
    return result


def _scalars_result(values):
    """Mock ``db.execute()`` result whose ``.scalars().all()`` yields ``values``."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result



# ---------------------------------------------------------------------------
# create_maintenance_request
# ---------------------------------------------------------------------------


class TestCreateMaintenanceRequest:
    """tool_ops delegates to the PM service, which owns the lease rule and the row."""

    async def test_create_success_delegates_to_the_pm_service(self) -> None:
        from app.models.enums import MaintenanceCategory, MaintenanceUrgency

        db = AsyncMock()
        actor = SimpleNamespace(id=10)
        db.get = AsyncMock(return_value=actor)
        created = SimpleNamespace(id=33)
        service = AsyncMock(return_value=created)
        shaped = {"id": 33, "category": "plumbing", "priority": "high", "status": "open"}

        with (
            patch.object(maint_tool_ops, "create_pm_maintenance_request", new=service),
            patch.object(maint_tool_ops, "serialize_maintenance_request", return_value=shaped),
        ):
            result = await maint_tool_ops.create_maintenance_request(
                db,
                tenant_user_id=10,
                property_id=3,
                title="Leaking tap",
                description="Kitchen tap drips constantly",
                category="plumbing",
                priority="high",
            )

        assert result["message"] == "Maintenance request created successfully"
        assert result["request"] == shaped
        kwargs = service.await_args.kwargs
        assert kwargs["actor"] is actor
        assert kwargs["property_id"] == 3
        assert kwargs["category"] is MaintenanceCategory.plumbing
        assert kwargs["urgency"] is MaintenanceUrgency.high

    async def test_no_active_lease_maps_to_forbidden(self) -> None:
        from app.core.exceptions import InsufficientPermissionsError

        db = AsyncMock()
        db.get = AsyncMock(return_value=SimpleNamespace(id=10))
        service = AsyncMock(side_effect=InsufficientPermissionsError("no lease"))

        with patch.object(maint_tool_ops, "create_pm_maintenance_request", new=service):
            result = await maint_tool_ops.create_maintenance_request(
                db,
                tenant_user_id=10,
                property_id=3,
                title="Broken window",
                description="Window shattered",
                category="structural",
                priority="medium",
            )

        assert result["error"] is True
        assert result["code"] == maint_tool_ops.TOOL_OPS_FORBIDDEN
        assert "lease" in result["message"].lower()


class TestListMaintenanceRequests:
    async def test_returns_requests(self) -> None:
        db = AsyncMock()
        requests = [
            make_maintenance_request(request_id=1),
            make_maintenance_request(request_id=2),
        ]
        db.execute = AsyncMock(side_effect=[_scalars_result(requests), _scalar_result(2)])

        result = await maint_tool_ops.list_maintenance_requests(
            db, tenant_user_id=10, include_total=True
        )

        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert result["has_more"] is False
        assert result["next_cursor"] is None

    async def test_empty_result(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_scalars_result([]), _scalar_result(0)])

        result = await maint_tool_ops.list_maintenance_requests(db, include_total=True)

        assert result["total"] == 0
        assert result["items"] == []
        assert result["has_more"] is False

    async def test_status_filter_invalid(self) -> None:
        db = AsyncMock()
        # An INVALID status bubbles up as an error from the status-filter
        # integration. The error short-circuits before the DB query is issued.
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await maint_tool_ops.list_maintenance_requests(db, status="bogus")

        assert result["error"] is True
        assert "Invalid status" in result["message"]
        db.execute.assert_not_awaited()

    async def test_status_filter_valid_open(self) -> None:
        db = AsyncMock()
        requests = [make_maintenance_request(request_id=1)]
        db.execute = AsyncMock(return_value=_scalars_result(requests))

        result = await maint_tool_ops.list_maintenance_requests(db, status="open")

        # A valid status should NOT return an error — it filters results normally
        assert "error" not in result
        assert len(result["items"]) == 1
        # Without include_total the page query is the only query and total is null.
        assert result["total"] is None
        db.execute.assert_awaited_once()

    async def test_status_filter_valid_completed(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await maint_tool_ops.list_maintenance_requests(db, status="completed")

        assert "error" not in result
        assert result["items"] == []
        assert result["total"] is None


# ---------------------------------------------------------------------------
# build_maintenance_status_filter
# ---------------------------------------------------------------------------


class TestBuildMaintenanceStatusFilter:
    def test_open_filter(self) -> None:
        stmt = MagicMock()

        filtered, status = maint_tool_ops.build_maintenance_status_filter(stmt, "open")

        assert status == "open"
        assert filtered is not None
        stmt.where.assert_called_once()

    def test_completed_filter(self) -> None:
        stmt = MagicMock()

        filtered, status = maint_tool_ops.build_maintenance_status_filter(stmt, "completed")

        assert status == "completed"
        assert filtered is not None
        stmt.where.assert_called_once()

    def test_invalid_status(self) -> None:
        stmt = MagicMock()

        filtered, status = maint_tool_ops.build_maintenance_status_filter(stmt, "bogus")

        assert filtered is None
        assert "Invalid status" in status
        stmt.where.assert_not_called()

    def test_in_progress_filter(self) -> None:
        stmt = MagicMock()

        filtered, status = maint_tool_ops.build_maintenance_status_filter(stmt, "in_progress")

        assert status == "in_progress"
        assert filtered is not None
        stmt.where.assert_called_once()

    def test_scheduled_filter(self) -> None:
        stmt = MagicMock()

        filtered, status = maint_tool_ops.build_maintenance_status_filter(stmt, "scheduled")

        assert status == "scheduled"
        assert filtered is not None
        stmt.where.assert_called_once()

    def test_cancelled_filter(self) -> None:
        stmt = MagicMock()

        filtered, status = maint_tool_ops.build_maintenance_status_filter(stmt, "cancelled")

        assert status == "cancelled"
        assert filtered is not None
        stmt.where.assert_called_once()

    def test_none_status(self) -> None:
        stmt = MagicMock()

        filtered, status = maint_tool_ops.build_maintenance_status_filter(stmt, None)

        assert status is None
        assert filtered is stmt
        stmt.where.assert_not_called()
