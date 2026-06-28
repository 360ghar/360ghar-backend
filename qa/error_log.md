# Phase 2 — Error Log

Baseline run of the full suite (2060 tests): **2027 passing, 33 failing, 2 errors**.

Every failure was triaged into one of two buckets:

- **App bug** — the production code is wrong; fix the code.
- **Stale test** — the code is correct/evolved; the test is outdated. Per the
  task ("you can completely overwrite the existing Tests"), these are rewritten
  in Phase 5 rather than the code being bent to match old assumptions.

---

## A. Genuine application bugs (FIXED)

### BUG-1 — Property deletion crashes (US-200)
`DELETE /api/v1/properties/{property_id}` → `ModuleNotFoundError: No module named 'app.models.visits'`.

- **Cause:** `app/services/property/crud.py` imported `Visit` from a module that
  does not exist (`app.models.visits`). The `Visit` model lives in
  `app.models.properties`.
- **Impact:** Any property delete that reached the cleanup branch crashed with a
  500 — data could not be removed.
- **Fix:** `from app.models.properties import Visit`.
- **Verified:** `tests/unit/services/test_property_service.py::TestDeleteProperty::test_delete_property_success` green.

### BUG-2 — Maintenance status transitions all rejected (US-266)
`PATCH /api/v1/pm/maintenance/requests/{request_id}` rejected every valid status
change: `Cannot transition from 'open' to 'in_review'`.

- **Cause:** `app/services/pm_maintenance.py` `ALLOWED_TRANSITIONS` referenced
  statuses that don't exist in the `MaintenanceRequestStatus` enum
  (`in_progress`, `on_hold`) and omitted the real ones (`in_review`,
  `work_order_created`). The whole state machine was disconnected from the enum.
- **Impact:** Landlords / relationship managers could never advance a maintenance
  request — the feature was effectively dead.
- **Fix:** Rewrote `ALLOWED_TRANSITIONS` to match the enum:
  `open → {in_review, work_order_created, resolved, closed}`,
  `in_review → {work_order_created, resolved, closed, open}`,
  `work_order_created → {resolved, closed}`,
  `resolved → {closed, open}`, `closed → {}`.
- **Verified:** `tests/unit/services/pm/test_pm_maintenance_service.py::TestUpdateMaintenanceRequest::test_update_request_status` green.

---

## B. Stale tests (code is correct; tests outdated — rewritten in Phase 5)

| Test(s) | Symptom | Why it's stale |
|---------|---------|----------------|
| `tests/unit/services/test_storage_paths.py` (6) | `'avatars/{user_id}' == 'avatars'`, uuid length, path layout | Storage path scheme was redesigned (per-entity folders, uuid filenames); tests assert the old scheme. |
| `tests/unit/services/test_visit_service.py` (2) | `VisitStatus.requested != 'scheduled'`, `reschedule_suggested != 'rescheduled'` | `VisitStatus` enum values were renamed; tests assert old literals. |
| `tests/unit/core/test_config.py::test_default_cache_settings` (1) | `'./cache' == '/tmp/ghar360_cache'` | Default cache dir changed to `./cache`; test asserts old default. |
| `tests/mcp/test_admin_mcp_server.py` (9) | `AuthRequiredError: Please log in ...` | MCP auth-context test harness predates the current auth wiring; tools require an authed context the fixtures no longer inject. |
| `tests/mcp/test_user_mcp_server.py` (4) | `module ... has no attribute 'list_managed_properties' / 'create_managed_property' / 'booking_svc'` | MCP tool internals were renamed; tests patch the old symbol names. |
| `tests/mcp/test_mcp_integration.py` (1) | `AuthRequiredError` | Same MCP auth-context drift. |
| `tests/pm/test_pm_rent_pagination.py` (1) | `'...T12:00:00Z' == '...+00:00'` | Datetime serialization now emits `Z`; test asserts `+00:00`. |
| `tests/api/test_delete_account.py::test_supabase_error_returns_500` (1) | `Exception` propagates instead of 500 | Test harness needs `raise_app_exceptions=False`; the global handler returns 500 in production. |
| `tests/e2e/test_booking_complete_flow.py` (1) | `Mock has no attribute 'property_id'` | Test mock missing a field the cancel path now reads. |
| `tests/e2e/test_pm_lifecycle_flow.py` (1) | `NameError: name 'Decimal' is not defined` | Test module missing `from decimal import Decimal`. |
| `tests/unit/services/test_property_service.py` create/update (2) | `MagicMock can't be used in 'await'` | Async DB calls mocked with `MagicMock` instead of `AsyncMock`. |
| `tests/pm/test_authz.py`, `tests/pm/test_rent.py` (2 errors) | `fixture 'test_db' not found` | Renamed fixture — should be `db_session`. |

These are addressed by the Phase 5 test overhaul (clean structure + corrected
assertions), not by altering production behaviour.
