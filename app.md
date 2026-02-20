# Property Management Owner Mobile App — UI/UX Specification (India)

This document defines the **UI/UX** for a standalone **Property Management mobile app for Owners only** (for now), powered by the existing 360Ghar backend plus the new **Property Management (PM)** APIs implemented in this repository.

**Backend surfaces used by the app**
- Property Management: `/api/v1/pm/*`
- Public rental applications (shared link, no login): `/api/v1/pm/public/*`

---

## 0) Scope (Owner-only)

### 0.1 What is in scope
- Owner can manage the full PM lifecycle from the app:
  - Properties, leases, tenants directory, rent charges + payments (manual ledger), expenses, maintenance/work orders, documents, inspections, and reports.
  - Rental application forms + reviewing submissions via a public share link flow.
  - Relationship Manager assignment (if the Owner already knows the `agent_id` / is pre-assigned).

### 0.2 What is explicitly out of scope (for this app release)
- A dedicated **Tenant** app experience (tenant payments and tenant maintenance requests can be added later).
- A dedicated **Relationship Manager (Agent)** app experience (agents can be supported later).
- Any third-party integrations: payment gateways, KYC verification providers, e-signature, background checks, accounting sync.
- Real-time chat/communication hub (no backend module yet).

---

## 1) Backend Integration Contract (Mobile ↔ API)

### 1.1 Base URL + headers
- Base URL: `https://<env-domain>` (dev/stage/prod)
- All PM APIs are under: `https://<env-domain>/api/v1`
- Auth header on all authenticated calls:
  - `Authorization: Bearer <access_token>`
  - `Content-Type: application/json` (except multipart uploads)

### 1.3 Pagination + list patterns
Most list endpoints support `limit` and `offset` (default `limit=50`).
- Use pull-to-refresh to reload from `offset=0`.
- Use infinite scroll or “Load more” to increment `offset += limit`.

### 1.4 Document upload & linking (central pattern)
All attachments (lease PDF, payment proof, invoices, inspection signatures) are **documents**.
1) Upload a file → get a `document_id`
2) Use the `document_id` when creating/updating the target entity (lease/payment/expense/inspection)

Upload:
- `POST /api/v1/pm/documents/upload` (`multipart/form-data`)
  - `file` (binary)
  - `document_type` (enum)
  - `title` (string)
  - optional link fields: `property_id`, `lease_id`, `maintenance_request_id`, `rental_application_id`, `user_id`
  - optional share flags: `shared_with_tenant`, `shared_with_agent`

Download (viewer):
- `GET /api/v1/pm/documents/{document_id}/download`

### 1.5 Status & enums (UI must reflect backend)
The UI must render status chips exactly as backend returns them.
- Property: `management_status` on property (`active` / `draft` / etc.)
- Lease: `status` (`draft`, `active`, `terminated`, `expired`, etc.)
- Rent charge: `status` (`pending`, `partial`, `paid`, `overdue`, etc.)
- Maintenance: `request_status` and `work_order_status`

---

## 2) Navigation (Owner App IA)

Use **5 bottom tabs** + a **Floating Action Button (FAB)**.

**Tabs**
1) **Home** (Dashboard + Tasks)
2) **Properties** (Portfolio)
3) **Tenants** (Directory + tenant insights)
4) **Finance** (Rent charges/payments + expenses)
5) **More** (Maintenance, Applications, Leases, Documents, Inspections, Reports, Settings)

**FAB (global quick actions)**
- Add Property
- Create Lease
- Create Application Form
- Generate Rent Charges
- Record Rent Payment
- Add Expense
- Create Maintenance Request
- Upload Document

---

## 3) Global UX Rules (build once, reuse everywhere)

### 3.1 India-first formatting
- Currency: `₹` with Indian commas (`₹1,25,000`)
- Dates: `27 Dec 2025` (and show timezone where relevant)
- Phone: `+91` default, normalize input to E.164

### 3.2 List screens must always include
- Search (if endpoint supports `q`, otherwise local search)
- Filters sheet (status + property + date range)
- Empty state with a clear CTA
- “Last updated” timestamp (optional)

### 3.3 Forms must always include
- Inline validation + 422 error mapping
- Draft saving (local) for long forms (Property/Lease/Application/Inspection)
- Upload progress + retry for attachments

### 3.4 “Tasks” are computed (no single API)
MVP Tasks are a client-side computed feed from existing endpoints:
- Overdue/Pending rent charges: `GET /api/v1/pm/rent/charges?status=overdue|pending|partial`
- Open maintenance requests: `GET /api/v1/pm/maintenance/requests?request_status=open|in_review`
- Leases expiring soon: `GET /api/v1/pm/leases` then client-side filter by `end_date <= today+30`
- Applications pending decision: `GET /api/v1/pm/applications?status=pending`

---

## 4) Screen-by-Screen Spec (Owner MVP)

Each screen below includes: purpose, key UI, and APIs used.

### 4.1 Splash / Session Restore
**Purpose**
- Decide if user is authenticated; route to Home or Login.

**Behavior**
- If token exists → call any lightweight authenticated endpoint to validate session:
  - `GET /api/v1/pm/dashboard/overview`
- If 401 → clear token → go to Login.

### 4.2 Login — Phone OTP
**Screen: Enter Phone**
- Input: phone
- CTA: Send OTP
- API: Supabase client SDK `auth.signInWithOtp({ phone })`

**Screen: Verify OTP**
- 6-digit OTP
- CTA: Verify
- API: Supabase client SDK `auth.verifyOtp({ phone, token, type: 'sms' })`

**Post-login**
- Route to Profile Setup if `full_name` missing; else Home.

### 4.3 Profile Setup / Profile Edit
**Screen: Profile**
- Fields: full name, email (optional), phone (read-only), profile photo (optional)
- APIs:
  - `GET /api/v1/users/profile/`
  - `PUT /api/v1/users/profile/` (save profile)

---

## 5) Home Tab

### 5.1 Home — Dashboard
**Purpose**
- Owner’s portfolio snapshot + quick entry points.

**UI**
- KPI cards (tap to drill):
  - Total properties
  - Occupied / Vacant / Under maintenance
  - This month revenue vs previous month
  - Outstanding rent total
  - Upcoming expenses total
- Quick Actions grid (mirrors FAB)
- Recent Activity timeline

**APIs**
- `GET /api/v1/pm/dashboard/overview`
- `GET /api/v1/pm/dashboard/activity?limit=20`

**Empty states**
- No properties → show “Add your first property” CTA.

### 5.2 Home — Tasks (Computed)
**Purpose**
- A prioritized “what needs attention” list.

**UI**
- Sections (each tappable):
  - Rent overdue
  - Rent pending (this month)
  - Maintenance open (Emergency/High first)
  - Leases expiring soon
  - Applications pending decision

**APIs (fan-out)**
- `GET /api/v1/pm/rent/charges?status=overdue`
- `GET /api/v1/pm/rent/charges?status=pending`
- `GET /api/v1/pm/maintenance/requests?request_status=open`
- `GET /api/v1/pm/leases` (client filter for expiring)
- `GET /api/v1/pm/applications?status=pending`

---

## 6) Properties Tab (Portfolio)

### 6.1 Properties — List
**Purpose**
- Browse/search all managed properties.

**UI**
- Search bar
- Filters:
  - Occupancy: occupied/vacant (`occupancy` query param)
  - Status: management status (client-side filter using property fields)
- Property card:
  - Title, address snippet
  - Occupancy chip (derived from `current_lease_id` / active lease on detail)
  - Quick stats: rent (if available), open maintenance count (optional)

**API**
- `GET /api/v1/pm/properties?occupancy=occupied|vacant&q=<text>&limit=50&offset=0`

### 6.2 Property — Detail (Tabbed)
**Purpose**
- Single source of truth for a property: lease, rent, maintenance, expenses, documents, inspections.

**Header**
- Property title + status chip
- “Call tenant” quick action (if tenant phone exists in active lease)

**API**
- `GET /api/v1/pm/properties/{property_id}` returns:
  - `property`
  - `active_lease` (nullable)

**Subsections (tabs)**
1) **Overview**
   - Specs, address, photos, management settings (due day, grace, late fee policy)
   - CTA: “Edit management settings”
   - API: `PATCH /api/v1/pm/properties/{property_id}`
2) **Lease**
   - Active lease summary (or “No active lease”)
   - CTAs: Create lease / Upload signed lease / Renew / Terminate
   - APIs: see Leases module
3) **Rent**
   - Charges list filtered to this property
   - Payments list filtered to this property
   - APIs:
     - `GET /api/v1/pm/rent/charges?property_id=<id>`
     - `GET /api/v1/pm/rent/payments?property_id=<id>`
4) **Expenses**
   - Expense list filtered to this property
   - API: `GET /api/v1/pm/expenses?property_id=<id>`
5) **Maintenance**
   - Requests filtered to this property
   - API: `GET /api/v1/pm/maintenance/requests?property_id=<id>`
6) **Documents**
   - Document vault filtered to this property
   - API: `GET /api/v1/pm/documents?property_id=<id>`
7) **Inspections**
   - Inspection list filtered to this property
   - API: `GET /api/v1/pm/inspections?property_id=<id>`

### 6.3 Add Property (Wizard)
**Purpose**
- Create a managed property in Owner portfolio.

**Flow**
- Step 1: Basics (title, type, purpose, base price, address)
- Step 2: Details (beds/baths/area, optional photos/amenities)
- Step 3: PM defaults (due day, grace days, management status)

**API**
- `POST /api/v1/pm/properties?management_status=active&payment_due_day=1&grace_period_days=5`
- Body: `PropertyCreate` (see `/api/v1/docs` for full shape)

---

## 7) Tenants Tab

### 7.1 Tenants — Directory
**Purpose**
- List tenant users across the owner’s portfolio (platform users only).

**UI**
- Search (local)
- Tenant card: name, phone, active leases count

**API**
- `GET /api/v1/pm/tenants?limit=50&offset=0`

**Important limitation**
- Leases created without `tenant_user_id` (only `tenant_name/phone/email`) will not appear in this directory.

### 7.2 Tenant — Detail
**Purpose**
- Tenant’s profile + lease history + quick finance/maintenance drill-down.

**UI**
- Contact actions: call, WhatsApp
- Leases list (active + historic)
- Quick links:
  - Rent charges for tenant (client uses lease ids to fetch charges)
  - Maintenance requests for tenant (if tenant_user_id exists)

**API**
- `GET /api/v1/pm/tenants/{tenant_user_id}`

---

## 8) Finance Tab (Rent + Expenses)

### 8.1 Rent — Charges List
**Purpose**
- Owner’s rent ledger (manual-first).

**UI**
- Summary chips: Pending / Partial / Paid / Overdue
- Filters: property, status, billing month (client-side month grouping)
- Charge row:
  - Billing month, due date, amount due
  - Paid total, outstanding
  - Status chip
- CTA: Record payment

**API**
- `GET /api/v1/pm/rent/charges?status=<status>&property_id=<id>&limit=50&offset=0`

### 8.2 Rent — Generate Charges
**Purpose**
- Create monthly rent charges for leases (idempotent behavior expected by backend).

**UI**
- Select scope:
  - “All active leases” (default)
  - or “Specific lease”
- Select start month + number of months (default 1)

**API**
- `POST /api/v1/pm/rent/charges/generate`
- Body: `{ "lease_id": null, "start_month": "2025-01-01", "months": 1 }`

### 8.3 Rent — Record Payment
**Purpose**
- Log a payment against a charge (cash/bank/manual).

**UI**
- Inputs: amount, paid_at (default now), method, reference, notes
- Optional: upload receipt → sets `receipt_document_id`

**APIs**
- Upload receipt (optional): `POST /api/v1/pm/documents/upload`
- Create payment: `POST /api/v1/pm/rent/payments`
  - Body: `{ "charge_id": 123, "amount_paid": 25000, "payment_method": "bank_transfer", "reference": "UTR123", "receipt_document_id": 999 }`

### 8.4 Expenses — List + Add
**Purpose**
- Track property expenses; attach receipts.

**List API**
- `GET /api/v1/pm/expenses?property_id=<id>&category=<cat>&start_date=2025-01-01&end_date=2025-01-31`

**Create**
- `POST /api/v1/pm/expenses`
- Body: `ExpenseCreate` (supports `receipt_document_id`)

**Edit**
- `PATCH /api/v1/pm/expenses/{expense_id}`

---

## 9) More Tab (Operations)

### 9.1 Maintenance — Queue
**Purpose**
- Owner’s operational queue of maintenance requests + work orders.

**UI**
- Filters: property, request status, work order status, urgency
- Sorting: urgency desc, then updated_at desc

**API**
- `GET /api/v1/pm/maintenance/requests?property_id=<id>&request_status=<status>&work_order_status=<status>`

### 9.2 Maintenance — Create Request (Owner-created)
**Purpose**
- Log an issue even if tenant app is not shipped yet.

**API**
- `POST /api/v1/pm/maintenance/requests`
- Body: `{ "property_id": 10, "category": "plumbing", "urgency": "high", "title": "Kitchen sink leak", "description": "...", "preferred_contact_method": "call" }`

### 9.3 Maintenance — Request Detail / Work Order Update
**Purpose**
- Track request lifecycle; record costs; mark completion.

**API**
- `PATCH /api/v1/pm/maintenance/requests/{request_id}`
- Use fields such as: `request_status`, `work_order_status`, `scheduled_for`, `estimated_cost`, `actual_cost`, `completion_notes`, `completed_at`, `closed_at`.

### 9.4 Applications — Forms
**Purpose**
- Create and manage shareable rental application forms.

**List**
- `GET /api/v1/pm/applications/forms?property_id=<id>&q=<text>`

**Create**
- `POST /api/v1/pm/applications/forms`
- Body: `RentalApplicationFormCreate` (supports JSON `questions`, `required_document_types`, `config`)

**Share link behavior**
- App shows: `https://<env-domain>/api/v1/pm/public/applications/{slug}` (API) and also a public web/mobile deep link for applicants (Phase 2).

### 9.5 Applications — Inbox + Decision
**List**
- `GET /api/v1/pm/applications?property_id=<id>&status=pending`

**Detail**
- `GET /api/v1/pm/applications/{application_id}`

**Approve/Reject**
- `POST /api/v1/pm/applications/{application_id}/decision`
- Body: `{ "decision": "approved" }` or `{ "decision": "rejected" }`

**Post-approval CTA**
- “Create Lease from application” → prefill tenant name/phone/email into Lease Create.

### 9.6 Leases — List / Create / Detail
**List**
- `GET /api/v1/pm/leases?property_id=<id>&status=active`

**Create**
- `POST /api/v1/pm/leases`
- Body: `LeaseCreate`
  - If tenant is a platform user: set `tenant_user_id`
  - Otherwise: set `tenant_name`, `tenant_phone`, `tenant_email`

**Detail**
- `GET /api/v1/pm/leases/{lease_id}`

**Upload signed lease (MVP manual)**
- Upload the PDF to documents: `POST /api/v1/pm/documents/upload` → `document_id`
- Attach to lease: `POST /api/v1/pm/leases/{lease_id}/upload-signed`
  - Body: `{ "lease_document_id": 999, "signed_by_owner": true, "signed_by_tenant": true }`

**Renew / Terminate**
- `POST /api/v1/pm/leases/{lease_id}/renew`
- `POST /api/v1/pm/leases/{lease_id}/terminate`

### 9.7 Documents — Vault
**List**
- `GET /api/v1/pm/documents?property_id=<id>&lease_id=<id>&document_type=<type>`

**Update sharing**
- `PATCH /api/v1/pm/documents/{document_id}`
- Body: `{ "shared_with_tenant": true, "shared_with_agent": false }`

### 9.8 Inspections — Checklists + Signatures
**List**
- `GET /api/v1/pm/inspections?property_id=<id>`

**Create**
- `POST /api/v1/pm/inspections`
- Body: `{ "lease_id": 123, "inspection_type": "move_in", "rooms_data": { ... }, "overall_notes": "..." }`

**Sign (owner signature document id)**
- Upload signature image: `POST /api/v1/pm/documents/upload`
- `POST /api/v1/pm/inspections/{inspection_id}/sign`
- Body: `{ "owner_signature_document_id": 999 }`

### 9.9 Reports — Hub
**Cards**
- Rent roll: `GET /api/v1/pm/reports/rent-roll`
- Income: `GET /api/v1/pm/reports/income?start=<iso>&end=<iso>`
- Expenses: `GET /api/v1/pm/reports/expenses?start=<date>&end=<date>`
- P&L: `GET /api/v1/pm/reports/pnl?start=<date>&end=<date>`
- Occupancy: `GET /api/v1/pm/reports/occupancy`
- Maintenance: `GET /api/v1/pm/reports/maintenance`

**Export**
- MVP export is client-generated CSV/PDF (backend export endpoints can be added later).

### 9.10 Relationship Manager (Optional)
**Purpose**
- Show current RM assignment and allow unassign/change if the owner knows `agent_id`.

**APIs**
- `GET /api/v1/pm/assignments` (owner gets only their assignment)
- Assign/change: `POST /api/v1/pm/assignments` with `{ "agent_id": <id> }`
- Unassign: `POST /api/v1/pm/assignments` with `{ "agent_id": null }`

**Important limitation**
- There is no Owner-scoped “browse/search agents” endpoint in the current backend; if needed, add in Phase 2 or rely on admin/support.

---

## 10) Key Owner Journeys (End-to-End)

### 10.1 Owner adds a new property
Home → FAB “Add Property” → wizard → create → Property Detail
- API: `POST /api/v1/pm/properties`

### 10.2 Owner collects rent each month (manual-first)
Finance → “Generate Charges” → Charges list → Charge → “Record Payment”
- APIs: `POST /api/v1/pm/rent/charges/generate`, `POST /api/v1/pm/rent/payments`

### 10.3 Owner onboards a tenant via application link
More → Applications → Create form → share slug → review submissions → approve → create lease → upload signed PDF
- APIs: `/pm/applications/forms`, `/pm/applications`, `/pm/leases`, `/pm/documents/upload`

### 10.4 Owner handles a maintenance request (no vendors)
More → Maintenance → Create request → update statuses → record costs → close
- APIs: `/pm/maintenance/requests` (POST/GET/PATCH)

### 10.5 Owner generates reports for a date range
More → Reports → select report + date range → view → export (client-side)
- APIs: `/pm/reports/*`

---

## 11) Phase 2/3 (Design now, do not build yet)

- Payment gateways (UPI/card), autopay, payouts, bank sync
- E-signature for lease/inspections, signature tracking with reminders
- Background checks & scoring integrations
- Tenant app + tenant maintenance submission + tenant document views
- Agent app (RM mode) + owner switching
- In-app notifications feed for the current user (backend currently has admin-only listing)
- Messaging hub (owner ↔ tenant ↔ agent) with attachments
