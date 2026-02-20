# Property Management Owner Mobile App — Backend Integration Specification

This document is part of the **Property Management** module of 360 Ghar. It provides the complete backend integration specification for building a **Property Management Mobile App for Owners**. It defines all screens, user flows, APIs, and implementation details required for the mobile team.

---

## Table of Contents
1. [Executive Overview](#1-executive-overview)
2. [API Base Configuration](#2-api-base-configuration)
3. [Authentication & Onboarding](#3-authentication--onboarding)
4. [Navigation Structure](#4-navigation-structure)
5. [Screen Specifications](#5-screen-specifications)
6. [API Endpoints Reference](#6-api-endpoints-reference)
7. [Data Models & Schemas](#7-data-models--schemas)
8. [User Flows](#8-user-flows)
9. [Error Handling](#9-error-handling)
10. [Phase Roadmap](#10-phase-roadmap)

---

## 1. Executive Overview

### 1.1 Purpose
A standalone mobile app for Property Owners to manage their complete rental portfolio from a single interface. Owners can:

- Manage multiple properties, tenants, leases
- Collect rent and track finances (manual-first)
- Handle maintenance requests (no vendors - handled by RM/owner)
- Access documents and generate reports
- Work with Relationship Managers (Agents)

### 1.2 App Scope (MVP)
**In Scope:**
- Owner Dashboard with portfolio metrics
- Property Management (CRUD, photos, occupancy tracking)
- Tenant Management (directory, profiles, lease history)
- Rent Collection (charges, payments, manual recording)
- Expenses Tracking (categories, receipts, reports)
- Maintenance Management (requests, work orders)
- Document Vault (upload, share, download)
- Inspections (move-in/out checklists with signatures)
- Rental Applications (forms, public links, approvals)
- Reports & Analytics (rent roll, income, P&L, occupancy)
- Relationship Manager assignment

**Out of Scope (Phase 2/3):**
- Dedicated Tenant App experience
- Dedicated Agent App experience
- Payment gateway integration (Razorpay/Stripe)
- E-signature integration
- Background check/KYC provider integrations
- Real-time messaging hub
- Accounting software sync (QuickBooks/Xero)

### 1.3 Technical Stack
- **Backend API:** FastAPI (Python)
- **API Base Path:** `/api/v1/pm/*`
- **Auth:** Bearer token (JWT from Supabase)
- **Database:** PostgreSQL (Supabase)
- **Storage:** Supabase Storage (signed URLs)
- **Docs:** Swagger/OpenAPI available at `/api/v1/docs`

---

## 2. API Base Configuration

### 2.1 Base URL
```
https://api.360ghar.com
```

### 2.2 Authentication Headers
All authenticated requests must include:
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

### 2.3 Common Query Parameters
Most list endpoints support:
- `limit` (default 50, max 200)
- `offset` (for pagination)
- `q` (search text where applicable)

### 2.4 Pagination Pattern
```json
{
  "results": [...],
  "has_more": true,
  "total_count": 150
}
```
Use `limit` + `offset` with infinite scroll or "Load More" button.

---

## 3. Authentication & Onboarding

### 3.2 Profile Setup

#### Screen: Complete Profile
**Purpose:** Collect owner's basic information

**Inputs:**
- `full_name` (required)
- `email` (optional)
- `profile_photo` (optional, upload to `/pm/documents/upload`)
- Address details (optional)

**APIs:**
```
GET /api/v1/users/profile/
Response: { "id": 123, "full_name": "...", "phone": "...", "email": "..." }

PUT /api/v1/users/profile/
Body: { "full_name": "John Doe", "email": "john@example.com" }
```

### 3.3 Login Flow

#### Screen: Login
**Purpose:** Existing user login

**Auth Options (Client-side Supabase SDK):**
1. **Password Login:** `supabase.auth.signInWithPassword({ phone, password })`
2. **Phone OTP Login:** `supabase.auth.signInWithOtp()` + `supabase.auth.verifyOtp()`

### 3.4 Token Management
- Store `access_token` securely (Keychain/Keystore)
- Token expiration handling:
  - On 401 response, clear token and route to login
  - Optionally use `refresh_token` if available

---

## 4. Navigation Structure

### 4.1 Bottom Navigation (5 Tabs)
```
┌─────────────────────────────────────┐
│  HOME   │  PROPERTIES  │  TENANTS  │
├─────────────────────────────────────┤
│  FINANCE    │    MORE               │
└─────────────────────────────────────┘
```

### 4.2 Tab Breakdown

| Tab | Purpose | Key Features |
|-----|---------|--------------|
| **Home** | Dashboard & Tasks | Portfolio metrics, quick actions, activity feed |
| **Properties** | Property Management | Property list, add/edit, property details |
| **Tenants** | Tenant Directory | Tenant list, profiles, lease history |
| **Finance** | Rent & Expenses | Rent charges/payments, expense tracking, reports |
| **More** | Operations Center | Maintenance, applications, leases, documents, inspections, reports, settings |

### 4.3 Floating Action Button (FAB)
Global quick actions available from all tabs:
- Add Property
- Create Lease
- Create Application Form
- Generate Rent Charges
- Record Rent Payment
- Add Expense
- Create Maintenance Request
- Upload Document

---

## 5. Screen Specifications

### 5.1 Splash Screen
**Purpose:** Session restoration

**Behavior:**
- Check for stored `access_token`
- If exists → call `GET /api/v1/pm/dashboard/overview`
- If 401 → clear token → show Login
- Else → show Dashboard

---

### 5.2 HOME TAB

#### 5.2.1 Dashboard Screen

**Purpose:** Owner's portfolio snapshot

**UI Components:**
1. **Header**
   - Greeting with owner name
   - Profile photo (tap → Profile)
   - Notification bell (tap → Notifications - Phase 2)

2. **KPI Cards** (tappable for drill-down)
   - Total Properties: `X` (occupied: Y, vacant: Z)
   - Occupied: `Y` properties
   - Vacant: `Z` properties
   - Under Maintenance: `W` properties
   - This Month Revenue: `₹1,25,000` (vs previous: `₹1,10,000`)
   - Outstanding Rent: `₹45,000` (tap → overdue charges)
   - Upcoming Expenses: `₹12,500` (tap → expenses)

3. **Quick Actions Grid** (2x3)
   - Add Property
   - Create Lease
   - Generate Rent Charges
   - Record Payment
   - Add Expense
   - Maintenance Requests

4. **Recent Activity Timeline**
   - "Rent received: ₹25,000 for Apartment A - 2 hours ago"
   - "Maintenance request submitted: Plumbing - Yesterday"
   - "New application: Rahul Sharma - 2 days ago"

**APIs:**
```
GET /api/v1/pm/dashboard/overview
Response: {
  "total_properties": 5,
  "occupied_properties": 3,
  "vacant_properties": 2,
  "under_maintenance_properties": 0,
  "monthly_revenue_current": 125000.00,
  "monthly_revenue_previous": 110000.00,
  "outstanding_rent_total": 45000.00,
  "upcoming_expenses_total": 12500.00
}

GET /api/v1/pm/dashboard/activity?limit=20
Response: [
  {
    "type": "payment_received",
    "at": "2025-12-28T10:30:00Z",
    "id": 123,
    "property_id": 5,
    "lease_id": 10,
    "amount": 25000.00,
    "status": "paid"
  },
  ...
]
```

**Empty State:**
- No properties: Show "Add your first property" CTA button

#### 5.2.2 Tasks Screen (Computed Feed)

**Purpose:** Prioritized action items

**UI Structure:**
```
┌─────────────────────────────────────┐
│ OVERDUE RENT                      │
│ • Property A: ₹15,000 (7 days)    │
│ • Property B: ₹8,000 (3 days)     │
├─────────────────────────────────────┤
│ PENDING RENT                      │
│ • Property C: ₹25,000 (due Jan 5) │
├─────────────────────────────────────┤
│ OPEN MAINTENANCE                  │
│ • Plumbing: Property D (High)      │
│ • HVAC: Property A (Medium)       │
├─────────────────────────────────────┤
│ EXPIRING LEASES                  │
│ • Property E: Expires Jan 31       │
├─────────────────────────────────────┤
│ PENDING APPLICATIONS              │
│ • Rahul Sharma: Apartment F        │
└─────────────────────────────────────┘
```

**APIs (Fan-out for real-time):**
```
# Overdue rent
GET /api/v1/pm/rent/charges?status=overdue&limit=10

# Pending rent (current month)
GET /api/v1/pm/rent/charges?status=pending&limit=10

# Open maintenance requests
GET /api/v1/pm/maintenance/requests?request_status=open&limit=10

# Expiring leases (client-side filter)
GET /api/v1/pm/leases
Filter: end_date <= today + 30 days

# Pending applications
GET /api/v1/pm/applications?status=applicant&limit=10
```

---

### 5.3 PROPERTIES TAB

#### 5.3.1 Properties List Screen

**Purpose:** Browse and search all managed properties

**UI Components:**
1. **Search Bar**
   - Search by property title, address, tenant name

2. **Filter Sheet**
   - Occupancy: `Occupied | Vacant | Under Maintenance`
   - Property Type: `Apartment | House | Commercial | Land`
   - Location: City filter

3. **Property Card**
```
┌─────────────────────────────────────┐
│ [Property Image]                  │
│ Green Valley Apt - 2BHK           │
│ 📍 Sector 62, Gurgaon            │
│ Occupied • ₹25,000/month         │
│ 2 Open Maintenance               │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/properties?occupancy=occupied&q=search&limit=50&offset=0
Response: [
  {
    "id": 1,
    "title": "Green Valley Apt",
    "property_type": "apartment",
    "address": { "locality": "Sector 62", "city": "Gurgaon", ... },
    "base_price": 25000.00,
    "management_status": "active",
    "images": ["url1.jpg", "url2.jpg"],
    ...
  },
  ...
]
```

**Empty State:**
- "No properties found. Add your first property."

#### 5.3.2 Add Property Wizard (Multi-step)

**Step 1: Basic Details**
**Inputs:**
- Property Nickname/Title
- Property Type (dropdown)
- Purpose: rent
- Monthly Rent Amount
- Full Address (with map picker if available)

**Step 2: Property Specifications**
**Inputs:**
- Bedrooms, Bathrooms, Balconies
- Area (sqft)
- Floor number, Total floors
- Age of property
- Parking spaces
- Amenities (checkboxes: AC, Gym, Parking, etc.)
- Property Photos (up to 20, upload via `/pm/documents/upload`)

**Step 3: Management Settings**
**Inputs:**
- Management Status: `Active | Draft`
- Payment Due Day (1-28)
- Grace Period Days (0-365)
- Late Fee Policy (JSON):
  ```json
  {
    "type": "fixed",  // or "percentage"
    "amount": 500,    // or "percentage": 10
    "apply_after": 3   // days after due date
  }
  ```

**API:**
```
POST /api/v1/pm/properties?management_status=active&payment_due_day=1&grace_period_days=5
Body: {
  "title": "Green Valley Apt",
  "property_type": "apartment",
  "purpose": "rent",
  "base_price": 25000.00,
  "address": { "city": "Gurgaon", ... },
  "bedrooms": 2,
  "bathrooms": 2,
  "area_sqft": 1200,
  ...
}
```

#### 5.3.3 Property Detail Screen

**Purpose:** Single source of truth for a property

**UI Structure:**
```
┌─────────────────────────────────────┐
│ Green Valley Apt - 2BHK          │
│ Active • Occupied                │
│ [Call Tenant] [Share] [Edit]     │
├─────────────────────────────────────┤
│ Tabs: Overview | Lease | Rent |   │
│       Expenses | Maintenance |     │
│       Documents | Inspections     │
└─────────────────────────────────────┘
```

**Tab 1: Overview**
- Property specifications (beds, baths, area, amenities)
- Address with map
- Photos carousel
- Management settings (due day, grace period, late fee policy)
- Current Tenant summary (if occupied)

**API:**
```
GET /api/v1/pm/properties/{property_id}
Response: {
  "property": { ... },
  "active_lease": {
    "id": 10,
    "tenant_name": "Rahul Sharma",
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "monthly_rent": 25000.00,
    ...
  }
}
```

**Tab 2: Lease**
- Active lease summary card
- Lease status: `active | expiring_soon | expired | terminated`
- Quick actions:
  - Create Lease (if no active lease)
  - Upload Signed Lease
  - Renew
  - Terminate

**APIs:**
```
# Create lease
POST /api/v1/pm/leases
Body: {
  "property_id": 1,
  "tenant_name": "Rahul Sharma",
  "tenant_phone": "+919876543210",
  "tenant_email": "rahul@example.com",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "monthly_rent": 25000.00,
  "security_deposit": 50000.00,
  ...
}

# Upload signed lease
POST /api/v1/pm/leases/{lease_id}/upload-signed
Body: {
  "lease_document_id": 999,
  "signed_by_owner": true,
  "signed_by_tenant": true
}

# Renew lease
POST /api/v1/pm/leases/{lease_id}/renew
Body: {
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "monthly_rent": 27000.00,
  "make_active": true
}

# Terminate lease
POST /api/v1/pm/leases/{lease_id}/terminate
```

**Tab 3: Rent**
- Rent Charges list (filtered by this property)
- Payments list (filtered by this property)
- Summary: Total collected, outstanding, overdue

**APIs:**
```
GET /api/v1/pm/rent/charges?property_id=1&status=overdue|pending|paid
Response: [
  {
    "charge": { "id": 101, "billing_month": "2025-01", "due_date": "2025-01-05", ... },
    "amount_paid_total": 0.00,
    "amount_due_total": 25000.00,
    "outstanding": 25000.00
  },
  ...
]

GET /api/v1/pm/rent/payments?property_id=1
```

**Tab 4: Expenses**
- Expense list for this property
- Add Expense CTA

**API:**
```
GET /api/v1/pm/expenses?property_id=1
```

**Tab 5: Maintenance**
- Maintenance requests for this property
- Status, urgency, work order status

**API:**
```
GET /api/v1/pm/maintenance/requests?property_id=1
```

**Tab 6: Documents**
- Document vault for this property
- Upload, view, share documents

**API:**
```
GET /api/v1/pm/documents?property_id=1

# Upload document
POST /api/v1/pm/documents/upload
Form Data:
- file: (binary)
- document_type: "lease_agreement" | "id_proof" | "receipt" | ...
- title: "Lease Agreement Jan 2024"
- property_id: 1
- shared_with_tenant: true
- shared_with_agent: true
```

**Tab 7: Inspections**
- Inspection checklists (move-in, move-out, routine)
- View checklist details, signatures

**API:**
```
GET /api/v1/pm/inspections?property_id=1
```

---

### 5.4 TENANTS TAB

#### 5.4.1 Tenants List Screen

**Purpose:** View all tenants across portfolio

**UI Components:**
1. **Search Bar**
   - Search by tenant name, phone, property address

2. **Tenant Card**
```
┌─────────────────────────────────────┐
│ [Photo] Rahul Sharma              │
│ +91 98765 43210                 │
│ 2 Active Leases • ₹55,000 total   │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/tenants?limit=50&offset=0
Response: [
  {
    "user_id": 45,
    "full_name": "Rahul Sharma",
    "phone": "+919876543210",
    "email": "rahul@example.com",
    "active_leases_count": 2,
    "total_rent": 55000.00
  },
  ...
]
```

**Note:** Only tenants with platform user accounts (`tenant_user_id`) appear here. Tenants from leases without `tenant_user_id` will be visible only in property detail > lease tab.

#### 5.4.2 Tenant Detail Screen

**Purpose:** View tenant profile and history

**UI Components:**
1. **Header**
   - Photo, Name, Phone, Email
   - Actions: Call, WhatsApp, SMS

2. **Leases Section**
   - Active leases list
   - Historical leases list

3. **Quick Links**
   - View Rent Charges for this tenant
   - View Maintenance Requests for this tenant
   - View Documents for this tenant

**API:**
```
GET /api/v1/pm/tenants/{tenant_user_id}
Response: {
  "user_id": 45,
  "full_name": "Rahul Sharma",
  "phone": "+919876543210",
  "email": "rahul@example.com",
  "leases": [
    {
      "id": 10,
      "property_title": "Green Valley Apt",
      "status": "active",
      "start_date": "2024-01-01",
      "end_date": "2024-12-31",
      "monthly_rent": 25000.00
    },
    ...
  ]
}
```

---

### 5.5 FINANCE TAB

#### 5.5.1 Rent Charges Screen

**Purpose:** View all rent charges and track collection

**UI Components:**
1. **Summary Chips**
   - Pending: X charges, ₹Y outstanding
   - Overdue: X charges, ₹Y outstanding
   - Paid: X charges, ₹Y collected

2. **Filter Sheet**
   - Property
   - Status: `pending | partial | paid | overdue | waived`
   - Billing Month (month picker)

3. **Charge Row**
```
┌─────────────────────────────────────┐
│ Jan 2025 • Due: Jan 5            │
│ Green Valley Apt • ₹25,000        │
│ Paid: ₹0 | Outstanding: ₹25,000   │
│ [Record Payment]                  │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/rent/charges?status=overdue&property_id=1&limit=50
Response: [
  {
    "charge": {
      "id": 101,
      "lease_id": 10,
      "property_id": 1,
      "billing_month": "2025-01",
      "due_date": "2025-01-05",
      "amount_due": 25000.00,
      "late_fee_assessed": 0.00,
      "status": "overdue"
    },
    "amount_paid_total": 0.00,
    "amount_due_total": 25000.00,
    "outstanding": 25000.00
  },
  ...
]
```

#### 5.5.2 Generate Rent Charges

**Purpose:** Create monthly rent charges for leases

**UI Components:**
1. **Scope Selection**
   - All Active Leases (default)
   - Specific Lease (dropdown)

2. **Date Selection**
   - Start Month (default: current month)
   - Number of Months (1-24)

3. **Generate Button**

**API:**
```
POST /api/v1/pm/rent/charges/generate
Body: {
  "lease_id": null,  // null = all active leases
  "owner_id": null,  // null = current owner
  "start_month": "2025-01-01",
  "months": 1
}
Response: {
  "created": 3,
  "skipped": 0,
  "charges": [...]
}
```

#### 5.5.3 Record Payment Modal

**Purpose:** Log a rent payment (manual-first)

**UI Components:**
1. **Charge Info Display**
   - Property, Tenant, Billing Month, Amount Due

2. **Payment Details**
   - Amount Paid (default: outstanding)
   - Payment Date (default: now)
   - Payment Method: `bank_transfer | cash | check | card`
   - Reference Number (UTR/Cheque No.)

3. **Receipt Upload**
   - Upload receipt photo/PDF → gets `document_id`

4. **Notes** (optional)

**APIs:**
```
# First upload receipt (optional)
POST /api/v1/pm/documents/upload
Form Data:
- file: receipt.jpg
- document_type: "receipt"
- title: "Rent Receipt Jan 2025"
- lease_id: 10
Response: { "id": 999, "file_url": "...", ... }

# Then record payment
POST /api/v1/pm/rent/payments
Body: {
  "charge_id": 101,
  "amount_paid": 25000.00,
  "paid_at": "2025-01-05T10:30:00Z",
  "payment_method": "bank_transfer",
  "reference": "UTR123456789",
  "receipt_document_id": 999,
  "notes": "Paid via NEFT"
}
Response: {
  "id": 201,
  "charge_id": 101,
  "amount_paid": 25000.00,
  "paid_at": "2025-01-05T10:30:00Z",
  ...
}
```

#### 5.5.4 Expenses Screen

**Purpose:** Track property expenses

**UI Components:**
1. **Filter Sheet**
   - Property
   - Category: `maintenance | repairs | insurance | property_tax | hoa | utilities | marketing | legal | other`
   - Date Range

2. **Expense Row**
```
┌─────────────────────────────────────┐
│ Dec 28, 2024 • Maintenance       │
│ Green Valley Apt • ₹2,500         │
│ Plumber - Sink Repair             │
│ [View Receipt]                   │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/expenses?property_id=1&category=maintenance&start_date=2025-01-01&end_date=2025-01-31
Response: [
  {
    "id": 50,
    "property_id": 1,
    "category": "maintenance",
    "amount": 2500.00,
    "expense_date": "2025-01-15",
    "description": "Plumber - Sink Repair",
    "receipt_document_id": 100
  },
  ...
]
```

#### 5.5.5 Add Expense Modal

**UI Components:**
1. **Property Selection** (dropdown)
2. **Category** (dropdown)
3. **Amount** (numeric input)
4. **Expense Date** (date picker)
5. **Description** (text)
6. **Receipt Upload** (optional)
7. **Notes** (optional)

**API:**
```
POST /api/v1/pm/expenses
Body: {
  "property_id": 1,
  "category": "maintenance",
  "amount": 2500.00,
  "expense_date": "2025-01-15",
  "description": "Plumber - Sink Repair",
  "receipt_document_id": 100,
  "notes": "Emergency repair"
}
```

---

### 5.6 MORE TAB

#### 5.6.1 Maintenance Screen

**Purpose:** View and manage maintenance requests

**UI Components:**
1. **Filter Sheet**
   - Property
   - Request Status: `open | in_review | work_order_created | resolved | closed`
   - Work Order Status: `created | assigned | in_progress | completed | closed`
   - Urgency: `emergency | high | medium | low`

2. **Request Row**
```
┌─────────────────────────────────────┐
│ [Emergency] Plumbing              │
│ Green Valley Apt - Kitchen Sink   │
│ Open • Created 2 hours ago       │
│ [View Details]                   │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/maintenance/requests?request_status=open&urgency=high
Response: [
  {
    "id": 30,
    "property_id": 1,
    "category": "plumbing",
    "urgency": "emergency",
    "title": "Kitchen Sink Leak",
    "description": "Water leaking from pipe",
    "request_status": "open",
    "work_order_status": null,
    "created_at": "2025-12-28T10:00:00Z"
  },
  ...
]
```

#### 5.6.2 Maintenance Request Detail

**Purpose:** Track request lifecycle

**UI Components:**
1. **Header**
   - Title, Property, Category, Urgency chip
   - Status badges: Request Status, Work Order Status

2. **Details**
   - Description
   - Preferred Contact Method
   - Availability Notes
   - Attached Photos/Documents

3. **Work Order Section**
   - Assigned To (owner or RM)
   - Estimated Cost
   - Actual Cost
   - Scheduled Date
   - Work Order Status
   - Completion Notes

4. **Timeline**
   - Request Created
   - Work Order Created
   - In Progress
   - Completed
   - Closed

5. **Actions**
   - Update Status
   - Record Costs
   - Upload Completion Photos
   - Close Request

**API:**
```
PATCH /api/v1/pm/maintenance/requests/{request_id}
Body: {
  "request_status": "in_review",
  "work_order_status": "in_progress",
  "assigned_agent_id": null,  // null = owner handles
  "estimated_cost": 2000.00,
  "actual_cost": 1800.00,
  "scheduled_for": "2025-01-10T10:00:00Z",
  "completed_at": "2025-01-10T15:00:00Z",
  "closed_at": "2025-01-10T16:00:00Z",
  "completion_notes": "Repaired sink pipe successfully"
}
```

#### 5.6.3 Create Maintenance Request

**UI Components:**
1. **Property Selection** (dropdown)
2. **Category** (dropdown): `plumbing | electrical | hvac | appliance | structural | pest_control | cleaning | other`
3. **Urgency** (dropdown): `emergency | high | medium | low`
4. **Title** (text)
5. **Description** (text)
6. **Preferred Contact Method** (dropdown)
7. **Availability Notes** (text)
8. **Photo Upload** (optional)

**API:**
```
POST /api/v1/pm/maintenance/requests
Body: {
  "property_id": 1,
  "category": "plumbing",
  "urgency": "high",
  "title": "Kitchen Sink Leak",
  "description": "Water leaking from pipe under sink",
  "preferred_contact_method": "call",
  "availability_notes": "Available after 6 PM on weekdays"
}
```

#### 5.6.4 Applications Screen

**Purpose:** Manage rental application forms and submissions

**Section 1: Application Forms**
```
┌─────────────────────────────────────┐
│ [+] Create Form                    │
├─────────────────────────────────────┤
│ Apartment A Rental Application      │
│ 5 Submissions • Active            │
│ [Share Link] [View Submissions]    │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/applications/forms?property_id=1
Response: [
  {
    "id": 5,
    "title": "Apartment A Rental Application",
    "description": "Apply for 2BHK in Sector 62",
    "slug": "apt-a-rental-app",
    "is_active": true,
    "application_fee_amount": 500.00,
    "submissions_count": 5
  },
  ...
]
```

**Section 2: Applications Inbox**
- List of applications with status
- Filter by property, status, date

**API:**
```
GET /api/v1/pm/applications?status=applicant&property_id=1
Response: [
  {
    "id": 100,
    "applicant_full_name": "Rahul Sharma",
    "applicant_phone": "+919876543210",
    "applicant_email": "rahul@example.com",
    "property_title": "Green Valley Apt",
    "status": "applicant",
    "submitted_at": "2025-12-28T10:00:00Z"
  },
  ...
]
```

#### 5.6.5 Create Application Form

**UI Components:**
1. **Basic Info**
   - Title
   - Description
   - Select Property (optional)

2. **Application Fee**
   - Amount (optional)
   - Payment Method (Phase 2)

3. **Required Documents**
   - ID Proof (checkbox)
   - Address Proof (checkbox)
   - Income Proof (checkbox)
   - Custom: Add document types

4. **Questions** (JSON)
   - Employment details
   - Previous rental history
   - Pet policy agreement
   - References
   - (Customizable fields)

5. **Config** (JSON)
   - Application deadline
   - Auto-reject criteria (Phase 2)

**API:**
```
POST /api/v1/pm/applications/forms
Body: {
  "title": "Apartment A Rental Application",
  "description": "Apply for 2BHK in Sector 62",
  "property_id": 1,
  "application_fee_amount": 500.00,
  "required_document_types": {
    "id_proof": true,
    "address_proof": true,
    "income_proof": true
  },
  "questions": {
    "employment": {
      "company": "text",
      "monthly_income": "number",
      "work_experience": "number"
    },
    "rental_history": {
      "previous_landlord_name": "text",
      "previous_landlord_contact": "text"
    },
    "references": "array",
    "pets": "boolean"
  },
  "config": {
    "deadline": "2025-02-01",
    "max_applicants": 10
  }
}
Response: {
  "id": 5,
  "slug": "apt-a-rental-app",
  "share_url": "https://app.360ghar.com/apply/apt-a-rental-app"
}
```

#### 5.6.6 Share Application Form

**UI Components:**
1. **Share Link**
   - Display URL: `https://app.360ghar.com/apply/{slug}`
   - Copy button
   - Share via WhatsApp, Email (native share)

2. **QR Code** (optional, Phase 2)

#### 5.6.7 Application Detail

**Purpose:** Review applicant submission

**UI Components:**
1. **Header**
   - Applicant Name, Phone, Email
   - Property, Status
   - Submitted At

2. **Application Answers**
   - Employment details
   - Rental history
   - References
   - Pets, etc.

3. **Documents**
   - ID Proof (view/download)
   - Address Proof (view/download)
   - Income Proof (view/download)
   - Other uploaded docs

4. **Actions**
   - Approve → Create Lease
   - Reject
   - Request More Info (Phase 2)

**APIs:**
```
GET /api/v1/pm/applications/{application_id}
Response: {
  "id": 100,
  "applicant_full_name": "Rahul Sharma",
  "applicant_phone": "+919876543210",
  "applicant_email": "rahul@example.com",
  "status": "applicant",
  "answers": {
    "employment": {
      "company": "ABC Corp",
      "monthly_income": 75000,
      "work_experience": 5
    },
    ...
  },
  "documents": [...],
  "submitted_at": "2025-12-28T10:00:00Z"
}

# Decision
POST /api/v1/pm/applications/{application_id}/decision
Body: {
  "decision": "approved"  // or "rejected"
}
```

#### 5.6.8 Leases Screen (Quick List)

**Purpose:** Quick access to all leases

**UI Components:**
1. **Filter Sheet**
   - Property
   - Status: `draft | pending_signature | active | expiring_soon | expired | terminated | renewed`
   - End Date Range

2. **Lease Row**
```
┌─────────────────────────────────────┐
│ Green Valley Apt - 2BHK           │
│ Rahul Sharma • Active              │
│ ₹25,000/month • Ends Dec 31       │
│ [View Details]                   │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/leases?status=active&property_id=1
Response: [...]
```

#### 5.6.9 Documents Screen

**Purpose:** Central document vault

**UI Components:**
1. **Filter Sheet**
   - Property
   - Document Type: `lease_agreement | id_proof | address_proof | income_proof | inspection_report | receipt | invoice | property_deed | insurance_policy | other`
   - Shared: `Tenant | Agent`

2. **Document Row**
```
┌─────────────────────────────────────┐
│ 📄 Lease Agreement Jan 2024      │
│ Green Valley Apt • PDF            │
│ Shared: Tenant ✓ • Agent ✓       │
│ [View] [Download] [Share]        │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/documents?property_id=1&document_type=lease_agreement
Response: [
  {
    "id": 50,
    "title": "Lease Agreement Jan 2024",
    "document_type": "lease_agreement",
    "file_url": "https://...",
    "mime_type": "application/pdf",
    "shared_with_tenant": true,
    "shared_with_agent": true,
    "created_at": "2024-01-01T10:00:00Z"
  },
  ...
]

GET /api/v1/pm/documents/{document_id}/download
Response: { "url": "https://storage.../signed-url" }
```

#### 5.6.10 Inspections Screen

**Purpose:** View inspection checklists

**UI Components:**
1. **Filter Sheet**
   - Property
   - Type: `move_in | move_out | routine`

2. **Inspection Row**
```
┌─────────────────────────────────────┐
│ Move-In Inspection               │
│ Green Valley Apt • Jan 1, 2024   │
│ Signed: Owner ✓, Tenant ✓       │
│ [View Checklist]                 │
└─────────────────────────────────────┘
```

**API:**
```
GET /api/v1/pm/inspections?property_id=1&inspection_type=move_in
Response: [...]
```

#### 5.6.11 Inspection Detail

**Purpose:** View inspection checklist and signatures

**UI Components:**
1. **Header**
   - Type, Property, Date
   - Signed Status: Owner ✓, Tenant ✓

2. **Checklist Data**
   - Room-by-room JSON viewer:
     ```json
     {
       "living_room": {
         "condition": "good",
         "notes": "Wall paint is good",
         "photos": ["url1.jpg", "url2.jpg"]
       },
       "kitchen": { ... },
       ...
     }
     ```

3. **Signatures**
   - Owner Signature Document (view/download)
   - Tenant Signature Document (view/download)
   - Sign button (if not signed)

**APIs:**
```
GET /api/v1/pm/inspections/{inspection_id}
Response: {
  "id": 20,
  "property_id": 1,
  "lease_id": 10,
  "inspection_type": "move_in",
  "conducted_at": "2024-01-01T10:00:00Z",
  "rooms_data": { ... },
  "overall_notes": "Property in good condition",
  "tenant_signature_document_id": 100,
  "owner_signature_document_id": 101,
  "signed_by_tenant_at": "2024-01-01T11:00:00Z",
  "signed_by_owner_at": "2024-01-01T11:30:00Z"
}

# Sign inspection
POST /api/v1/pm/inspections/{inspection_id}/sign
Body: {
  "tenant_signature_document_id": 100,
  "owner_signature_document_id": 101
}
```

#### 5.6.12 Reports Screen

**Purpose:** View and generate reports

**UI Components:**
1. **Report Cards**
   - Rent Roll
   - Income Report
   - Expenses Report
   - Profit & Loss
   - Occupancy Report
   - Maintenance Report

2. **Report View**
   - Date Range Picker
   - Property Filter
   - Export Options: CSV (MVP), PDF (Phase 2)

**APIs:**
```
# Rent Roll
GET /api/v1/pm/reports/rent-roll
Response: [
  {
    "property_id": 1,
    "property_title": "Green Valley Apt",
    "tenant_name": "Rahul Sharma",
    "monthly_rent": 25000.00,
    "lease_start": "2024-01-01",
    "lease_end": "2024-12-31",
    "occupancy_status": "occupied"
  },
  ...
]

# Income Report
GET /api/v1/pm/reports/income?start=2025-01-01&end=2025-01-31
Response: {
  "total_income": 75000.00,
  "property_breakdown": [
    { "property_id": 1, "amount": 25000.00 },
    { "property_id": 2, "amount": 50000.00 }
  ],
  "month_over_month": { "current": 75000.00, "previous": 70000.00 }
}

# Expenses Report
GET /api/v1/pm/reports/expenses?start=2025-01-01&end=2025-01-31
Response: {
  "total_expenses": 15000.00,
  "category_breakdown": [
    { "category": "maintenance", "amount": 10000.00 },
    { "category": "property_tax", "amount": 5000.00 }
  ],
  "property_breakdown": [...]
}

# Profit & Loss
GET /api/v1/pm/reports/pnl?start=2025-01-01&end=2025-01-31
Response: {
  "revenue": 75000.00,
  "expenses": 15000.00,
  "net_income": 60000.00,
  "roi_percentage": 8.5,
  "property_breakdown": [...]
}

# Occupancy Report
GET /api/v1/pm/reports/occupancy
Response: {
  "total_properties": 5,
  "occupied": 3,
  "vacant": 2,
  "occupancy_rate": 60.0,
  "vacancy_days_average": 15,
  "turnover_rate": 20.0
}

# Maintenance Report
GET /api/v1/pm/reports/maintenance
Response: {
  "total_requests": 25,
  "by_category": [
    { "category": "plumbing", "count": 10 },
    { "category": "electrical", "count": 8 }
  ],
  "by_urgency": [
    { "urgency": "high", "count": 5 },
    { "urgency": "medium", "count": 15 }
  ],
  "average_resolution_hours": 48
}
```

**Export:**
- MVP: Client-side CSV generation from API response
- Phase 2: Backend-provided CSV/PDF download links

#### 5.6.13 Settings Screen

**UI Components:**
1. **Profile Section**
   - Full Name
   - Phone
   - Email
   - Profile Photo
   - Edit Profile

2. **Relationship Manager**
   - Current RM: "Name - Phone"
   - Change RM (if `agent_id` known)

3. **Notifications** (Phase 2)
   - Push Notifications toggle
   - Email Notifications toggle
   - SMS Notifications toggle

4. **App Settings**
   - Theme: Light/Dark
   - Language (Phase 2)
   - Currency: INR (₹) - fixed for India

5. **Support**
   - Contact Support
   - Report Bug
   - Privacy Policy
   - Terms of Service

**APIs:**
```
# Get/Set RM
GET /api/v1/pm/assignments
Response: {
  "owner_user_id": 123,
  "agent_id": 5,
  "agent": {
    "id": 5,
    "name": "Vikram Singh",
    "phone": "+919876543210"
  }
}

POST /api/v1/pm/assignments
Body: {
  "agent_id": 5  // or null to unassign
}

# Profile
GET /api/v1/users/profile/
PUT /api/v1/users/profile/
Body: { "full_name": "...", "email": "..." }
```

---

## 6. API Endpoints Reference

### 6.1 Dashboard
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/pm/dashboard/overview` | Portfolio metrics |
| GET | `/pm/dashboard/activity` | Recent activity |

### 6.2 Properties
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/properties` | Create managed property |
| GET | `/pm/properties` | List properties |
| GET | `/pm/properties/{id}` | Get property detail |
| PATCH | `/pm/properties/{id}` | Update property settings |

### 6.3 Assignments
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/assignments` | Set RM for owner |
| GET | `/pm/assignments` | List assignments |
| PATCH | `/pm/assignments/{owner_id}` | Update RM |

### 6.4 Applications
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/applications/forms` | Create application form |
| GET | `/pm/applications/forms` | List forms |
| GET | `/pm/applications/forms/{id}` | Get form detail |
| GET | `/pm/applications` | List applications (inbox) |
| GET | `/pm/applications/{id}` | Get application detail |
| POST | `/pm/applications/{id}/decision` | Approve/reject application |
| GET | `/pm/public/applications/{slug}` | Public form view |
| POST | `/pm/public/applications/{slug}/submit` | Public form submit |

### 6.5 Tenants
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/pm/tenants` | List tenants |
| GET | `/pm/tenants/{id}` | Get tenant detail |

### 6.6 Leases
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/leases` | Create lease |
| GET | `/pm/leases` | List leases |
| GET | `/pm/leases/{id}` | Get lease detail |
| POST | `/pm/leases/{id}/upload-signed` | Upload signed lease |
| POST | `/pm/leases/{id}/renew` | Renew lease |
| POST | `/pm/leases/{id}/terminate` | Terminate lease |

### 6.7 Rent
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/rent/charges/generate` | Generate monthly charges |
| GET | `/pm/rent/charges` | List charges |
| POST | `/pm/rent/payments` | Record payment |
| POST | `/pm/rent/charges/{id}/tenant-payment-intent` | Tenant marks paid |
| GET | `/pm/rent/payments` | List payments |

### 6.8 Expenses
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/expenses` | Create expense |
| GET | `/pm/expenses` | List expenses |
| PATCH | `/pm/expenses/{id}` | Update expense |

### 6.9 Maintenance
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/maintenance/requests` | Create request |
| GET | `/pm/maintenance/requests` | List requests |
| PATCH | `/pm/maintenance/requests/{id}` | Update request/work order |

### 6.10 Documents
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/documents/upload` | Upload document |
| GET | `/pm/documents` | List documents |
| PATCH | `/pm/documents/{id}` | Update document |
| GET | `/pm/documents/{id}/download` | Get download URL |

### 6.11 Inspections
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pm/inspections` | Create inspection |
| GET | `/pm/inspections` | List inspections |
| GET | `/pm/inspections/{id}` | Get inspection detail |
| POST | `/pm/inspections/{id}/sign` | Sign inspection |

### 6.12 Reports
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/pm/reports/rent-roll` | Rent roll report |
| GET | `/pm/reports/income` | Income report |
| GET | `/pm/reports/expenses` | Expenses report |
| GET | `/pm/reports/pnl` | Profit & Loss report |
| GET | `/pm/reports/occupancy` | Occupancy report |
| GET | `/pm/reports/maintenance` | Maintenance report |

---

## 7. Data Models & Schemas

### 7.1 Property Status Enums
- `ManagedPropertyStatus`: `draft | active | archived`
- `PropertyStatus`: `available | sold | rented | under_offer | maintenance`

### 7.2 Lease Enums
- `LeaseStatus`: `draft | pending_signature | active | expiring_soon | expired | terminated | renewed`

### 7.3 Rent Enums
- `RentChargeStatus`: `pending | partial | paid | overdue | waived`
- Payment methods: `bank_transfer | cash | check | card`

### 7.4 Expense Categories
- `maintenance | repairs | insurance | property_tax | hoa | utilities | marketing | legal | other`

### 7.5 Maintenance Enums
- `MaintenanceCategory`: `plumbing | electrical | hvac | appliance | structural | pest_control | cleaning | other`
- `MaintenanceUrgency`: `emergency | high | medium | low`
- `MaintenanceRequestStatus`: `open | in_review | work_order_created | resolved | closed`
- `WorkOrderStatus`: `created | assigned | in_progress | completed | closed | cancelled`

### 7.6 Document Types
- `lease_agreement | id_proof | address_proof | income_proof | inspection_report | receipt | invoice | property_deed | insurance_policy | other`

### 7.7 Inspection Types
- `move_in | move_out | routine`

---

## 8. User Flows

### 8.1 Owner Adds New Property
1. Navigate to Properties Tab → Tap "+" FAB → "Add Property"
2. Step 1: Enter basic details (title, type, address, rent)
3. Step 2: Add specifications (beds, baths, area, photos)
4. Step 3: Set management defaults (due day, grace period, late fee)
5. Tap "Save Property"
6. Property appears in list → Route to Property Detail

### 8.2 Owner Collects Rent
1. Navigate to Finance Tab → Rent Charges
2. Tap "Generate Charges"
3. Select scope (all leases or specific) + month(s)
4. Tap "Generate"
5. View generated charges with status (pending/overdue)
6. Tap a charge → Tap "Record Payment"
7. Enter amount, method, reference, upload receipt
8. Tap "Submit" → Charge status updates

### 8.3 Owner Onboards Tenant via Application
1. Navigate to More Tab → Applications → Create Form
2. Fill form details, select property, add questions
3. Tap "Create" → Get share link
4. Share link with prospects (WhatsApp, email)
5. Monitor submissions in Applications Inbox
6. Tap a submission → Review answers + documents
7. Tap "Approve" → CTA: "Create Lease"
8. Pre-filled lease form appears with tenant details
9. Complete lease details → Create
10. Upload signed lease (optional for MVP)

### 8.4 Owner Handles Maintenance Request
1. Navigate to More Tab → Maintenance
2. View open requests (filter by status/urgency)
3. Tap a request → View details
4. Tap "Assign" (assign to self or RM)
5. Set priority, schedule, estimate cost
6. Update status to "In Progress"
7. After completion → Tap "Complete"
8. Add actual cost, upload completion photos, add notes
9. Tap "Close Request"

### 8.5 Owner Generates Reports
1. Navigate to More Tab → Reports
2. Select report type (Rent Roll, Income, P&L, etc.)
3. Set date range, property filter
4. Tap "Generate Report"
5. View report data
6. Tap "Export CSV" → Client generates and downloads CSV

---

## 9. Error Handling

### 9.1 Common HTTP Status Codes
| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Proceed |
| 400 | Bad Request | Show validation error message |
| 401 | Unauthorized | Clear token, route to login |
| 403 | Forbidden | Show "Access denied" message |
| 404 | Not Found | Show "Resource not found" |
| 422 | Validation Error | Map field errors to UI inputs |
| 429 | Too Many Requests | Show "Rate limited, try again later" |
| 500 | Server Error | Show generic error, retry option |

### 9.2 Error Response Format
```json
{
  "detail": "Error message for user display",
  "errors": {
    "field_name": "Specific validation error"
  }
}
```

### 9.3 Network Error Handling
- Show offline indicator when no network
- Queue offline actions (local storage) and sync on reconnect (Phase 2)
- Retry failed requests with exponential backoff

---
