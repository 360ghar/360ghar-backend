-- ============================================================
-- 360Ghar Schema — 03: Property Management
-- ============================================================
-- PM enums, documents, rental applications, leases,
-- rent charges/payments, expenses, maintenance requests,
-- inspection checklists
-- ============================================================

CREATE TYPE tenant_status AS ENUM ('applicant', 'approved', 'active', 'notice_period', 'vacated', 'rejected');
CREATE TYPE lease_status AS ENUM ('draft', 'pending_signature', 'active', 'expiring_soon', 'expired', 'terminated', 'renewed');
CREATE TYPE rent_charge_status AS ENUM ('pending', 'partial', 'paid', 'overdue', 'waived');
CREATE TYPE expense_category AS ENUM ('maintenance', 'repairs', 'insurance', 'property_tax', 'hoa', 'utilities', 'marketing', 'legal', 'other');
CREATE TYPE maintenance_urgency AS ENUM ('emergency', 'high', 'medium', 'low');
CREATE TYPE maintenance_category AS ENUM ('plumbing', 'electrical', 'hvac', 'appliance', 'structural', 'pest_control', 'cleaning', 'other');
CREATE TYPE maintenance_request_status AS ENUM ('open', 'in_review', 'work_order_created', 'resolved', 'closed');
CREATE TYPE work_order_status AS ENUM ('created', 'assigned', 'in_progress', 'completed', 'closed', 'cancelled');
CREATE TYPE document_type AS ENUM ('lease_agreement', 'id_proof', 'address_proof', 'income_proof', 'inspection_report', 'receipt', 'invoice', 'property_deed', 'insurance_policy', 'other');
CREATE TYPE inspection_type AS ENUM ('move_in', 'move_out', 'routine');

-- ============================================================
-- Documents vault (created first — FK targets exist)
-- ============================================================
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(id),
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    property_id BIGINT REFERENCES properties(id) ON DELETE SET NULL,
    lease_id BIGINT,                     -- FK added after leases table
    maintenance_request_id BIGINT,       -- FK added after maintenance_requests table
    rental_application_id BIGINT,        -- FK added after rental_applications table
    document_type document_type NOT NULL,
    title TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_path TEXT,
    mime_type TEXT,
    file_size INTEGER,
    shared_with_tenant BOOLEAN DEFAULT FALSE,
    shared_with_agent BOOLEAN DEFAULT FALSE,
    version INTEGER DEFAULT 1,
    replaces_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_documents_owner_id ON documents(owner_id);
CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_documents_property_id ON documents(property_id);
CREATE INDEX idx_documents_created_at ON documents(created_at DESC);
CREATE TRIGGER update_documents_updated_at
    BEFORE UPDATE ON documents FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Rental application forms
-- ============================================================
CREATE TABLE rental_application_forms (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(id),
    property_id BIGINT REFERENCES properties(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    slug TEXT NOT NULL UNIQUE,
    is_active BOOLEAN DEFAULT TRUE,
    application_fee_amount REAL,
    required_document_types JSONB,
    questions JSONB,
    config JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_rental_application_forms_owner_id ON rental_application_forms(owner_id);
CREATE INDEX idx_rental_application_forms_property_id ON rental_application_forms(property_id);
CREATE TRIGGER update_rental_application_forms_updated_at
    BEFORE UPDATE ON rental_application_forms FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Rental applications
-- ============================================================
CREATE TABLE rental_applications (
    id BIGSERIAL PRIMARY KEY,
    form_id BIGINT NOT NULL REFERENCES rental_application_forms(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status tenant_status DEFAULT 'applicant',
    applicant_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    applicant_full_name TEXT,
    applicant_phone TEXT,
    applicant_email TEXT,
    answers JSONB,
    application_data JSONB,
    emergency_contacts JSONB,
    submitted_at TIMESTAMPTZ,
    decision_at TIMESTAMPTZ,
    decided_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_rental_applications_owner_id ON rental_applications(owner_id);
CREATE INDEX idx_rental_applications_property_id ON rental_applications(property_id);
CREATE INDEX idx_rental_applications_form_id ON rental_applications(form_id);
CREATE INDEX idx_rental_applications_status ON rental_applications(status);
CREATE INDEX idx_rental_applications_submitted_at ON rental_applications(submitted_at DESC);
CREATE TRIGGER update_rental_applications_updated_at
    BEFORE UPDATE ON rental_applications FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE documents
    ADD CONSTRAINT fk_documents_rental_application_id
    FOREIGN KEY (rental_application_id) REFERENCES rental_applications(id) ON DELETE SET NULL;
CREATE INDEX idx_documents_rental_application_id ON documents(rental_application_id);

-- ============================================================
-- Leases (with termination fields)
-- ============================================================
CREATE TABLE leases (
    id BIGSERIAL PRIMARY KEY,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    tenant_name TEXT,
    tenant_phone TEXT,
    tenant_email TEXT,
    status lease_status NOT NULL DEFAULT 'draft',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    monthly_rent REAL NOT NULL,
    security_deposit REAL NOT NULL,
    late_fee_amount REAL,
    late_fee_percentage REAL,
    grace_period_days INTEGER DEFAULT 5,
    payment_due_day INTEGER DEFAULT 1,
    lease_terms JSONB,
    special_clauses TEXT,
    signed_by_tenant_at TIMESTAMPTZ,
    signed_by_owner_at TIMESTAMPTZ,
    lease_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    termination_date DATE,
    termination_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_leases_owner_id ON leases(owner_id);
CREATE INDEX idx_leases_property_id ON leases(property_id);
CREATE INDEX idx_leases_tenant_user_id ON leases(tenant_user_id);
CREATE INDEX idx_leases_status ON leases(status);
CREATE INDEX idx_leases_end_date ON leases(end_date);
CREATE UNIQUE INDEX uq_leases_property_active ON leases(property_id) WHERE status = 'active';
CREATE TRIGGER update_leases_updated_at
    BEFORE UPDATE ON leases FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE documents
    ADD CONSTRAINT fk_documents_lease_id
    FOREIGN KEY (lease_id) REFERENCES leases(id) ON DELETE SET NULL;
CREATE INDEX idx_documents_lease_id ON documents(lease_id);

-- Link properties.current_lease_id to leases
ALTER TABLE properties
    ADD CONSTRAINT fk_properties_current_lease_id
    FOREIGN KEY (current_lease_id) REFERENCES leases(id) ON DELETE SET NULL;

-- ============================================================
-- Rent charges and payments
-- ============================================================
CREATE TABLE rent_charges (
    id BIGSERIAL PRIMARY KEY,
    lease_id BIGINT NOT NULL REFERENCES leases(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    billing_month DATE NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    due_date DATE NOT NULL,
    amount_due REAL NOT NULL,
    late_fee_assessed REAL DEFAULT 0,
    status rent_charge_status NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    CONSTRAINT uq_rent_charges_lease_month UNIQUE (lease_id, billing_month)
);
CREATE INDEX idx_rent_charges_owner_id ON rent_charges(owner_id);
CREATE INDEX idx_rent_charges_property_id ON rent_charges(property_id);
CREATE INDEX idx_rent_charges_tenant_user_id ON rent_charges(tenant_user_id);
CREATE INDEX idx_rent_charges_due_date ON rent_charges(due_date);
CREATE INDEX idx_rent_charges_status ON rent_charges(status);
CREATE TRIGGER update_rent_charges_updated_at
    BEFORE UPDATE ON rent_charges FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE rent_payments (
    id BIGSERIAL PRIMARY KEY,
    charge_id BIGINT NOT NULL REFERENCES rent_charges(id) ON DELETE CASCADE,
    lease_id BIGINT NOT NULL REFERENCES leases(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    paid_at TIMESTAMPTZ NOT NULL,
    amount_paid REAL NOT NULL,
    payment_method TEXT,
    reference TEXT,
    notes TEXT,
    receipt_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_rent_payments_charge_id ON rent_payments(charge_id);
CREATE INDEX idx_rent_payments_owner_id ON rent_payments(owner_id);
CREATE INDEX idx_rent_payments_property_id ON rent_payments(property_id);
CREATE INDEX idx_rent_payments_lease_id ON rent_payments(lease_id);
CREATE INDEX idx_rent_payments_paid_at ON rent_payments(paid_at DESC);
CREATE TRIGGER update_rent_payments_updated_at
    BEFORE UPDATE ON rent_payments FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Expenses
-- ============================================================
CREATE TABLE expenses (
    id BIGSERIAL PRIMARY KEY,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category expense_category NOT NULL,
    amount REAL NOT NULL,
    expense_date DATE NOT NULL,
    description TEXT,
    notes TEXT,
    receipt_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    is_recurring BOOLEAN DEFAULT FALSE,
    recurrence_rule JSONB,
    next_due_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_expenses_owner_id ON expenses(owner_id);
CREATE INDEX idx_expenses_property_id ON expenses(property_id);
CREATE INDEX idx_expenses_expense_date ON expenses(expense_date DESC);
CREATE INDEX idx_expenses_category ON expenses(category);
CREATE TRIGGER update_expenses_updated_at
    BEFORE UPDATE ON expenses FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Maintenance requests
-- ============================================================
CREATE TABLE maintenance_requests (
    id BIGSERIAL PRIMARY KEY,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    lease_id BIGINT REFERENCES leases(id) ON DELETE SET NULL,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    category maintenance_category NOT NULL,
    urgency maintenance_urgency NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    preferred_contact_method TEXT,
    availability_notes TEXT,
    request_status maintenance_request_status NOT NULL DEFAULT 'open',
    assigned_agent_id BIGINT REFERENCES agents(id) ON DELETE SET NULL,
    work_order_status work_order_status,
    priority TEXT,
    estimated_cost REAL,
    actual_cost REAL,
    scheduled_for TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    completion_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_maintenance_requests_owner_id ON maintenance_requests(owner_id);
CREATE INDEX idx_maintenance_requests_property_id ON maintenance_requests(property_id);
CREATE INDEX idx_maintenance_requests_lease_id ON maintenance_requests(lease_id);
CREATE INDEX idx_maintenance_requests_tenant_user_id ON maintenance_requests(tenant_user_id);
CREATE INDEX idx_maintenance_requests_request_status ON maintenance_requests(request_status);
CREATE INDEX idx_maintenance_requests_work_order_status ON maintenance_requests(work_order_status);
CREATE INDEX idx_maintenance_requests_created_at ON maintenance_requests(created_at DESC);
CREATE TRIGGER update_maintenance_requests_updated_at
    BEFORE UPDATE ON maintenance_requests FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE documents
    ADD CONSTRAINT fk_documents_maintenance_request_id
    FOREIGN KEY (maintenance_request_id) REFERENCES maintenance_requests(id) ON DELETE SET NULL;
CREATE INDEX idx_documents_maintenance_request_id ON documents(maintenance_request_id);

-- ============================================================
-- Inspection checklists
-- ============================================================
CREATE TABLE inspection_checklists (
    id BIGSERIAL PRIMARY KEY,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    lease_id BIGINT NOT NULL REFERENCES leases(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    inspection_type inspection_type NOT NULL,
    conducted_by_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conducted_at TIMESTAMPTZ NOT NULL,
    rooms_data JSONB,
    overall_notes TEXT,
    tenant_signature_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    owner_signature_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    signed_by_tenant_at TIMESTAMPTZ,
    signed_by_owner_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_inspection_checklists_owner_id ON inspection_checklists(owner_id);
CREATE INDEX idx_inspection_checklists_property_id ON inspection_checklists(property_id);
CREATE INDEX idx_inspection_checklists_lease_id ON inspection_checklists(lease_id);
CREATE INDEX idx_inspection_checklists_conducted_at ON inspection_checklists(conducted_at DESC);
CREATE TRIGGER update_inspection_checklists_updated_at
    BEFORE UPDATE ON inspection_checklists FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
