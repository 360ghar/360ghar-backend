"""Unit tests for the shared MCP dashboard tool_ops layer.

Exercises ``compute_dashboard_metrics`` in ``app/mcp/tool_ops/dashboard.py``
directly, mocking every ``db.execute`` call to return scalar aggregation
results. This verifies that the function:
- Translates the four aggregate queries (properties, leases, maintenance, rent)
  into the documented dashboard dict shape.
- Computes the occupancy rate from active leases vs. total properties.
- Short-circuits to an all-zero dashboard when ``owner_ids`` is an empty list.
- Honors the ``owner_ids`` filter path without short-circuiting.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.mcp.tool_ops.dashboard import compute_dashboard_metrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value):
    """Build a mock ``db.execute()`` result with a sync ``scalar()``.

    The dashboard code does ``(await db.execute(...)).scalar()`` (no second
    await), so the method must be a sync ``MagicMock`` returning the value.
    """
    result = MagicMock()
    result.scalar = MagicMock(return_value=value)
    return result


def _build_db(*scalars):
    """Create an ``AsyncMock`` session whose ``execute`` returns scalars in order."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(v) for v in scalars])
    return db


# ---------------------------------------------------------------------------
# compute_dashboard_metrics
# ---------------------------------------------------------------------------


class TestComputeDashboardMetrics:
    async def test_full_portfolio(self) -> None:
        # Order: total_properties, active_leases, open_maintenance, monthly_rent
        db = _build_db(10, 7, 3, 700000)

        result = await compute_dashboard_metrics(db)

        assert result["properties"] == {"total": 10, "occupied": 7, "vacant": 3}
        assert result["leases"] == {"active": 7}
        assert result["occupancy_rate"] == 70.0
        assert result["maintenance"] == {"open": 3}
        assert result["rent"] == {"expected_monthly": 700000.0}
        # All four aggregates are executed exactly once.
        assert db.execute.await_count == 4

    async def test_empty_portfolio(self) -> None:
        # An empty owner_ids list short-circuits to a zeroed dashboard with no
        # database calls.
        db = AsyncMock()

        result = await compute_dashboard_metrics(db, owner_ids=[])

        assert result == {
            "properties": {"total": 0, "occupied": 0, "vacant": 0},
            "leases": {"active": 0},
            "occupancy_rate": 0.0,
            "maintenance": {"open": 0},
            "rent": {"expected_monthly": 0.0},
        }
        db.execute.assert_not_awaited()

    async def test_all_occupied(self) -> None:
        # Every property has an active lease -> 100% occupancy, zero vacant.
        db = _build_db(5, 5, 0, 125000)

        result = await compute_dashboard_metrics(db)

        assert result["properties"] == {"total": 5, "occupied": 5, "vacant": 0}
        assert result["occupancy_rate"] == 100.0
        assert result["leases"]["active"] == 5

    async def test_all_vacant(self) -> None:
        # No active leases -> 0% occupancy, every property vacant.
        db = _build_db(5, 0, 0, 0)

        result = await compute_dashboard_metrics(db)

        assert result["properties"] == {"total": 5, "occupied": 0, "vacant": 5}
        assert result["occupancy_rate"] == 0.0
        assert result["leases"]["active"] == 0
        assert result["rent"]["expected_monthly"] == 0.0

    async def test_with_overdue_rent(self) -> None:
        # The dashboard computes expected_monthly rent from active leases; this
        # exercises the rent-aggregation branch with a non-zero sum.
        db = _build_db(3, 2, 0, 50000)

        result = await compute_dashboard_metrics(db)

        assert result["rent"]["expected_monthly"] == 50000.0
        assert result["properties"]["occupied"] == 2
        assert result["occupancy_rate"] == round(2 / 3 * 100, 1)

    async def test_with_open_maintenance(self) -> None:
        # Exercises the maintenance-aggregation branch with open requests.
        db = _build_db(2, 1, 5, 20000)

        result = await compute_dashboard_metrics(db)

        assert result["maintenance"] == {"open": 5}
        assert result["leases"]["active"] == 1

    async def test_agent_filtered_by_owner(self) -> None:
        # When owner_ids is provided (agent-scoped view), the function must NOT
        # short-circuit and must run all four filtered aggregates.
        db = _build_db(4, 3, 1, 60000)

        result = await compute_dashboard_metrics(db, owner_ids=[10], managed_only=True)

        assert result["properties"] == {"total": 4, "occupied": 3, "vacant": 1}
        assert result["leases"]["active"] == 3
        assert result["maintenance"]["open"] == 1
        assert result["rent"]["expected_monthly"] == 60000.0
        # owner_ids is not an empty list, so all four queries execute.
        assert db.execute.await_count == 4

    async def test_null_scalar_results_default_to_zero(self) -> None:
        # Defensive: if the DB returns None for an aggregate (e.g. no rows),
        # the function coerces to 0 rather than crashing.
        db = _build_db(None, None, None, None)

        result = await compute_dashboard_metrics(db)

        assert result["properties"] == {"total": 0, "occupied": 0, "vacant": 0}
        assert result["occupancy_rate"] == 0.0
        assert result["rent"]["expected_monthly"] == 0.0
