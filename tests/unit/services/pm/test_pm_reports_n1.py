"""Tests for the PM reports service.

Regression coverage for the N+1 query bug in ``rent_roll_report``: the original
implementation streamed properties and fired a per-property ``SELECT lease``
query. The fix issues exactly one query for properties and one batched query
for the active leases of the whole property set.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeaseStatus, UserRole
from app.models.pm_leases import Lease
from app.models.users import User


def _make_property(pid: int) -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.title = f"Property {pid}"
    return p


def _make_lease(property_id: int, *, monthly_rent=1000) -> MagicMock:
    lease = MagicMock(spec=Lease)
    lease.property_id = property_id
    lease.tenant_user_id = 100 + property_id
    lease.monthly_rent = monthly_rent
    lease.end_date = None
    lease.status = LeaseStatus.active
    lease.created_at = property_id  # newest per property (desc)
    return lease


def _is_lease_query(stmt) -> bool:
    """Return True when the select statement targets the Lease entity.

    Avoids brittle string matching: a Property select compiles to SQL that
    contains the substring 'lease' (because of the ``leases`` relationship),
    so we inspect ``column_descriptions`` instead.
    """
    return any(desc.get("entity") is Lease for desc in getattr(stmt, "column_descriptions", []))


class TestRentRollReportQueryCount:
    """Verifies the rent roll report does not regress into an N+1 pattern."""

    @pytest.mark.asyncio
    async def test_rent_roll_uses_two_queries_regardless_of_property_count(self):
        """For N properties there must be exactly 2 execute() calls:
        one for properties, one for the batched active-lease lookup.
        """
        from app.services import pm_reports

        actor = MagicMock(spec=User)
        actor.role = UserRole.user.value
        actor.id = 1
        actor.agent_id = None

        # _resolve_owner_scope returns the actor's own id (single owner)
        with patch(
            "app.services.pm_reports._resolve_owner_scope",
            new_callable=AsyncMock,
            return_value=[1],
        ) as mock_resolve:
            db = AsyncMock(spec=AsyncSession)
            execute_calls = []

            properties = [_make_property(i) for i in range(1, 6)]  # 5 properties
            leases = [_make_lease(i) for i in range(1, 4)]  # 3 occupied

            # First execute -> properties, second execute -> leases
            async def _execute(stmt):
                execute_calls.append(stmt)
                result = MagicMock()

                # Dispatch by entity, not string match: a Property select
                # compiles to SQL containing "lease" (via the leases
                # relationship), so substring matching would misroute it.
                if _is_lease_query(stmt):
                    scalars_result = MagicMock()
                    scalars_result.all.return_value = leases
                    result.scalars.return_value = scalars_result
                else:
                    scalars_result = MagicMock()
                    scalars_result.all.return_value = properties
                    result.scalars.return_value = scalars_result
                return result

            db.execute = AsyncMock(side_effect=_execute)

            result = await pm_reports.rent_roll_report(db, actor=actor)

        # Exactly 2 queries regardless of property count: 1 properties + 1 leases
        assert len(execute_calls) == 2, (
            f"Expected exactly 2 DB queries (batched), got {len(execute_calls)}. "
            "The N+1 pattern regressed: one lease query per property."
        )
        mock_resolve.assert_awaited_once()

        items, next_payload, total = result

        # Correctness: 3 occupied, 2 vacant
        assert len(items) == 5
        occupied = [r for r in items if r["occupancy"] == "occupied"]
        vacant = [r for r in items if r["occupancy"] == "vacant"]
        assert len(occupied) == 3
        assert len(vacant) == 2
        assert next_payload is None
        assert total is None

    @pytest.mark.asyncio
    async def test_rent_roll_handles_no_properties_without_lease_query(self):
        """When the property set is empty, the lease query must be skipped
        (no IN (...) against an empty list)."""
        from app.services import pm_reports

        actor = MagicMock(spec=User)
        actor.role = UserRole.user.value
        actor.id = 1
        actor.agent_id = None

        with patch(
            "app.services.pm_reports._resolve_owner_scope",
            new_callable=AsyncMock,
            return_value=[1],
        ):
            db = AsyncMock(spec=AsyncSession)
            execute_calls = []

            async def _execute(stmt):
                execute_calls.append(stmt)
                result = MagicMock()
                scalars_result = MagicMock()
                scalars_result.all.return_value = []  # no properties
                result.scalars.return_value = scalars_result
                return result

            db.execute = AsyncMock(side_effect=_execute)

            result = await pm_reports.rent_roll_report(db, actor=actor)

        # Only 1 query (the property select); no lease query for empty set.
        assert len(execute_calls) == 1, (
            f"Expected 1 query for empty property set, got {len(execute_calls)}"
        )
        items, next_payload, total = result
        assert items == []
        assert next_payload is None
        assert total is None

    @pytest.mark.asyncio
    async def test_rent_roll_picks_newest_active_lease_per_property(self):
        """If multiple active leases exist for one property, the one with the
        greatest created_at must win (per the ORDER BY created_at DESC)."""
        from app.services import pm_reports

        actor = MagicMock(spec=User)
        actor.role = UserRole.user.value
        actor.id = 1
        actor.agent_id = None

        with patch(
            "app.services.pm_reports._resolve_owner_scope",
            new_callable=AsyncMock,
            return_value=[1],
        ):
            db = AsyncMock(spec=AsyncSession)

            properties = [_make_property(1)]
            old_lease = _make_lease(1, monthly_rent=500)
            old_lease.created_at = 1
            old_lease.tenant_user_id = 111
            new_lease = _make_lease(1, monthly_rent=900)
            new_lease.created_at = 10
            new_lease.tenant_user_id = 222

            async def _execute(stmt):
                result = MagicMock()
                if _is_lease_query(stmt):
                    scalars_result = MagicMock()
                    # Simulate ORDER BY property_id, created_at DESC: newest first
                    # so setdefault picks the newest.
                    scalars_result.all.return_value = [new_lease, old_lease]
                    result.scalars.return_value = scalars_result
                else:
                    scalars_result = MagicMock()
                    scalars_result.all.return_value = properties
                    result.scalars.return_value = scalars_result
                return result

            db.execute = AsyncMock(side_effect=_execute)

            result = await pm_reports.rent_roll_report(db, actor=actor)

        items, next_payload, total = result
        assert len(items) == 1
        row = items[0]
        # The newest lease's monthly_rent wins
        assert row["monthly_rent"] == 900
        assert row["tenant_user_id"] == 222
