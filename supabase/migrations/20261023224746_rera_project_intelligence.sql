-- REP-I project intelligence: the filing detail that the list scraper never sees.
--
-- One filing page per project (haryanarera.gov.in/view_project/project_preview_open/{id})
-- supplies every row below. Collection tables are replaced wholesale only after a
-- filing parses in full, so a failed parse cannot leave a half-written filing.
-- Every table cites the source_documents row it came from.
--
-- Additive only: no existing column is changed and no existing row is touched.

-- Public URL key for a project. Derived from the project name and the RERA
-- number, so it is unique by construction (the RERA number is unique). Rows the
-- register had before this column keep a null slug and are skipped by the
-- detail scraper until their next list refresh fills it in.
ALTER TABLE rera_projects ADD COLUMN IF NOT EXISTS slug VARCHAR(300);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rera_projects_slug ON rera_projects (slug);

CREATE TYPE project_stage AS ENUM (
    'pre_launch', 'under_construction', 'near_possession', 'completed'
);
CREATE TYPE project_price_source AS ENUM ('launch', 'filing', 'derived');
CREATE TYPE project_person_role AS ENUM (
    'chairman', 'managing_director', 'director', 'authorised_representative', 'licensee', 'other'
);
CREATE TYPE market_sentiment AS ENUM ('positive', 'neutral', 'negative');

-- 1:1 scalar facts from REP-I Parts A/C/D that do not fit rera_projects.
CREATE TABLE rera_project_profiles (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    portal_project_id VARCHAR(50),
    licensed_land_acres NUMERIC(12,4),
    land_area_sqm NUMERIC(14,2),
    proposed_far NUMERIC(8,4),
    permissible_far NUMERIC(8,4),
    towers INTEGER,
    floors INTEGER,
    total_units INTEGER,
    units_per_acre NUMERIC(10,2),
    rera_received_date DATE,
    construction_start_date DATE,
    proposed_completion_date DATE,
    launch_price_per_sqft NUMERIC(12,2),
    current_price_per_sqft NUMERIC(12,2),
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    stage project_stage,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_profiles_project UNIQUE (rera_project_id)
);
CREATE INDEX idx_rera_project_profiles_stage ON rera_project_profiles (stage);

CREATE TABLE rera_land_usage (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    particular VARCHAR(200) NOT NULL,
    area_sqm NUMERIC(14,2),
    area_acres NUMERIC(12,4),
    percentage NUMERIC(6,2),
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_land_usage_project_particular UNIQUE (rera_project_id, particular)
);
CREATE INDEX idx_rera_land_usage_project ON rera_land_usage (rera_project_id);

-- 1:1 cost breakdown. Amounts are in rupees as filed.
CREATE TABLE rera_project_costs (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    land_cost NUMERIC(18,2),
    construction_cost NUMERIC(18,2),
    infrastructure_cost NUMERIC(18,2),
    other_cost NUMERIC(18,2),
    total_cost NUMERIC(18,2),
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_costs_project UNIQUE (rera_project_id)
);

-- 7-year quarterly expenditure, per category and particular.
CREATE TABLE rera_quarterly_expenditure (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    category VARCHAR(50) NOT NULL,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    particular VARCHAR(300) NOT NULL,
    amount NUMERIC(18,2),
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_quarterly_expenditure_point
        UNIQUE (rera_project_id, category, year, quarter, particular)
);
CREATE INDEX idx_rera_quarterly_expenditure_project ON rera_quarterly_expenditure (rera_project_id);

-- ordinal is the document's position in the filing table.
CREATE TABLE rera_project_documents (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    description VARCHAR(500) NOT NULL,
    uploaded_on DATE,
    view_url TEXT,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_documents_project_ordinal UNIQUE (rera_project_id, ordinal)
);
CREATE INDEX idx_rera_project_documents_project ON rera_project_documents (rera_project_id);

-- 1:1 statutory approvals and utility availability.
CREATE TABLE rera_statutory_approvals (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    loi_number VARCHAR(200),
    loi_date DATE,
    licence_number VARCHAR(200),
    licence_date DATE,
    electric_load_kw NUMERIC(12,2),
    water_available BOOLEAN,
    storm_water_available BOOLEAN,
    sewerage_available BOOLEAN,
    plan_approvals JSONB,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_statutory_approvals_project UNIQUE (rera_project_id)
);

CREATE TABLE rera_project_facilities (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    facility VARCHAR(200) NOT NULL,
    estimated_cost NUMERIC(18,2),
    status VARCHAR(200),
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_facilities_project_facility UNIQUE (rera_project_id, facility)
);
CREATE INDEX idx_rera_project_facilities_project ON rera_project_facilities (rera_project_id);

CREATE TABLE rera_project_nocs (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    facility VARCHAR(200) NOT NULL,
    provider_agency VARCHAR(300),
    approved BOOLEAN,
    approval_reference VARCHAR(300),
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_nocs_project_facility UNIQUE (rera_project_id, facility)
);
CREATE INDEX idx_rera_project_nocs_project ON rera_project_nocs (rera_project_id);

-- Promoter-side people. Only the last four PAN characters are stored: the filing
-- publishes the full identifier, but keeping the rest out of our database means a
-- leak here cannot expose it. Contact details never leave the backend.
CREATE TABLE rera_project_people (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    role project_person_role NOT NULL,
    name VARCHAR(300) NOT NULL,
    pan_last4 VARCHAR(4),
    email VARCHAR(300),
    phones TEXT,
    address TEXT,
    photo_url TEXT,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_people_role_name UNIQUE (rera_project_id, role, name)
);
CREATE INDEX idx_rera_project_people_project ON rera_project_people (rera_project_id);

-- The designated collection account. Stored because the filing states it and
-- reconciliation needs it; never part of a public response payload.
CREATE TABLE rera_project_bank_accounts (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    bank_name VARCHAR(200),
    branch_name VARCHAR(200),
    account_number VARCHAR(50),
    ifsc VARCHAR(20),
    micr VARCHAR(20),
    branch_code VARCHAR(20),
    operators TEXT,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_bank_accounts_project UNIQUE (rera_project_id)
);

CREATE TABLE rera_project_unit_configs (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    unit_type VARCHAR(200) NOT NULL,
    carpet_area_sqm NUMERIC(12,2),
    built_up_area_sqm NUMERIC(12,2),
    super_built_up_area_sqm NUMERIC(12,2),
    carpet_efficiency NUMERIC(6,4),
    units INTEGER,
    towers INTEGER,
    parkings INTEGER,
    price NUMERIC(18,2),
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_unit_configs_project_ordinal UNIQUE (rera_project_id, ordinal)
);
CREATE INDEX idx_rera_project_unit_configs_project ON rera_project_unit_configs (rera_project_id);

-- scope is 'project' or 'unit'; unit_type is 'all' for project-wide lines.
CREATE TABLE rera_project_specifications (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    scope VARCHAR(20) NOT NULL,
    unit_type VARCHAR(200) NOT NULL DEFAULT 'all',
    spec_key VARCHAR(200) NOT NULL,
    spec_value TEXT,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rera_project_specifications_line
        UNIQUE (rera_project_id, scope, unit_type, spec_key)
);
CREATE INDEX idx_rera_project_specifications_project ON rera_project_specifications (rera_project_id);

-- A promoter organisation, one row per slug shared by every project it filed.
CREATE TABLE developers (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(300) NOT NULL,
    name VARCHAR(500) NOT NULL,
    legal_name VARCHAR(500),
    logo_url TEXT,
    website_url TEXT,
    cin VARCHAR(30),
    summary TEXT,
    dossier TEXT,
    founded_year INTEGER,
    is_listed BOOLEAN,
    headquarters VARCHAR(300),
    geographies JSONB,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    last_checked_at TIMESTAMPTZ,
    last_successful_run_id INTEGER REFERENCES scraper_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_developers_slug ON developers (slug);

CREATE TABLE developer_scores (
    id SERIAL PRIMARY KEY,
    developer_id INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    delivery NUMERIC(5,2),
    regulatory NUMERIC(5,2),
    complaints NUMERIC(5,2),
    financials NUMERIC(5,2),
    market_reception NUMERIC(5,2),
    total_score NUMERIC(5,2),
    project_count INTEGER NOT NULL DEFAULT 0,
    delivered_count INTEGER NOT NULL DEFAULT 0,
    under_construction_count INTEGER NOT NULL DEFAULT 0,
    complaint_count INTEGER NOT NULL DEFAULT 0,
    computed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_developer_scores_developer UNIQUE (developer_id)
);
CREATE INDEX idx_developer_scores_developer ON developer_scores (developer_id);
CREATE INDEX idx_developer_scores_total ON developer_scores (total_score);

-- filing and launch points are read from a filing; derived points are computed
-- from them and are marked as such, so a derived number is never mistaken for a
-- filed one.
CREATE TABLE project_price_history (
    id SERIAL PRIMARY KEY,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    quarter VARCHAR(7) NOT NULL,
    period_start DATE,
    unit_type VARCHAR(200) NOT NULL DEFAULT 'all',
    price_per_sqft NUMERIC(12,2),
    source project_price_source NOT NULL,
    source_document_id BIGINT REFERENCES source_documents(id) ON DELETE SET NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_price_history_point
        UNIQUE (rera_project_id, quarter, unit_type, source)
);
CREATE INDEX idx_project_price_history_project ON project_price_history (rera_project_id);

CREATE TABLE micro_markets (
    id SERIAL PRIMARY KEY,
    city VARCHAR(100) NOT NULL,
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(300) NOT NULL,
    district VARCHAR(100),
    summary TEXT,
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_micro_markets_city_slug UNIQUE (city, slug)
);
CREATE INDEX idx_micro_markets_city ON micro_markets (city);

CREATE TABLE project_watchlist (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rera_project_id INTEGER NOT NULL REFERENCES rera_projects(id) ON DELETE CASCADE,
    notes TEXT,
    alert_prefs JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_watchlist_user_project UNIQUE (user_id, rera_project_id)
);
CREATE INDEX idx_project_watchlist_user_id ON project_watchlist (user_id);
CREATE INDEX idx_project_watchlist_rera_project_id ON project_watchlist (rera_project_id);

-- One city's market reading for a day. Rows are the history; nothing is overwritten.
CREATE TABLE market_pulse_snapshots (
    id SERIAL PRIMARY KEY,
    city VARCHAR(100) NOT NULL,
    captured_on DATE NOT NULL,
    sentiment market_sentiment NOT NULL,
    avg_price_per_sqft NUMERIC(12,2),
    price_change_90d_pct NUMERIC(6,2),
    new_registrations INTEGER NOT NULL DEFAULT 0,
    new_complaints INTEGER NOT NULL DEFAULT 0,
    computed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_market_pulse_snapshots_city_day UNIQUE (city, captured_on)
);
CREATE INDEX idx_market_pulse_snapshots_city ON market_pulse_snapshots (city);

-- Deny direct PostgREST reads on user-owned and personally identifying tables.
-- The backend connects as the table owner and is not affected.
ALTER TABLE project_watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE rera_project_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE rera_project_bank_accounts ENABLE ROW LEVEL SECURITY;
