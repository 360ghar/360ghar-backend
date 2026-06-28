-- ============================================================
-- 360Ghar Schema — 06: Data Hub
-- ============================================================
-- 13 core tables for public real estate data aggregation.
-- All auction_source enum values (28) from the start.
-- ============================================================

CREATE TYPE scraper_status AS ENUM ('running', 'success', 'partial', 'failed');
CREATE TYPE auction_source AS ENUM (
    'sarfaesi', 'ibapi', 'mstc', 'drt', 'ecourts',
    'ibbi', 'baanknet', 'dda', 'dfc_delhi',
    'hsvp', 'hsvp_procure247', 'dtcp', 'mda', 'yeida',
    'bank_eauctions', 'eauctions_india', 'auction_bazaar',
    'eauction_dekho', 'findauction', 'findauction_prop', 'auction_tiger',
    'sbi', 'pnb', 'bob', 'canara', 'hdfc', 'icici', 'union', 'yes_bank'
);
CREATE TYPE gazette_type AS ENUM ('land_acquisition', 'rate_revision', 'policy', 'clu_change');
CREATE TYPE complaint_nature AS ENUM ('delay', 'quality', 'refund', 'compensation', 'other');

-- circle_rates
CREATE TABLE circle_rates (
    id SERIAL PRIMARY KEY,
    district VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    tehsil VARCHAR(100),
    sector VARCHAR(200) NOT NULL,
    colony VARCHAR(200),
    property_type VARCHAR(50) NOT NULL,
    rate_per_sqyd NUMERIC(12,2),
    rate_per_sqft NUMERIC(12,2),
    rate_per_sqm NUMERIC(12,2),
    revision_year INTEGER NOT NULL,
    effective_date DATE,
    source_url TEXT,
    slug VARCHAR(300) NOT NULL,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(sector, colony, property_type, revision_year)
);
CREATE UNIQUE INDEX idx_circle_rates_slug ON circle_rates (slug);
CREATE INDEX idx_circle_rates_sector_type ON circle_rates (sector, property_type);
CREATE INDEX idx_circle_rates_revision_year ON circle_rates (revision_year DESC);

-- rera_projects
CREATE TABLE rera_projects (
    id SERIAL PRIMARY KEY,
    rera_number VARCHAR(200) NOT NULL UNIQUE,
    project_name VARCHAR(500) NOT NULL,
    developer_name VARCHAR(500),
    developer_slug VARCHAR(300),
    location VARCHAR(500),
    district VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    total_units INTEGER,
    units_booked INTEGER,
    possession_date DATE,
    registration_date DATE,
    expiry_date DATE,
    status VARCHAR(50),
    project_type VARCHAR(100),
    total_area_sqm NUMERIC(12,2),
    complaint_count INTEGER DEFAULT 0,
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rera_projects_developer_slug ON rera_projects (developer_slug);
CREATE INDEX idx_rera_projects_status ON rera_projects (status);
CREATE INDEX idx_rera_projects_location ON rera_projects (location);

-- bank_auctions
CREATE TABLE bank_auctions (
    id SERIAL PRIMARY KEY,
    source auction_source NOT NULL,
    bank_name VARCHAR(200) NOT NULL,
    property_description TEXT NOT NULL,
    property_type VARCHAR(50),
    area_sqft NUMERIC(12,2),
    city VARCHAR(100) NOT NULL DEFAULT 'Delhi NCR',
    locality VARCHAR(300),
    full_address TEXT,
    reserve_price NUMERIC(15,2),
    emd_amount NUMERIC(15,2),
    auction_date DATE,
    auction_end_date DATE,
    possession_type VARCHAR(50),
    contact_person VARCHAR(200),
    contact_phone VARCHAR(50),
    contact_email VARCHAR(200),
    source_url TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_data JSONB,
    normalized_address_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(bank_name, normalized_address_hash, auction_date)
);
CREATE UNIQUE INDEX uq_bank_auctions_key ON bank_auctions (bank_name, normalized_address_hash, auction_date);
CREATE INDEX idx_bank_auctions_city_active ON bank_auctions (city, is_active);
CREATE INDEX idx_bank_auctions_auction_date ON bank_auctions (auction_date DESC) WHERE is_active;
CREATE INDEX idx_bank_auctions_type_active ON bank_auctions (property_type, is_active);
CREATE INDEX idx_bank_auctions_reserve_price ON bank_auctions (reserve_price) WHERE is_active;
CREATE INDEX idx_bank_auctions_city ON bank_auctions (city);
CREATE INDEX idx_bank_auctions_source ON bank_auctions (source);

-- auction_alerts
CREATE TABLE auction_alerts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    city VARCHAR(100) NOT NULL DEFAULT 'Delhi NCR',
    property_type VARCHAR(50),
    min_price NUMERIC(15,2),
    max_price NUMERIC(15,2),
    bank_name VARCHAR(200),
    keyword TEXT,
    alert_channels JSONB DEFAULT '["email"]',
    is_active BOOLEAN DEFAULT TRUE,
    last_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_auction_alerts_user_active ON auction_alerts (user_id, is_active);

-- bank_rates
CREATE TABLE bank_rates (
    id SERIAL PRIMARY KEY,
    bank_name VARCHAR(200) NOT NULL,
    rate_type VARCHAR(50) NOT NULL,
    rate_value NUMERIC(6,4) NOT NULL,
    effective_date DATE,
    source VARCHAR(200),
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(bank_name, rate_type, effective_date)
);
CREATE UNIQUE INDEX uq_bank_rates_key ON bank_rates (bank_name, rate_type, effective_date);
CREATE INDEX idx_bank_rates_bank_type ON bank_rates (bank_name, rate_type);

-- jamabandi_cache
CREATE TABLE jamabandi_cache (
    id SERIAL PRIMARY KEY,
    tehsil VARCHAR(200) NOT NULL,
    village VARCHAR(200) NOT NULL,
    khasra_number VARCHAR(100) NOT NULL,
    khewat_number VARCHAR(100),
    owner_names JSONB,
    area_kanal NUMERIC(10,4),
    area_marla NUMERIC(10,4),
    mutation_status VARCHAR(100),
    encumbrance_details TEXT,
    survey_number VARCHAR(100),
    source_html TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE(tehsil, village, khasra_number)
);
CREATE INDEX idx_jamabandi_cache_lookup ON jamabandi_cache (tehsil, village, khasra_number);
CREATE INDEX idx_jamabandi_cache_expires ON jamabandi_cache (expires_at);

-- zoning_data
CREATE TABLE zoning_data (
    id SERIAL PRIMARY KEY,
    sector VARCHAR(200) NOT NULL,
    slug VARCHAR(300) NOT NULL,
    land_use VARCHAR(100),
    far_limit NUMERIC(6,2),
    max_height_m NUMERIC(8,2),
    max_coverage_pct NUMERIC(5,2),
    setback_front_m NUMERIC(6,2),
    setback_rear_m NUMERIC(6,2),
    master_plan_year INTEGER,
    notes TEXT,
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(sector, land_use)
);
CREATE UNIQUE INDEX idx_zoning_data_slug ON zoning_data (slug);

-- colony_approvals
CREATE TABLE colony_approvals (
    id SERIAL PRIMARY KEY,
    colony_name VARCHAR(300) NOT NULL,
    developer_name VARCHAR(300),
    district VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    licence_number VARCHAR(100),
    approval_status VARCHAR(50),
    clu_status VARCHAR(50),
    approval_date DATE,
    area_acres NUMERIC(10,4),
    sector VARCHAR(200),
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_colony_approvals_unique_with_licence
    ON colony_approvals (colony_name, licence_number) WHERE licence_number IS NOT NULL;
CREATE UNIQUE INDEX idx_colony_approvals_unique_no_licence
    ON colony_approvals (colony_name) WHERE licence_number IS NULL;
CREATE INDEX idx_colony_approvals_sector ON colony_approvals (sector);

-- gazette_notifications
CREATE TABLE gazette_notifications (
    id SERIAL PRIMARY KEY,
    notification_number VARCHAR(200),
    notification_date DATE,
    department VARCHAR(200),
    notification_type gazette_type,
    title TEXT NOT NULL,
    summary TEXT,
    pdf_url TEXT,
    pdf_text TEXT,
    relevance_tags JSONB,
    relevance_score NUMERIC(3,2),
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_gazette_unique_with_number
    ON gazette_notifications (notification_number, notification_date) WHERE notification_number IS NOT NULL;
CREATE UNIQUE INDEX idx_gazette_unique_no_number
    ON gazette_notifications (title, notification_date) WHERE notification_number IS NULL;
CREATE INDEX idx_gazette_notifications_date ON gazette_notifications (notification_date DESC);
CREATE INDEX idx_gazette_notifications_type ON gazette_notifications (notification_type);
CREATE INDEX idx_gazette_notifications_tags ON gazette_notifications USING GIN (relevance_tags);

-- rera_complaints
CREATE TABLE rera_complaints (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(200) NOT NULL UNIQUE,
    order_date DATE,
    complainant_type VARCHAR(50),
    respondent_builder VARCHAR(300),
    respondent_project VARCHAR(500),
    rera_number VARCHAR(100),
    complaint_nature complaint_nature,
    order_summary TEXT,
    penalty_amount NUMERIC(15,2),
    direction_type VARCHAR(100),
    pdf_url TEXT,
    pdf_text TEXT,
    builder_slug VARCHAR(300),
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rera_complaints_builder_slug ON rera_complaints (builder_slug);
CREATE INDEX idx_rera_complaints_rera_number ON rera_complaints (rera_number);
CREATE INDEX idx_rera_complaints_order_date ON rera_complaints (order_date DESC);

-- court_auctions
CREATE TABLE court_auctions (
    id SERIAL PRIMARY KEY,
    source auction_source NOT NULL,
    case_number VARCHAR(200) NOT NULL,
    borrower_name VARCHAR(300),
    property_description TEXT,
    property_type VARCHAR(50),
    city VARCHAR(100) NOT NULL DEFAULT 'Delhi NCR',
    locality VARCHAR(300),
    reserve_price NUMERIC(15,2),
    auction_date DATE,
    presiding_officer VARCHAR(200),
    court_name VARCHAR(200),
    contact_details TEXT,
    source_url TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(case_number, auction_date)
);
CREATE INDEX idx_court_auctions_city_active ON court_auctions (city, is_active);
CREATE INDEX idx_court_auctions_auction_date ON court_auctions (auction_date DESC) WHERE is_active;
CREATE INDEX idx_court_auctions_city ON court_auctions (city);

-- neighbourhood_scores
CREATE TABLE neighbourhood_scores (
    id SERIAL PRIMARY KEY,
    listing_id BIGINT REFERENCES properties(id) ON DELETE CASCADE,
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    overall_score INTEGER,
    category_scores JSONB,
    nearby_places JSONB,
    metro_stations JSONB,
    schools JSONB,
    hospitals JSONB,
    malls JSONB,
    it_parks JSONB,
    landmarks JSONB,
    api_calls_made INTEGER DEFAULT 0,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stale_after TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(listing_id)
);
CREATE INDEX idx_neighbourhood_scores_stale ON neighbourhood_scores (stale_after);

-- scraper_runs
CREATE TABLE scraper_runs (
    id SERIAL PRIMARY KEY,
    scraper_name VARCHAR(100) NOT NULL,
    run_type VARCHAR(20) DEFAULT 'cron',
    triggered_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    status scraper_status NOT NULL DEFAULT 'running',
    records_found INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    metadata JSONB
);
CREATE INDEX idx_scraper_runs_name_started ON scraper_runs (scraper_name, started_at DESC);

-- updated_at triggers for all data hub tables
CREATE TRIGGER update_circle_rates_updated_at BEFORE UPDATE ON circle_rates FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_rera_projects_updated_at BEFORE UPDATE ON rera_projects FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_bank_auctions_updated_at BEFORE UPDATE ON bank_auctions FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_auction_alerts_updated_at BEFORE UPDATE ON auction_alerts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_bank_rates_updated_at BEFORE UPDATE ON bank_rates FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_zoning_data_updated_at BEFORE UPDATE ON zoning_data FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_colony_approvals_updated_at BEFORE UPDATE ON colony_approvals FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_gazette_notifications_updated_at BEFORE UPDATE ON gazette_notifications FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_rera_complaints_updated_at BEFORE UPDATE ON rera_complaints FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_court_auctions_updated_at BEFORE UPDATE ON court_auctions FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_neighbourhood_scores_updated_at BEFORE UPDATE ON neighbourhood_scores FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
