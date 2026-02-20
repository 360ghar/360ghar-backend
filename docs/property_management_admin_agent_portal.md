# Property Management — Admin & Agent Portal UI/UX Specification

This document is part of the **Property Management** module of 360 Ghar. It defines the **web portal UI/UX** needed to fully operate the Property Management system (Owners + Relationship Managers + Tenants) on top of the existing 360 Ghar backend and the new PM API surface:
- PM APIs: `/api/v1/pm/*`
- Public applications: `/api/v1/pm/public/*`
- Auth: direct Supabase client SDK login/session management; backend accepts bearer access tokens

It is aligned to the current backend direction:
- **Manual-first workflows** (rent ledger + receipt uploads, no payment gateway yet)
- **No vendor module** (work orders handled by Owner/RM)
- **No third‑party integrations** until later phase (payments, KYC verification, background checks, e-sign)
- RM assignment reuses existing **`users.agent_id`** (one RM per owner for MVP)
- KYC documents are stored as **documents linked via `documents.user_id`** (admin-driven)

---

## 1) Purpose and Audience

### 1.1 Portals covered
1) **Admin Portal (Back-office)**
- Used by operations/admin teams to manage users, agents, assignments, KYC docs, and supervise the full PM dataset.

2) **Agent Portal (Relationship Manager / RM)**
- Used by agents to manage properties, leases, rent, maintenance, documents, inspections, and reports **for assigned owners only**.

### 1.2 Primary UX goals
- **Fast operations**: data-dense tables, powerful filtering, bulk actions.
- **Low error rate**: guardrails, validation, and “undo where possible”.
- **Auditability**: clear “who did what” in activity + audit trails.
- **Owner-scoped work**: agents always work within an owner/portfolio context.

---

## 2) Roles, Permissions, and Access Model

### 2.1 Roles
**Admin**
- Full access to all portfolios and all PM entities.
- Can manage agent accounts and assign agents to owners.
- Can upload KYC documents and update KYC status (manual).
- Can run exports, generate reports, and perform operational overrides.

**Agent (Relationship Manager)**
- Access only to owners where `owner.user.agent_id == agent.agent_id`.
- Full operational authority within that owner scope for:
  - Applications, leases, rent charges/payments, expenses
  - Maintenance requests/work orders (no vendors)
  - Documents and inspections
  - Reports

**Support / Read-only (optional)**
- Read-only views of data, no financial or assignment operations.

### 2.2 Owner selection behavior (Agent portal)
The Agent portal must provide an **Owner Selector** in the top bar:
- Search owners by name/phone.
- Switching owners changes scope for all modules (portfolio, leases, rent, maintenance, documents, reports).
- Store last selected owner in local storage.

### 2.3 Tenant data access (privacy)
Even for admin/agent:
- Tenant documents should only be visible if linked to the owner’s portfolio and permitted by document sharing rules.
- Mask sensitive fields by default (ID numbers) where applicable; reveal only on explicit action (admin only).

---

## 3) Information Architecture (Navigation)

### 3.1 Layout and navigation style
Desktop-first web app with:
- **Left sidebar navigation**
- **Top bar**: owner selector (agent), global search, notifications, user menu
- **Main content**: list → detail patterns with drawers/modals

### 3.2 Admin portal sidebar (recommended)
1) **Dashboard**
2) **Owners**
3) **Agents**
4) **Managed Properties**
5) **Applications**
6) **Leases**
7) **Rent Ledger**
8) **Expenses**
9) **Maintenance**
10) **Documents**
11) **Inspections**
12) **Reports**
13) **Notifications & Scheduler** (phase 2)
14) **Audit Log**
15) **Settings**

### 3.3 Agent portal sidebar (recommended)
1) **Dashboard**
2) **Owners** (assigned list + switch owner)
3) **Managed Properties**
4) **Applications**
5) **Leases**
6) **Rent Ledger**
7) **Expenses**
8) **Maintenance**
9) **Documents**
10) **Inspections**
11) **Reports**
12) **Profile / Settings**

---

## 4) Global UX Patterns (Consistency Rules)

### 4.1 List pages (tables)
All list pages should share:
- Search input (debounced)
- Filter bar + “More filters” drawer
- Sort menu
- Pagination (server-driven) + page-size selector
- Sticky bulk-action bar when rows selected

### 4.2 Entity detail pages
Use a consistent structure:
- Header: entity title + status chip + key metadata + primary actions
- Tabs or sections:
  - Overview
  - Related items
  - Activity / audit trail
- Right-side action panel (optional) for quick edits

### 4.3 Status chips + timelines
Always display status in lists and details:
- Lease status, rent charge status, maintenance/work order status, application status, property management status.
Provide a compact timeline component for:
- Lease lifecycle
- Maintenance/work order updates
- Document versioning (phase 2)

### 4.4 File upload UX (documents, receipts, inspections)
Standard upload component:
- Drag & drop + browse
- File type validation (PDF/images/doc)
- Progress + retry
- Metadata capture (type, title, linked entity IDs)
- Preview + delete before submit

---

## 5) Admin Portal — Modules & Screens

### 5.1 Dashboard (Admin)
**Purpose:** global oversight.

Widgets:
- Total managed properties + occupancy
- Outstanding rent (global) + overdue count
- Maintenance open by urgency
- Lease expiries (90/60/30 windows)
- Recent activity feed (payments recorded, work orders updated, documents uploaded)

Drill-down:
- Clicking any KPI routes to the filtered module view.

API mapping:
- `GET /api/v1/pm/dashboard/overview`
- `GET /api/v1/pm/dashboard/activity`

### 5.2 Owners (Admin)
**Screen: Owners List**
Columns:
- Owner name, phone/email
- Assigned RM (agent)
- Managed properties count
- Outstanding rent
- KYC status (manual)
- Last activity

Actions:
- View owner portfolio
- Assign/change RM (updates `users.agent_id`)
- Add KYC documents (upload to documents with `user_id` = owner)
- Export owner portfolio (CSV)

**Screen: Owner Detail**
Tabs:
1) Overview (contact, assignment, portfolio summary)
2) Properties (managed only)
3) Tenants (derived from active leases)
4) Leases
5) Rent ledger
6) Maintenance
7) Documents (owner-scoped)
8) Reports
9) Activity/audit

API mapping:
- Assignment: `POST/PATCH /api/v1/pm/assignments`
- Portfolio views: use `owner_id` filters across `/pm/*` list endpoints

### 5.3 Agents (Admin)
**Screen: Agents List**
Columns:
- Agent name, phone
- Active flag
- Assigned owners count
- Open maintenance count (aggregate)

Actions:
- Create/edit agent profile (if supported in existing backend)
- Activate/deactivate agent
- View assigned owners

**Screen: Agent Detail**
Tabs:
- Overview (profile)
- Assigned owners
- Performance (phase 2: KPIs)
- Activity/audit

### 5.4 Managed Properties (Admin)
**Screen: Properties List**
Default filter: `is_managed=true`

Filters:
- Owner
- Occupancy (active lease exists)
- City / locality
- Management status (draft/active/archived)
- Maintenance (open work orders)

Bulk actions:
- Export CSV
- Set management status
- Reassign RM (via owner assignment)

**Screen: Property Detail**
Tabs:
- Overview (managed defaults: due day, grace, late fee policy)
- Lease & tenant
- Rent
- Maintenance
- Expenses
- Documents
- Inspections
- Activity

API mapping:
- `GET/POST/PATCH /api/v1/pm/properties`
- `GET /api/v1/pm/properties/{property_id}`

### 5.5 Applications (Admin)
**Screen: Application Forms**
- Owner + property + status
- Share link + slug copy
- Submission count

**Screen: Applications Inbox**
Filters:
- Owner / property
- Status (submitted/approved/rejected/request_more_info)
- Submitted date

**Screen: Application Detail**
- Full answers viewer
- Documents viewer
- Decision actions (approve/reject)
- CTA: create lease for approved applicant

API mapping:
- `POST /api/v1/pm/applications/forms`
- `GET /api/v1/pm/applications/forms/{id}`
- `GET /api/v1/pm/public/applications/{slug}`
- `POST /api/v1/pm/public/applications/{slug}/submit`
- `POST /api/v1/pm/applications/{application_id}/decision`

### 5.6 Leases (Admin)
**Screen: Leases List**
Filters:
- Owner, property, tenant
- Status (active/expiring/expired/terminated)
- End date range (expiring soon)

Actions:
- Create lease (admin override)
- Upload signed lease doc (manual)
- Renew/terminate

API mapping:
- `POST /api/v1/pm/leases`
- `GET /api/v1/pm/leases`
- `GET /api/v1/pm/leases/{lease_id}`
- `POST /api/v1/pm/leases/{lease_id}/upload-signed`
- `POST /api/v1/pm/leases/{lease_id}/renew`
- `POST /api/v1/pm/leases/{lease_id}/terminate`

### 5.7 Rent Ledger (Admin)
**Screen: Charges**
Filters:
- Owner, property, lease, tenant
- Status: pending/partial/paid/overdue/waived
- Billing month range

Bulk actions:
- Generate charges for owner or lease (idempotent)
- Export CSV

**Screen: Payments**
- Filter by owner/property/lease/tenant/date
- Show: paid_at, method, reference, amount, linked charge, receipt doc

**Modal: Record Payment**
- Amount + paid_at + method + reference + notes + optional receipt upload
- Result shows updated charge status and outstanding.

API mapping:
- `POST /api/v1/pm/rent/charges/generate`
- `GET /api/v1/pm/rent/charges`
- `POST /api/v1/pm/rent/payments`
- `GET /api/v1/pm/rent/payments`

### 5.8 Expenses (Admin)
**Screen: Expenses List**
Filters:
- Owner, property, category, date range
Actions:
- Add/edit expense
- Upload receipt
- Export CSV

API mapping:
- `POST /api/v1/pm/expenses`
- `GET /api/v1/pm/expenses`

### 5.9 Maintenance (Admin)
**Screen: Maintenance Queue**
Filters:
- Owner, property, lease
- Request status + work order status
- Urgency and category

Detail actions:
- Assign to RM/self
- Update work order status
- Schedule date/time
- Update estimated/actual cost
- Upload completion invoice/photos
- Close

API mapping:
- `GET /api/v1/pm/maintenance/requests`
- `PATCH /api/v1/pm/maintenance/requests/{id}`

### 5.10 Documents (Admin)
**Screen: Document Vault**
Filters:
- Owner, property, lease, user, document type
- Shared with tenant / shared with agent

Actions:
- Upload document (link to any entity)
- Edit metadata (title, sharing toggles)
- Download/view

Special admin use-cases:
- Upload owner KYC documents (link via `user_id`)
- Upload signed lease documents
- Upload maintenance invoices

API mapping:
- `POST /api/v1/pm/documents/upload`
- `GET /api/v1/pm/documents`
- `PATCH /api/v1/pm/documents/{id}`
- `GET /api/v1/pm/documents/{id}/download`

### 5.11 Inspections (Admin)
**Screen: Inspection Checklists**
Filters:
- Owner, lease, property
- Inspection type (move-in/move-out/routine)

Detail:
- Room-by-room JSON viewer
- Photo/document attachments (via documents)
- Sign-off docs (phase 2: signatures)

API mapping:
- `POST /api/v1/pm/inspections`
- `GET /api/v1/pm/inspections`
- `GET /api/v1/pm/inspections/{id}`
- `POST /api/v1/pm/inspections/{id}/sign`

### 5.12 Reports (Admin)
**Screen: Reports Hub**
Reports:
- Rent roll
- Income
- Expenses
- P&L
- Occupancy
- Maintenance

Controls:
- Date range
- Owner/property filters
- Export CSV (MVP), PDF/Excel (phase 3)

API mapping:
- `GET /api/v1/pm/reports/rent-roll`
- `GET /api/v1/pm/reports/income`
- `GET /api/v1/pm/reports/expenses`
- `GET /api/v1/pm/reports/pnl`
- `GET /api/v1/pm/reports/occupancy`
- `GET /api/v1/pm/reports/maintenance`

### 5.13 Audit Log (Admin)
**Purpose:** traceability for operational risk.

Views:
- Filter by entity type (lease/payment/maintenance/document), actor, date range
- Show “before/after” diffs for key financial fields (phase 2)

MVP approach:
- Use activity computed from existing tables (created_at/updated_at) plus application logs where available.
- Add a proper audit table in later phase if needed.

### 5.14 Settings (Admin)
Configuration pages (MVP-lite):
- Document types and categories (display labels; backend enums are fixed)
- Late fee policy presets (fixed / percentage presets stored in frontend config or backend JSON store in phase 2)
- Application form templates (frontend templates; backend stores answers JSON)
- Notification preferences (phase 2)

---

## 6) Agent Portal (RM) — Modules & Screens

### 6.1 Dashboard (Agent)
**Purpose:** daily operational cockpit.

Widgets (scoped to assigned owners or selected owner):
- Tasks due today: overdue rent, upcoming rent, expiring leases, pending applications
- Maintenance queue by urgency
- Recent activity for selected owner

Top bar:
- Owner selector (required)
- Quick “Create” dropdown (lease, expense, application form, inspection)

API mapping:
- `GET /api/v1/pm/dashboard/*` with owner scope selection

### 6.2 Owners (Agent)
**Screen: Assigned Owners**
- List owners assigned to this agent (derived from `users.agent_id`)
- Show: properties count, outstanding, maintenance open count
- Click opens the owner context and routes to Portfolio.

### 6.3 Managed Properties (Agent)
Same UX as Admin but scoped:
- List/search/filter
- Property detail tabs for rent/maintenance/docs/inspections
- Ability to create/update managed properties for assigned owners (if business allows)

### 6.4 Applications (Agent)
Agent operates the full applications funnel for assigned owners:
- Create form, share link, monitor submissions
- Review, approve/reject, create lease

### 6.5 Leases (Agent)
Agent can:
- Create lease for a property
- Upload signed lease doc
- Renew/terminate

### 6.6 Rent Ledger (Agent)
Agent can:
- Generate charges for an owner/lease (idempotent)
- Record payments (cash/bank transfer/check/manual)
- Track outstanding and overdue

### 6.7 Expenses (Agent)
Agent can:
- Add expenses per property
- Attach receipts
- Filter and export for owners

### 6.8 Maintenance (Agent)
Agent is the executor (no vendors):
- Triage new requests
- Convert/update work order fields
- Assign to self / set schedule / manage costs
- Close with completion notes and invoice uploads

### 6.9 Documents & Inspections (Agent)
Agent can:
- Upload and link documents (lease, invoices, inspection photos, receipts)
- Share/unshare docs with tenant/agent based on owner policy
- Create and manage inspection checklists

### 6.10 Reports (Agent)
Agent generates reports for owners:
- Rent roll, income, expenses, P&L, occupancy, maintenance
- Export/share (CSV)

---

## 7) Key Operational Flows (Step-by-Step UX)

### 7.1 Admin: Onboard a new Owner into PM
1) Create/verify owner user (existing user module).
2) Assign RM (set `users.agent_id`).
3) Add managed properties (or mark existing properties as managed).
4) Upload KYC docs (documents with `user_id = owner.id`).
5) Set KYC status (MVP suggestion: store in user preferences JSON; display in UI).
6) Optional: create application form to start tenant onboarding.

### 7.2 Agent: Convert applicant → tenant lease
1) Receive submission in Applications Inbox.
2) Review answers + documents.
3) Approve and create lease (pre-fill tenant info).
4) Upload signed lease PDF (manual).
5) Generate rent charges for next N months.

### 7.3 Agent: Monthly rent operations
1) Open Rent Ledger → filter “Overdue / Due this week”.
2) Call tenant (outside system) and record payment when received.
3) Upload payment receipt/proof.
4) Ensure charge status updates to partial/paid.
5) Export monthly receipts for owner (CSV + doc links).

### 7.4 Agent: Maintenance lifecycle without vendors
1) Review incoming maintenance request.
2) Assign to self, set priority and schedule, estimate cost.
3) Update progress status (in progress → completed).
4) Upload invoice/completion photos.
5) Close request with final notes and actual cost.

---

## 8) Data & Form Design (Guardrails)

### 8.1 Late fee policy (JSON-backed)
Portal should provide a simple builder:
- Type: Fixed amount OR Percentage
- Amount/percent
- Grace period days
Preview: “If rent ₹25,000 is late by X days → late fee ₹Y”

### 8.2 Rent charge generation UX
Generate charges modal:
- Scope: owner (all active leases) OR specific lease
- Start month (default current)
- Months count (1–24)
Show result:
- Created count, skipped count (idempotency)

### 8.3 Tenant identity for lease creation (MVP)
Lease tenant options:
- Existing user (search by phone)
- New tenant without account (store name/phone/email in lease record)
Portal should show a warning when tenant has no account: “Tenant portal access will be unavailable until invited/created.”

---

## 9) Non‑Goals (Do not design as MVP dependencies)
- Payment gateway collection (UPI/card), autopay, retries
- Background check integration and scoring
- E-signature workflow provider integration
- Vendor onboarding, assignment, payouts
- Bank account sync and accounting integrations

These can be included as **Phase 3** “coming later” placeholders in UI, but must not block MVP.

---

## 10) Phase Roadmap (Portal Enhancements)

### Phase 2
- Notification scheduler UI: rent reminders, lease expiry reminders (with logs)
- Communication hub (owner/tenant/RM messaging) if backend adds messaging
- Recurring expenses management and materialization UI
- Strong audit log with diffs for finance/lease changes

### Phase 3 (Integrations)
- Payment gateway receipts + reconciliation UI
- KYC verification and background checks dashboards
- E-sign tracking pages and signature status timelines
- Accounting exports/integrations (QuickBooks/Xero)
