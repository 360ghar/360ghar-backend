# Property Management Platform (India) — Backend Implementation Plan (360 Ghar)

This plan describes the **Property Management** module of the 360 Ghar platform. It covers how to build a full property-management system (owners + relationship managers + tenants) on top of the existing 360 Ghar backend (FastAPI + SQLAlchemy 2.x async + Postgres/Supabase).

It is written to be **backward-compatible** with the existing 360 Ghar Core and 360 Stays APIs (`/api/v1/properties`, swipes, visits, bookings) while introducing a **new Property Management surface area** (`/api/v1/pm/*`) for the new mobile app.

---

## 0) Constraints / Non‑Goals (for now)

- **No vendor module**: Work orders are handled by the Relationship Manager (RM) and/or owner only.
- **No 3rd‑party integrations until last phase**:
  - Payment gateway (Razorpay/Stripe/etc), bank sync, autopay + retries
  - KYC verification providers
  - Background check providers
  - E‑signature providers
- Build what we can with **ledger + manual workflows** first, but **design DB/API** so integrations can be added later without rewriting core tables.
- Keep logic in `app/services/`, keep route handlers thin, and add new endpoints under `app/api/api_v1/endpoints/`.

---

## 1) Current Backend Snapshot (what we will reuse)

**Auth & Users**
- Supabase Auth JWT verification (`app/core/auth.py`, `app/api/api_v1/dependencies/auth.py`)
- `users` table + SQLAlchemy model `app/models/users.py` already includes `role`, contact fields, and JSON settings fields.

**Properties**
- `properties` table + model `app/models/properties.py` already covers most “property basics” (type, address, photos, rent amount, deposit).
- `property_images`, `amenities`, `property_amenities` already exist.

**Agents**
- `agents` table + model `app/models/agents.py` exists; today it’s used for marketplace “agent assignment”.
- We will map “Relationship Manager” → `agents` (plus a small assignment layer).

**Visits & Bookings**
- `visits` is reusable for inspections.
- `bookings` should remain for short-stay/marketplace flows; do **not** repurpose for long-term rent/leases.

**Notifications**
- Push + in-app logging is already implemented (`app/services/notifications.py`, `app/services/notification_dispatcher.py`, `app/api/api_v1/endpoints/notifications.py`).
- APScheduler is available (`app/services/notification_scheduler.py`) for periodic reminders (opt-in via config).

**File storage**
- Cloudinary storage service exists (`app/services/storage/`) and supports images, videos, and documents.

**Auth & onboarding additions (for the Property Management app)**
- Clients authenticate directly with Supabase SDK (password and/or OTP), then call backend with bearer access tokens.
- Backend does not expose `/api/v1/auth/*` session endpoints.
- Profile setup remains `PUT /api/v1/users/profile/`; additional “owner/tenant profile” fields can live in:
  - `users.preferences` JSON (fastest), or
  - dedicated profile tables (cleaner; see section 3.3).
- Owner KYC is admin-driven:
  - Admin endpoint(s) to upload KYC docs into `documents` and set KYC status (stored in `owner_profiles` or `users.preferences`).

---

## 2) High-Level Architecture for Property Management

### 2.1 API Surface Strategy
Add a new logical API namespace so we do not break existing clients:

- Existing marketplace API stays as-is:
  - `/api/v1/properties`, `/swipes`, `/visits`, `/bookings`, etc.
- New property-management API under:
  - `/api/v1/pm/*` (new routers)

This allows the property-management mobile app to use a dedicated API with RBAC + domain-specific payloads without impacting discovery endpoints.

### 2.2 “Multi-tenancy” (data partitioning)
The “tenant boundary” is **the property owner’s portfolio**.

- Owner has many `Property` rows (`properties.owner_id`)
- RM can be assigned to many owners; access is granted via `owner_agent_assignments`
- Tenants access data through an **active lease** that links them to a property and owner

### 2.3 RBAC Model (practical and backward-compatible)
Keep `users.role` for coarse roles (`user`, `agent`, `admin`) to avoid breaking existing flows.

Use **resource-based authorization** for property management:
- Owner access: user is `properties.owner_id` (or admin).
- RM access: user has `role=agent` and is linked to an `Agent` record and has an **active** assignment to the owner (optionally scoped to properties).
- Tenant access: user has a linked tenant profile and an **active lease** for the property/lease they’re trying to access.

Implement as reusable helpers (planned):
- `app/services/pm_authz.py` (or similar) with functions like:
  - `assert_can_access_property(current_user, property_id)`
  - `assert_can_access_lease(current_user, lease_id)`
  - `assert_can_manage_owner_portfolio(current_user, owner_id)`

---

## 3) Data Model (DB + SQLAlchemy) — Entities to Add/Extend

> Naming convention: SQL tables in snake_case; new models under `app/models/pm/*` (recommended) or `app/models/*.py` if we keep it flat.

### 3.1 New Enums (`app/models/enums.py`)
Add enums required for tenant management, leasing, payments, maintenance, documents, inspections, messaging.

Minimum set (MVP → expanded later):
- `TenantStatus`: `applicant`, `approved`, `active`, `notice_period`, `vacated`, `rejected`
- `LeaseStatus`: `draft`, `pending_signature`, `active`, `expiring_soon`, `expired`, `terminated`, `renewed`
- `RentChargeStatus`: `pending`, `partial`, `paid`, `overdue`, `waived`
- `ExpenseCategory`: `maintenance`, `repairs`, `insurance`, `property_tax`, `hoa`, `utilities`, `marketing`, `legal`, `other`
- `MaintenanceUrgency`: `emergency`, `high`, `medium`, `low`
- `MaintenanceCategory`: `plumbing`, `electrical`, `hvac`, `appliance`, `structural`, `pest_control`, `cleaning`, `other`
- `MaintenanceRequestStatus`: `open`, `in_review`, `work_order_created`, `resolved`, `closed`
- `WorkOrderStatus`: `created`, `assigned`, `in_progress`, `completed`, `closed`, `cancelled`
- `DocumentType`: `lease_agreement`, `id_proof`, `address_proof`, `income_proof`, `inspection_report`, `receipt`, `invoice`, `property_deed`, `insurance_policy`, `other`
- `InspectionType`: `move_in`, `move_out`, `routine`
- `MessageThreadType`: `lease`, `maintenance`, `general`

### 3.2 Extend `Property` (existing `app/models/properties.py`)
Add “managed rental” fields without breaking discovery:

- `is_managed` (bool, default false)
- `management_status` (enum: `draft`, `active`, `archived`) or `is_active`/`is_draft`
- Default rent settings (only as defaults; lease may override):
  - `payment_due_day` (int, 1–28)
  - `grace_period_days` (int)
  - `late_fee_policy` (JSON: fixed or percentage)
- Convenience pointers (optional but useful):
  - `current_lease_id` nullable FK → `leases.id`
  - `current_tenant_id` nullable FK → `tenants.id`

Notes:
- Occupancy (Occupied/Vacant) should be computed from the **active lease**, not stored redundantly.
- Keep existing listing fields (`is_available`, `status`, `purpose`) untouched for marketplace compatibility.

### 3.3 Extend `User` (existing `app/models/users.py`) — KYC support
KYC is added by Admin portal, not by users; we still need storage.

Two options (choose 1):
Add KYC at User level but optional, so a user whether a owner, tenant, etc. can have KYC Docs 
- KYC docs go into `documents` table and are linked via `user_id`
   
### 3.4 Owner ↔ Relationship Manager assignment

Planned models (new file):
- `app/models/pm_assignments.py` (or similar module)
 No new module required, the Agent assigned to user will be the relationship manager to manage their properties.

### 3.5 Tenant + Application + Onboarding

User model can be tied to a lease 

Planned models (new file):
- `app/models/pm_tenants.py`

Core tenant profile:

Application form system (so owners can share a link):
- `rental_applications`
  - `id`, `form_id`, `property_id`
  - `status` (submitted/approved/rejected/etc)
  - `answers` JSON (MVP; or normalized answers table)
  - `submitted_at`, `decision_at`, `created_at`, `updated_at`
    - `application_data` JSON (employment, references, pets, etc; can be normalized later)
  - `emergency_contacts` JSON

Docs upload for applications:
- Store as `documents` records linked via `rental_application_id` (or a link table).

### 3.6 Lease Management (long‑term rentals)

Planned models (new file):
- `app/models/pm_leases.py`

Tables:
- `leases`
  - `id`
  - `property_id` (FK → `properties.id`)
  - `owner_id` (FK → `users.id`) for faster auth checks
  - `tenant_id` (FK → `tenants.id`)
  - `status` (enum)
  - `start_date`, `end_date`
  - `monthly_rent`, `security_deposit`
  - `late_fee_amount`, `late_fee_percentage`, `grace_period_days`
  - `payment_due_day`
  - `lease_terms` JSON, `special_clauses` text
  - signature placeholders: `signed_by_tenant_at`, `signed_by_owner_at`
  - `lease_document_id` (FK → `documents.id`) for uploaded/signed lease PDF
  - `created_at`, `updated_at`

### 3.7 Rent Collection & Ledger (manual-first, gateway later)

Planned models (new file):
- `app/models/pm_finance.py`

Use a 2-table ledger to support partial payments and future gateway integration:
- `rent_charges` (what is due)
  - `id`, `lease_id`, `property_id`, `owner_id`, `tenant_id`
  - `period_start`, `period_end` (or `billing_month` as YYYY-MM)
  - `due_date`
  - `amount_due`
  - `late_fee_assessed`
  - `status` (enum)
  - `created_at`, `updated_at`
- `rent_payments` (what is paid)
  - `id`, `charge_id`, `lease_id`, `property_id`, `owner_id`, `tenant_id`
  - `paid_at`, `amount_paid`
  - `payment_method` (bank_transfer/cash/check/card as string/enum)
  - `reference` (UTR/cheque/txn id), `notes`
  - `receipt_document_id` (FK → `documents.id`, optional)
  - `created_at`, `updated_at`

Late fee logic (backend-owned):
- Compute using lease (or property default) policy; assess after `due_date + grace_period_days`.
- Keep assessment idempotent (safe to run from a daily scheduler).

### 3.8 Expense Tracking

Planned models (new file):
- `app/models/pm_finance.py` (same module as rent)

Tables:
- `expenses`
  - `id`, `property_id`, `owner_id`
  - `category` enum
  - `amount`, `expense_date`, `description`, `notes`
  - `receipt_document_id` (FK → `documents.id`)
  - recurrence (phase 2): `is_recurring`, `recurrence_rule` JSON, `next_due_date`
  - `created_at`, `updated_at`

### 3.9 Maintenance Requests + Work Orders (no vendors)

Planned models (new file):
- `app/models/pm_maintenance.py`

Tables:
- `maintenance_requests`
  - `id`, `property_id`, `lease_id` (optional), `tenant_id`, `owner_id`
  - `category`, `urgency`, `status`
  - `title`, `description`
  - `preferred_contact_method`, `availability_notes`
  - attachments via `documents` (better ACL than JSON arrays)
  - `created_at`, `updated_at`
  - `status`, `priority`, `category`
  - `estimated_cost`, `actual_cost`
  - `scheduled_for`, `completed_at`, `closed_at`
  - completion docs via `documents` (invoice, completion photos)

### 3.10 Document Vault (permissions-first)

Planned models (new file):
- `app/models/pm_documents.py`

Tables:
- `documents`
  - `id`
  - `owner_id` (FK → `users.id`) (owner “owns” the document)
  - optional links: `property_id`, `tenant_id`, `lease_id`, `maintenance_request_id`, `rental_application_id`
  - `document_type` enum, `title`
  - file metadata: `file_url`, `file_path`, `mime_type`, `file_size`
  - sharing: `shared_with_tenant`, `shared_with_agent`
  - versioning: `version`, `replaces_document_id` (optional)
  - `created_by_user_id`, `created_at`, `updated_at`

Storage decision (recommended):
- Use a private Supabase bucket for documents and serve via signed URLs or an authenticated proxy download endpoint.

### 3.11 Inspections (Move-in/Move-out checklists)

Planned models (new file):
- `app/models/pm_inspections.py`

Tables:
- `inspection_checklists`
  - `id`, `property_id`, `lease_id`, `owner_id`
  - `inspection_type` enum
  - `conducted_by_user_id` (FK → `users.id`), `conducted_at`
  - `rooms_data` JSON
  - signatures: `tenant_signature_document_id`, `owner_signature_document_id`
  - `signed_by_tenant_at`, `signed_by_owner_at`
  - `created_at`, `updated_at`


## 4) API Modules & Endpoints (new `/api/v1/pm/*` surface)

Add routers in `app/api/api_v1/endpoints/` and wire them in `app/api/api_v1/api.py`.

### 4.1 Router Map
- `pm_dashboard.py` → `/pm/dashboard`
- `pm_properties.py` → `/pm/properties`
- `pm_assignments.py` → `/pm/assignments`
- `pm_applications.py` → `/pm/applications` (+ public `GET /pm/public/applications/{slug}`)
- `pm_tenants.py` → `/pm/tenants`
- `pm_leases.py` → `/pm/leases`
- `pm_rent.py` → `/pm/rent`
- `pm_expenses.py` → `/pm/expenses`
- `pm_maintenance.py` → `/pm/maintenance`
- `pm_documents.py` → `/pm/documents`
- `pm_inspections.py` → `/pm/inspections`
- `pm_reports.py` → `/pm/reports`

### 4.2 Key Endpoints (MVP first)

Dashboard (Owner/RM):
- `GET /pm/dashboard/overview` → counts, revenue, outstanding, occupancy, upcoming
- `GET /pm/dashboard/activity` → recent activity timeline (computed from tables)

`/pm/dashboard/overview` should be computed (not stored) from the core tables:
- Total properties: count of `properties` where `is_managed=true` and accessible to the caller (owner scope or RM assignment).
- Occupancy: count properties with an **active** `leases` row (occupied) vs no active lease (vacant); “under maintenance” can be derived from `properties.status=maintenance` or open work orders.
- Monthly revenue: sum of `rent_payments.amount_paid` by `paid_at` month; compare current vs previous month.
- Outstanding rent: per `rent_charges` compute `(amount_due + late_fee_assessed) - sum(payments)` for unpaid/partial charges; expose tenant-level breakdown.
- Upcoming expenses: sum of `expenses` in date range (and `next_due_date` for recurring expenses in phase 2).

Managed Properties:
- `POST /pm/properties` → create managed property (sets `is_managed=true`)
- `GET /pm/properties` → list owner portfolio (filters: occupied/vacant/maintenance, search)
- `GET /pm/properties/{property_id}` → property mgmt view (tenant, lease, rent, maintenance, expenses, docs)
- `PATCH /pm/properties/{property_id}` → update mgmt fields (rent defaults, management status)

Owner ↔ RM Assignment:
- `POST /pm/assignments` (owner/admin) → assign RM to owner (scoped or all)
- `GET /pm/assignments` (owner/admin) → list assignments
- `PATCH /pm/assignments/{id}` → enable/disable, scope changes

Tenant Applications:
- `POST /pm/applications/forms` (owner/RM) → create application form
- `GET /pm/applications/forms/{id}` → form details
- `GET /pm/public/applications/{slug}` (public) → fetch application form for prospects
- `POST /pm/public/applications/{slug}/submit` (public) → submit application
- `POST /pm/applications/{application_id}/decision` (owner/RM) → approve/reject (creates tenant + optional invite)

Tenants:
- `GET /pm/tenants` (owner/RM) → list tenants across portfolio
- `GET /pm/tenants/{tenant_id}` (owner/RM/tenant-self) → details + leases

Leases:
- `POST /pm/leases` (owner/RM) → create lease for property + tenant
- `GET /pm/leases` (owner/RM) → list/filter leases
- `GET /pm/leases/{lease_id}` (owner/RM/tenant) → lease details
- `POST /pm/leases/{lease_id}/upload-signed` → attach signed doc (e-sign later)
- `POST /pm/leases/{lease_id}/renew` → renewal workflow (creates new lease)
- `POST /pm/leases/{lease_id}/terminate` → termination workflow

Rent Ledger:
- `POST /pm/rent/charges/generate` (owner/RM/admin, idempotent) → generate upcoming charges
- `GET /pm/rent/charges` (owner/RM/tenant) → due/overdue
- `POST /pm/rent/payments` (owner/RM) → record payment (manual)
- `POST /pm/rent/payments` (tenant) → “I paid” claim, stored as pending; the owner confirms it with `POST /pm/rent/payments/{payment_id}/settle`
- `GET /pm/rent/payments` → payment history

Expenses:
- `POST /pm/expenses` (owner/RM) → record expense + receipt
- `GET /pm/expenses` → filter by property/date/category

Maintenance & Work Orders:
- `POST /pm/maintenance/requests` (tenant) → submit request
- `GET /pm/maintenance/requests` (owner/RM/tenant) → list requests
- `PATCH /pm/maintenance/requests/{id}` (owner/RM) → triage/status
- `PATCH /pm/maintenance/requests/{id}` (owner/RM) → status updates + costs + completion

Documents:
- `POST /pm/documents/upload` → upload doc + metadata
- `GET /pm/documents` → list/filter by property/lease/tenant/type
- `PATCH /pm/documents/{id}` → share/unshare, title, version bump
- `GET /pm/documents/{id}/download` → signed URL / proxy download (secure)

Inspections:
- `POST /pm/inspections` → create move-in/out checklist
- `GET /pm/inspections?lease_id=...` → list
- `GET /pm/inspections/{id}` → details
- `POST /pm/inspections/{id}/sign` → attach signature docs

Reports:
- `GET /pm/reports/rent-roll`
- `GET /pm/reports/income`
- `GET /pm/reports/expenses`
- `GET /pm/reports/pnl`
- `GET /pm/reports/occupancy`
- `GET /pm/reports/maintenance`
- Export (MVP): CSV download; PDF/Excel later.

---

## 5) Services & Repositories (implementation structure)

New services (`app/services/`):
- `pm_properties.py` — managed property CRUD + portfolio queries
- `pm_assignments.py` — owner↔RM assignment logic
- `pm_applications.py` — application forms, submission, decisioning
- `pm_tenants.py` — tenant profiles, onboarding
- `pm_leases.py` — lease lifecycle (create/renew/terminate)
- `pm_rent.py` — charge generation, late fees, payment posting, outstanding calculations
- `pm_expenses.py` — expense CRUD + recurring schedule (phase 2)
- `pm_maintenance.py` — request triage, work order lifecycle, SLA/metrics
- `pm_documents.py` — upload metadata, ACL checks, versioning
- `pm_inspections.py` — checklist + comparison helpers
- `pm_dashboard.py` — dashboard aggregations
- `pm_reports.py` — reporting queries + export formatting
- `pm_authz.py` — shared authorization helpers (critical)

New repositories (`app/repositories/`):
- `pm_*_repository.py` per new model (tenant/lease/rent/expense/maintenance/documents/messages/assignments)

---

## 6) Scheduled Jobs & Notifications (manual-first; integrations later)

Use APScheduler (opt-in via `ENABLE_NOTIF_SCHEDULER`) and the existing notification dispatcher.

Scheduled jobs (idempotent):
- Rent reminders: due in 7/3/1 days; and daily overdue reminders
- Late fee assessment: apply once after grace period
- Lease expiry reminders: 90/60/30 days before `lease.end_date`
- Recurring expenses materialization (phase 2)

Notification type keys to add (`app/services/notification_config.py`):
- `rent_due`, `rent_overdue`, `rent_received`
- `maintenance_submitted`, `work_order_updated`, `work_order_completed`
- `lease_expiring`, `lease_renewal_offer`
- `document_shared`, `signature_required`
- reuse existing `chat_message` or add `pm_message`

---
