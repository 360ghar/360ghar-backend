# Lease

Leases are the legal backbone of the Property Management module. A lease binds an owner, a tenant, and a property for a fixed term with a rent schedule. Once active, a lease spawns rent charges, maintenance requests, inspection checklists, and documents - the entire PM lifecycle hangs off this one row.

Active contributors: Saksham, Ravi

## Model

File: `app/models/pm_leases.py`

The `Lease` table is indexed for the three most common query patterns: by owner (`idx_leases_owner_id`), by property (`idx_leases_property_id`), and by tenant (`idx_leases_tenant_user_id`). A status index and an end-date index support dashboard "expiring soon" queries.

Key columns:

- `property_id` - `ON DELETE CASCADE` from `properties`
- `owner_id` - the property owner (a `User`)
- `tenant_user_id` - nullable. The tenant if they have a platform account. `ON DELETE SET NULL` so deleting a tenant user does not delete the lease.
- `tenant_name`, `tenant_phone`, `tenant_email` - denormalized tenant contact for pre-account tenants
- `status` - `LeaseStatus` enum (`draft`, `pending_signature`, `active`, `expiring_soon`, `expired`, `terminated`, `renewed`)
- `start_date`, `end_date` - the lease term
- `monthly_rent`, `security_deposit` - `Numeric(10, 2)` currency fields
- `late_fee_amount`, `late_fee_percentage`, `grace_period_days`, `payment_due_day` - rent collection configuration
- `lease_terms` - JSON dict for freeform terms
- `special_clauses` - free text
- `signed_by_tenant_at`, `signed_by_owner_at` - signature timestamps
- `termination_date`, `termination_reason` - populated when a lease is terminated early
- `lease_document_id` - optional FK to the `documents` table

## Relationships

A lease owns its downstream PM entities:

- `RentCharge` - one per month, cascade-deleted with the lease
- `MaintenanceRequest` - linked but not cascade-deleted (history preserved)
- `InspectionChecklist` - move-in, move-out, and routine inspections
- `Document` - the signed lease PDF and supporting documents

## Lifecycle and termination

A lease moves `draft` -> `pending_signature` -> `active` -> `expiring_soon` -> `expired`. The `expiring_soon` status is set by a scheduled job when `end_date` is within a configurable window. Renewal creates a new `Lease` row with status `renewed` linked to the same property, and the old lease is marked `expired` rather than `terminated`.

Termination is a distinct path. The owner or admin calls `owner_leases_terminate` (or the admin MCP equivalent), which sets `termination_date`, `termination_reason`, and flips `status` to `terminated`. The lifespan startup applies lightweight DDL to ensure `termination_date` and `termination_reason` columns exist, since they were added after the initial migration.

## REST and MCP surfaces

The `/api/v1/pm/leases` router covers create, list, get, and terminate. Both MCP servers expose lease tools: `owner_leases_list`, `owner_leases_get`, `owner_leases_terminate` on the user server; `agent_leases_list`, `agent_leases_create`, `agent_leases_terminate` on the admin server. See [features/property-management.md](../features/property-management.md).
