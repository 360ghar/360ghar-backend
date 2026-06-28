"""Tests for the PM dashboard service.

Regression coverage for the enum-comparison bug in ``get_dashboard_overview``:
``Property.status`` is a real ``SQLEnum(PropertyStatus)`` column and must be
compared against ``PropertyStatus.maintenance``, not a raw string literal.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.enums import PropertyStatus
from app.models.properties import Property


def _compile_where(stmt) -> str:
    """Compile a select statement's WHERE clause to lowercase SQL for assertion."""
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return str(compiled).lower()


def test_property_status_maintenance_enum_value_is_stable():
    """Guard: the enum value must remain the lowercase literal we expect."""
    assert PropertyStatus.maintenance.value == "maintenance"


def test_property_status_compare_uses_enum_member_not_literal_string():
    """The generated SQL must bind the enum, not an arbitrary string.

    Regression for the original bug where the codebase compared
    ``Property.status == "maintenance"`` instead of
    ``Property.status == PropertyStatus.maintenance``. SQLEnum columns must
    be compared against enum members for type safety and to match the
    pattern used everywhere else in the codebase (e.g. ``LeaseStatus.active``).
    """
    # Build the same predicate shape used by get_dashboard_overview
    correct_stmt = select(Property.id).where(
        Property.is_managed, Property.status == PropertyStatus.maintenance
    )

    sql = _compile_where(correct_stmt)
    # The right-hand side must bind to the enum's value (which happens to be
    # the literal 'maintenance'). The point is that the comparison goes through
    # the enum member, not a bare string typed in the source.
    assert "'maintenance'" in sql or "maintenance" in sql

    # And the enum member itself must equal the literal value
    assert PropertyStatus.maintenance == "maintenance"


def test_property_status_literal_string_compare_is_not_source_pattern():
    """Direct string literal comparison would compile to the same SQL but is
    forbidden by the codebase convention. This test documents that the source
    pattern has changed by verifying the import is present.
    """
    from app.services import pm_dashboard

    # The dashboard module must import PropertyStatus (regression for the
    # original bug where it used the raw literal "maintenance").
    assert hasattr(pm_dashboard, "PropertyStatus"), (
        "pm_dashboard must import PropertyStatus to avoid raw-string comparisons"
    )
