-- 360Ghar Data Hub: 13 core tables for public data aggregation
-- Covers: circle rates, RERA projects/complaints, bank auctions, court auctions,
--         auction alerts, bank rates, jamabandi cache, zoning data,
--         colony approvals, gazette notifications, neighbourhood scores,
--         and scraper run audit logs

-- ---------------------------------------------------------------------------
-- 1. circle_rates
--    Circle rate data per sector for stamp duty calculation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS circle_rates (
    id SERIAL PRIMARY KEY,
    district VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    tehsil VARCHAR(100),
    sector VARCHAR(200) NOT NULL,
    colony VARCHAR(200),
    property_type VARCHAR(50) NOT NULL,  -- residential, commercial, plot, industrial
    rate_per_sqyd NUMERIC(12,2),
    rate_per_sqft NUMERIC(12,2),
    rate_per_sqm NUMERIC(12,2),
    revision_year INTEGER NOT NULL,
    effective_date DATE,
    source_url TEXT,
    slug VARCHAR(300) NOT NULL,  -- e.g. sector-57-residential-2026
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(sector, colony, property_type, revision_year)
);

CREATE INDEX idx_circle_rates_slug ON circle_rates (slug);
CREATE INDEX idx_circle_rates_sector_type ON circle_rates (sector, property_type);
CREATE INDEX idx_circle_rates_revision_year ON circle_rates (revision_year DESC);

-- ---------------------------------------------------------------------------
-- 2. rera_projects
--    HRERA registered real estate projects
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rera_projects (
    id SERIAL PRIMARY KEY,
    rera_number VARCHAR(200) NOT NULL UNIQUE,
    project_name VARCHAR(500),
    developer_name VARCHAR(500),
    developer_slug VARCHAR(300),
    location VARCHAR(500),
    district VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    total_units INTEGER,
    units_booked INTEGER,
    possession_date DATE,
    registration_date DATE,
    expiry_date DATE,
    status VARCHAR(50),  -- registered, lapsed, revoked, completed
    project_type VARCHAR(100),
    total_area_sqm NUMERIC(12,2),
    complaint_count INTEGER DEFAULT 0,
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rera_projects_developer_slug ON rera_projects (developer_slug);
CREATE INDEX idx_rera_projects_status ON rera_projects (status);
CREATE INDEX idx_rera_projects_location ON rera_projects (location);

-- ---------------------------------------------------------------------------
-- 3. bank_auctions
--    SARFAESI/IBAPI/MSTC property auctions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_auctions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50),  -- sarfaesi, ibapi, mstc
    bank_name VARCHAR(200),
    property_description TEXT,
    property_type VARCHAR(50),
    area_sqft NUMERIC(12,2),
    city VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    locality VARCHAR(300),
    full_address TEXT,
    reserve_price NUMERIC(15,2),
    emd_amount NUMERIC(15,2),
    auction_date DATE,
    auction_end_date DATE,
    possession_type VARCHAR(50),  -- physical, symbolic
    contact_person VARCHAR(200),
    contact_phone VARCHAR(50),
    contact_email VARCHAR(200),
    source_url TEXT,
    is_active BOOLEAN DEFAULT true,
    raw_data JSONB,
    normalized_address_hash VARCHAR(64),  -- SHA-256 of normalized address for dedup
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(bank_name, normalized_address_hash, auction_date)
);

CREATE INDEX idx_bank_auctions_city_active ON bank_auctions (city, is_active);
CREATE INDEX idx_bank_auctions_auction_date ON bank_auctions (auction_date DESC) WHERE is_active;
CREATE INDEX idx_bank_auctions_type_active ON bank_auctions (property_type, is_active);
CREATE INDEX idx_bank_auctions_reserve_price ON bank_auctions (reserve_price) WHERE is_active;

-- ---------------------------------------------------------------------------
-- 4. auction_alerts
--    User auction alert preferences
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auction_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    city VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    property_type VARCHAR(50),
    min_price NUMERIC(15,2),
    max_price NUMERIC(15,2),
    bank_name VARCHAR(200),
    keyword TEXT,
    alert_channels JSONB DEFAULT '["email"]',
    is_active BOOLEAN DEFAULT true,
    last_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_auction_alerts_user_active ON auction_alerts (user_id, is_active);

-- ---------------------------------------------------------------------------
-- 5. bank_rates
--    RBI repo rate and bank MCLR rates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_rates (
    id SERIAL PRIMARY KEY,
    bank_name VARCHAR(200) NOT NULL,  -- e.g. 'RBI', 'SBI', 'HDFC', 'ICICI', 'Axis', 'PNB'
    rate_type VARCHAR(50) NOT NULL,   -- repo, mclr_1y, mclr_3y, home_loan_min, home_loan_max
    rate_value NUMERIC(6,4) NOT NULL, -- percentage e.g. 6.5000
    effective_date DATE NOT NULL,
    source VARCHAR(200),
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(bank_name, rate_type, effective_date)
);

CREATE INDEX idx_bank_rates_bank_type ON bank_rates (bank_name, rate_type);

-- ---------------------------------------------------------------------------
-- 6. jamabandi_cache
--    Cached land records lookup results (7-day TTL)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jamabandi_cache (
    id SERIAL PRIMARY KEY,
    tehsil VARCHAR(200) NOT NULL,
    village VARCHAR(200) NOT NULL,
    khasra_number VARCHAR(100) NOT NULL,
    khewat_number VARCHAR(100),
    owner_names JSONB,              -- array of strings
    area_kanal NUMERIC(10,4),
    area_marla NUMERIC(10,4),
    mutation_status VARCHAR(100),
    encumbrance_details TEXT,
    survey_number VARCHAR(100),
    source_html TEXT,               -- raw HTML for re-parsing
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL, -- fetched_at + 7 days, set in application
    UNIQUE(tehsil, village, khasra_number)
);

CREATE INDEX idx_jamabandi_cache_lookup ON jamabandi_cache (tehsil, village, khasra_number);
CREATE INDEX idx_jamabandi_cache_expires ON jamabandi_cache (expires_at);

-- ---------------------------------------------------------------------------
-- 7. zoning_data
--    GMDA master plan zoning per sector (FAR, height, land use)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zoning_data (
    id SERIAL PRIMARY KEY,
    sector VARCHAR(200) NOT NULL,
    slug VARCHAR(300) NOT NULL,
    land_use VARCHAR(100),  -- residential, commercial, industrial, green_belt, institutional
    far_limit NUMERIC(6,2),
    max_height_m NUMERIC(8,2),
    max_coverage_pct NUMERIC(5,2),
    setback_front_m NUMERIC(6,2),
    setback_rear_m NUMERIC(6,2),
    master_plan_year INTEGER,
    notes TEXT,
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(sector, land_use)
);

CREATE INDEX idx_zoning_data_slug ON zoning_data (slug);

-- ---------------------------------------------------------------------------
-- 8. colony_approvals
--    TCP Haryana colony approval status
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS colony_approvals (
    id SERIAL PRIMARY KEY,
    colony_name VARCHAR(300) NOT NULL,
    developer_name VARCHAR(300),
    district VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    licence_number VARCHAR(100),
    approval_status VARCHAR(50),  -- approved, pending, revoked
    clu_status VARCHAR(50),       -- approved, pending, rejected
    approval_date DATE,
    area_acres NUMERIC(10,4),
    sector VARCHAR(200),
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(colony_name, licence_number)
);

CREATE INDEX idx_colony_approvals_sector ON colony_approvals (sector);

-- ---------------------------------------------------------------------------
-- 9. gazette_notifications
--    Haryana Gazette notifications relevant to real estate
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gazette_notifications (
    id SERIAL PRIMARY KEY,
    notification_number VARCHAR(200),
    notification_date DATE,
    department VARCHAR(200),
    notification_type VARCHAR(100),  -- land_acquisition, rate_revision, policy, clu_change
    title TEXT NOT NULL,
    summary TEXT,
    pdf_url TEXT,
    pdf_text TEXT,
    relevance_tags JSONB,            -- array of tag strings e.g. ["circle_rate", "Sector 65"]
    relevance_score NUMERIC(3,2),    -- 0.00-1.00
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(notification_number, notification_date)
);

CREATE INDEX idx_gazette_notifications_date ON gazette_notifications (notification_date DESC);
CREATE INDEX idx_gazette_notifications_type ON gazette_notifications (notification_type);
CREATE INDEX idx_gazette_notifications_tags ON gazette_notifications USING GIN (relevance_tags);

-- ---------------------------------------------------------------------------
-- 10. rera_complaints
--     HRERA orders/complaints for builder reputation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rera_complaints (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(200) NOT NULL UNIQUE,
    order_date DATE,
    complainant_type VARCHAR(50),    -- individual, association, authority
    respondent_builder VARCHAR(300),
    respondent_project VARCHAR(500),
    rera_number VARCHAR(100),
    complaint_nature VARCHAR(200),   -- delay, quality, refund, compensation
    order_summary TEXT,
    penalty_amount NUMERIC(15,2),
    direction_type VARCHAR(100),     -- refund, compensation, penalty, dismissal
    pdf_url TEXT,
    pdf_text TEXT,
    builder_slug VARCHAR(300),
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rera_complaints_builder_slug ON rera_complaints (builder_slug);
CREATE INDEX idx_rera_complaints_rera_number ON rera_complaints (rera_number);
CREATE INDEX idx_rera_complaints_order_date ON rera_complaints (order_date DESC);

-- ---------------------------------------------------------------------------
-- 11. court_auctions
--     DRT/eCourts court-ordered auction notices
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS court_auctions (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50),  -- drt, ecourts
    case_number VARCHAR(200) NOT NULL,
    borrower_name VARCHAR(300),
    property_description TEXT,
    property_type VARCHAR(50),
    city VARCHAR(100) NOT NULL DEFAULT 'Gurugram',
    locality VARCHAR(300),
    reserve_price NUMERIC(15,2),
    auction_date DATE,
    presiding_officer VARCHAR(200),
    court_name VARCHAR(200),
    contact_details TEXT,
    source_url TEXT,
    is_active BOOLEAN DEFAULT true,
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(case_number, auction_date)
);

CREATE INDEX idx_court_auctions_city_active ON court_auctions (city, is_active);
CREATE INDEX idx_court_auctions_auction_date ON court_auctions (auction_date DESC) WHERE is_active;

-- ---------------------------------------------------------------------------
-- 12. neighbourhood_scores
--     Google Places API amenity scores per listing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS neighbourhood_scores (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    overall_score INTEGER,           -- 0-100
    category_scores JSONB,           -- {"metro": 85, "schools": 70, ...}
    nearby_places JSONB,             -- [{name, type, distance_m, rating, place_id}, ...]
    metro_stations JSONB,
    schools JSONB,
    hospitals JSONB,
    malls JSONB,
    it_parks JSONB,
    landmarks JSONB,
    api_calls_made INTEGER DEFAULT 0,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    stale_after TIMESTAMPTZ NOT NULL, -- last_fetched + 90 days
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(listing_id)
);

CREATE INDEX idx_neighbourhood_scores_stale ON neighbourhood_scores (stale_after) WHERE stale_after < now();
CREATE INDEX idx_neighbourhood_scores_listing ON neighbourhood_scores (listing_id);

-- ---------------------------------------------------------------------------
-- 13. scraper_runs
--     Audit trail for all scraper runs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scraper_runs (
    id SERIAL PRIMARY KEY,
    scraper_name VARCHAR(100) NOT NULL,
    run_type VARCHAR(20) DEFAULT 'cron',  -- cron, manual, manual_override
    triggered_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',  -- running, success, partial, failed
    records_found INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    metadata JSONB  -- scraper-specific stats
);

CREATE INDEX idx_scraper_runs_name_started ON scraper_runs (scraper_name, started_at DESC);
