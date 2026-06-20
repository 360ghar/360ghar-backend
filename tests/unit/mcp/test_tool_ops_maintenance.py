"""Unit tests for MCP maintenance tool_ops layer.

These tests exercise the shared maintenance tool_ops functions in
``app/mcp/tool_ops/maintenance.py`` directly, mocking the DB session to
verify that each function:
- Validates category / priority before creating a request
- Enforces the active-lease tenant guard (FORBIDDEN when none)
- Serializes requests via ``serialize_maintenance_request``
- Applies status transitions and builds status filters
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp.tool_ops import maintenance as maint_tool_ops
from app.models.enums import MaintenanceRequestStatus, WorkOrderStatus
from tests.unit.mcp.conftest import make_maintenance_request

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


def _make_request_obj(request_id: int = 1) -> SimpleNamespace:
    """Create a maintenance request with lifecycle attrs initialized to None.

    ``apply_maintenance_status_update`` reads several lifecycle attributes
    (e.g. ``completed_at``) via direct attribute access before writing them,
    so they must exist on the mock object.
    """
    req = make_maintenance_request(request_id=request_id)
    req.request_status = None
    req.work_order_status = None
    req.scheduled_for = None
    req.completed_at = None
    req.completion_notes = None
    req.estimated_cost = None
    req.actual_cost = None
    return req


# ---------------------------------------------------------------------------
# create_maintenance_request
# ---------------------------------------------------------------------------


class TestCreateMaintenanceRequest:
    async def test_create_success(self) -> None:
        db = AsyncMock()
        lease = SimpleNamespace(id=7, owner_id=10)

        async def _refresh(obj, *args, **kwargs):
            obj.id = 33

        db.refresh = AsyncMock(side_effect=_refresh)
        db.execute = AsyncMock(return_value=_scalar_result(lease))
        # db.add() is synchronous on AsyncSession; override the AsyncMock attr
        db.add = MagicMock()

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
        assert result["request"]["id"] == 33
        assert result["request"]["category"] == "plumbing"
        assert result["request"]["priority"] == "high"
        assert result["request"]["status"] == "open"
        assert result["request"]["property_id"] == 3
        assert result["request"]["lease_id"] == 7
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_no_active_lease(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

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
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_invalid_category(self) -> None:
        db = AsyncMock()

        result = await maint_tool_ops.create_maintenance_request(
            db,
            tenant_user_id=10,
            property_id=3,
            title="x",
            description="y",
            category="teleportation",  # not a valid category
            priority="high",
        )

        assert result["error"] is True
        assert result["code"] == maint_tool_ops.TOOL_OPS_INVALID_INPUT
        assert "category" in result["message"].lower()
        db.execute.assert_not_awaited()
        db.add.assert_not_called()

    async def test_invalid_priority(self) -> None:
        db = AsyncMock()

        result = await maint_tool_ops.create_maintenance_request(
            db,
            tenant_user_id=10,
            property_id=3,
            title="x",
            description="y",
            category="plumbing",
            priority="supercritical",  # not a valid priority keyword
        )

        assert result["error"] is True
        assert result["code"] == maint_tool_ops.TOOL_OPS_INVALID_INPUT
        assert "priority" in result["message"].lower()
        db.execute.assert_not_awaited()
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# list_maintenance_requests
# ---------------------------------------------------------------------------


class TestListMaintenanceRequests:
    async def test_returns_requests(self) -> None:
        db = AsyncMock()
        requests = [
            make_maintenance_request(request_id=1),
            make_maintenance_request(request_id=2),
        ]
        db.execute = AsyncMock(return_value=_scalars_result(requests))

        result = await maint_tool_ops.list_maintenance_requests(db, tenant_user_id=10)

        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert result["has_more"] is False
        assert result["next_cursor"] is None

    async def test_empty_result(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await maint_tool_ops.list_maintenance_requests(db)

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
        assert result["total"] == 1
        db.execute.assert_awaited_once()

    async def test_status_filter_valid_completed(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        result = await maint_tool_ops.list_maintenance_requests(db, status="completed")

        assert "error" not in result
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# apply_maintenance_status_update
# ---------------------------------------------------------------------------


class TestApplyMaintenanceStatusUpdate:
    @pytest.mark.parametrize(
        ("status", "expected_request", "expected_work"),
        [
            ("open", MaintenanceRequestStatus.open, None),
            ("in_progress", MaintenanceRequestStatus.work_order_created, WorkOrderStatus.in_progress),
            ("completed", MaintenanceRequestStatus.resolved, WorkOrderStatus.completed),
            ("cancelled", MaintenanceRequestStatus.closed, WorkOrderStatus.cancelled),
        ],
    )
    def test_update_success(
        self,
        status: str,
        expected_request: MaintenanceRequestStatus,
        expected_work: WorkOrderStatus | None,
    ) -> None:
        request = _make_request_obj(request_id=1)

        maint_tool_ops.apply_maintenance_status_update(request, status=status)

        assert request.request_status == expected_request
        assert request.work_order_status == expected_work

    def test_scheduled_sets_date_and_status(self) -> None:
        request = _make_request_obj(request_id=1)

        maint_tool_ops.apply_maintenance_status_update(
            request, status="scheduled", scheduled_date="2026-07-01T09:00:00"
        )

        assert request.request_status == MaintenanceRequestStatus.work_order_created
        assert request.work_order_status == WorkOrderStatus.assigned
        assert request.scheduled_for == datetime.fromisoformat("2026-07-01T09:00:00")

    def test_completed_sets_notes_and_cost(self) -> None:
        request = _make_request_obj(request_id=1)

        maint_tool_ops.apply_maintenance_status_update(
            request,
            status="completed",
            notes="Fixed the leak",
            estimated_cost=500.0,
            actual_cost=450.0,
        )

        assert request.request_status == MaintenanceRequestStatus.resolved
        assert request.completion_notes == "Fixed the leak"
        assert request.estimated_cost == 500.0
        assert request.actual_cost == 450.0
        assert request.completed_at is not None

    def test_invalid_status_transition(self) -> None:
        request = _make_request_obj(request_id=1)

        with pytest.raises(ValueError, match="Invalid status"):
            maint_tool_ops.apply_maintenance_status_update(request, status="bogus")

    def test_request_not_found(self) -> None:
        # apply_maintenance_status_update operates on an in-hand request object;
        # a null request (caller could not resolve one) raises AttributeError
        # when the function dereferences it, documenting the absence of a
        # built-in null guard.
        with pytest.raises(AttributeError):
            maint_tool_ops.apply_maintenance_status_update(None, status="open")


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
