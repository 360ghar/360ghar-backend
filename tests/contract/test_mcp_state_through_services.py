"""MCP and agent tools change PM state through the PM services (wave 3d).

A tool that writes a lease, maintenance or rent field itself skips the caller's rights check,
the transition rules and the side effects of the service (for example the property's current
lease). This test reads the tool sources: no tool assigns a PM state field, and none builds
a PM row. Call the service in ``app/services/pm_*.py`` instead.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
TOOL_DIRS = (APP / "mcp", APP / "services" / "ai_agent")

# Assignments to PM state fields: obj.status = ..., obj.request_status = ..., and so on.
STATE_WRITE = re.compile(
    r"\.(?:status|request_status|work_order_status|completed_at|closed_at|scheduled_for|"
    r"current_lease_id|current_tenant_id|late_fee_assessed|termination_date|termination_reason)"
    r"\s*=(?!=)"
)
# Construction of a PM row.
PM_ROW = re.compile(
    r"\b(?:Lease|RentCharge|RentPayment|MaintenanceRequest|Expense|RentalApplication"
    r"|RentalApplicationForm|InspectionChecklist)\("
)


def _tool_sources():
    for directory in TOOL_DIRS:
        yield from sorted(directory.rglob("*.py"))


def _hits(pattern: re.Pattern[str]) -> list[str]:
    found = []
    for path in _tool_sources():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if pattern.search(line) and not line.lstrip().startswith("#"):
                found.append(f"{path.relative_to(APP.parent)}:{number}: {line.strip()}")
    return found


def test_no_tool_assigns_a_pm_state_field():
    assert _hits(STATE_WRITE) == []


def test_no_tool_builds_a_pm_row():
    assert _hits(PM_ROW) == []
