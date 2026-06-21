-- ============================================================
-- 360Ghar Schema — 01: Core identity and marketplace
-- ============================================================
-- users, agents, properties, property_images, amenities,
-- property_amenities, user_swipes, visits, bookings,
-- user_search_history, payment_methods, faqs, pages,
-- bug_reports, app_versions, agent_interactions,
-- ai_conversations, ai_conversation_messages
-- ============================================================

-- ============================================================
-- Enum types (final values — no ALTER chains)
-- ============================================================
CREATE TYPE property_type AS ENUM (
    'house', 'apartment', 'builder_floor', 'room', 'villa', 'plot',
    'condo', 'penthouse', 'studio', 'loft', 'pg', 'flatmate',
    'office', 'shop', 'warehouse'
);
CREATE TYPE property_purpose AS ENUM ('buy', 'rent', 'short_stay');
CREATE TYPE property_status AS ENUM ('available', 'sold', 'rented', 'under_offer', 'maintenance');
CREATE TYPE booking_status AS ENUM ('pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed');
CREATE TYPE payment_status AS ENUM ('pending', 'partial', 'paid', 'refunded', 'failed');
CREATE TYPE visit_status AS ENUM ('scheduled', 'confirmed', 'completed', 'cancelled', 'rescheduled');
CREATE TYPE agent_type AS ENUM ('general', 'specialist', 'senior');
CREATE TYPE experience_level AS ENUM ('beginner', 'intermediate', 'expert');

-- Enums that were TEXT/VARCHAR in old migrations but ORM expects PG enum types
CREATE TYPE user_role AS ENUM ('user', 'agent', 'admin');
CREATE TYPE flatmates_mode AS ENUM ('room_poster', 'seeker', 'co_hunter', 'open_to_both');
CREATE TYPE flatmates_profile_status AS ENUM ('draft', 'pending_review', 'active', 'paused', 'rejected');

-- Lifestyle enums (canonical v2 values)
CREATE TYPE flatmates_sleep_schedule_type AS ENUM ('early_bird', 'flexible', 'night_owl');
CREATE TYPE flatmates_cleanliness_type AS ENUM ('minimal', 'tidy', 'spotless');
CREATE TYPE flatmates_guests_policy_type AS ENUM ('no_overnight_guests', 'occasional_ok', 'open_house');
CREATE TYPE flatmates_food_habits_type AS ENUM ('vegetarian', 'vegan', 'non_vegetarian', 'eggetarian', 'no_preference');
CREATE TYPE flatmates_smoking_drinking_type AS ENUM ('neither', 'smoke_outside', 'drink_occasionally', 'both_fine');
CREATE TYPE flatmates_work_style_type AS ENUM ('wfh', 'office', 'hybrid');

-- Core support enums
CREATE TYPE bug_type AS ENUM ('ui_bug', 'functionality_bug', 'performance_issue', 'crash', 'feature_request', 'other');
CREATE TYPE bug_severity AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE bug_status AS ENUM ('open', 'in_progress', 'resolved', 'closed');
CREATE TYPE page_format AS ENUM ('html', 'markdown', 'json');
CREATE TYPE image_category AS ENUM (
    'room', 'hall', 'kitchen', 'bathroom', 'balcony', 'terrace',
    'garden', 'parking', 'entrance', 'exterior', 'interior', 'others', 'floor_plan'
);
CREATE TYPE message_thread_type AS ENUM ('lease', 'maintenance', 'general');

-- PM enum needed by properties.management_status (full PM enum set in migration 03)
CREATE TYPE managed_property_status AS ENUM ('draft', 'active', 'archived');

-- ============================================================
-- Agents table (before users — FK dependency)
-- ============================================================
CREATE TABLE agents (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    contact_number VARCHAR,
    description TEXT,
    avatar_url VARCHAR,
    languages JSONB,
    agent_type agent_type NOT NULL,
    experience_level experience_level NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_available BOOLEAN DEFAULT TRUE,
    working_hours JSONB,
    total_users_assigned INTEGER DEFAULT 0,
    user_satisfaction_rating REAL DEFAULT 0.0,
    is_seed_data BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_agents_is_active ON agents(is_active);
CREATE INDEX idx_agents_is_available ON agents(is_available);

-- ============================================================
-- Users table (final shape — email-linked identity model)
-- ============================================================
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    supabase_user_id VARCHAR UNIQUE NOT NULL,
    email VARCHAR,                          -- nullable; partial unique index below
    phone VARCHAR,                          -- nullable; unique when present
    full_name VARCHAR,
    date_of_birth TIMESTAMPTZ,
    profile_image_url VARCHAR,
    role user_role NOT NULL DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    phone_verified BOOLEAN NOT NULL DEFAULT FALSE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    last_auth_method TEXT,
    last_auth_method_at TIMESTAMPTZ,
    preferences JSONB DEFAULT '{}',
    current_latitude REAL,
    current_longitude REAL,
    notification_settings JSONB DEFAULT '{}',
    privacy_settings JSONB DEFAULT '{}',

    -- Flatmates profile columns (enums from the start)
    flatmates_mode flatmates_mode,
    flatmates_profile_status flatmates_profile_status NOT NULL DEFAULT 'draft',
    flatmates_onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
    stays_onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
    estate_onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
    ghar360_onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
    flatmates_bio TEXT,
    flatmates_budget_min DOUBLE PRECISION,
    flatmates_budget_max DOUBLE PRECISION,
    flatmates_move_in_timeline VARCHAR(64),
    flatmates_city VARCHAR,
    flatmates_locality VARCHAR,
    flatmates_sleep_schedule flatmates_sleep_schedule_type,
    flatmates_cleanliness flatmates_cleanliness_type,
    flatmates_food_habits flatmates_food_habits_type,
    flatmates_smoking_drinking flatmates_smoking_drinking_type,
    flatmates_guests_policy flatmates_guests_policy_type,
    flatmates_work_style flatmates_work_style_type,
    flatmates_last_active_at TIMESTAMPTZ,

    is_seed_data BOOLEAN NOT NULL DEFAULT FALSE,
    agent_id BIGINT REFERENCES agents(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,

    -- email is the canonical identity-linking key: unique when present
    CONSTRAINT ck_users_last_auth_method CHECK (
        last_auth_method IS NULL
        OR last_auth_method IN (
            'google', 'apple', 'email_password', 'phone_password', 'phone_otp', 'email_otp'
        )
    )
);

-- Phone: unique when present
ALTER TABLE users ADD CONSTRAINT users_phone_unique UNIQUE (phone);
CREATE INDEX idx_users_phone_unique ON users(phone) WHERE phone IS NOT NULL;

-- Email: partial unique index (unique when present)
CREATE UNIQUE INDEX uq_users_email ON users(email) WHERE email IS NOT NULL;

CREATE INDEX idx_users_supabase_user_id ON users(supabase_user_id);
CREATE INDEX idx_users_agent_id ON users(agent_id);
CREATE INDEX idx_users_role ON users(role);

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_agents_updated_at
    BEFORE UPDATE ON agents FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Sync properties.owner_name when user's full_name changes
CREATE TRIGGER trg_users_sync_owner_name
    AFTER UPDATE OF full_name ON users
    FOR EACH ROW EXECUTE FUNCTION public.sync_owner_name_on_user_rename();

-- ============================================================
-- Properties table (final shape — all columns from the start)
-- ============================================================
CREATE TABLE properties (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR NOT NULL,
    description TEXT,
    property_type property_type NOT NULL,
    purpose property_purpose NOT NULL,
    status property_status DEFAULT 'available',

    -- Location
    latitude REAL,
    longitude REAL,
    location geography(POINT, 4326),
    city VARCHAR,
    state VARCHAR,
    country VARCHAR DEFAULT 'India',
    pincode VARCHAR,
    locality VARCHAR,
    sub_locality VARCHAR,
    landmark VARCHAR,
    full_address TEXT,
    area_type VARCHAR,

    -- Pricing
    base_price REAL NOT NULL,
    price_per_sqft REAL,
    monthly_rent REAL,
    daily_rate REAL,
    security_deposit REAL,
    maintenance_charges REAL,

    -- Details
    area_sqft REAL,
    bedrooms INTEGER,
    bathrooms INTEGER,
    balconies INTEGER,
    parking_spaces INTEGER,
    floor_number INTEGER,
    total_floors INTEGER,
    age_of_property INTEGER,
    max_occupancy INTEGER,
    minimum_stay_days INTEGER DEFAULT 1,

    -- Features and media
    features JSONB,
    listing_preferences JSONB,
    main_image_url VARCHAR,
    virtual_tour_url VARCHAR,
    floor_plan_url TEXT,
    video_tour_url TEXT,
    video_urls JSONB,
    google_street_view_url TEXT,
    tags JSONB,
    search_keywords TEXT,

    -- Full-text search
    __ts_vector__ tsvector,

    -- Owner info
    owner_id BIGINT NOT NULL REFERENCES users(id),
    owner_name VARCHAR,
    owner_contact VARCHAR,
    builder_name VARCHAR,

    -- Property management extensions
    is_managed BOOLEAN DEFAULT FALSE,
    management_status managed_property_status DEFAULT 'active',
    payment_due_day INTEGER DEFAULT 1,
    grace_period_days INTEGER DEFAULT 5,
    late_fee_policy JSONB,
    current_lease_id BIGINT,   -- FK added in PM migration (circular dep)
    current_tenant_id BIGINT REFERENCES users(id) ON DELETE SET NULL,

    -- Meta
    is_available BOOLEAN DEFAULT TRUE,
    is_seed_data BOOLEAN NOT NULL DEFAULT FALSE,
    available_from TIMESTAMPTZ,
    calendar_data JSONB,
    view_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    interest_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,

    CONSTRAINT chk_properties_payment_due_day CHECK (payment_due_day BETWEEN 1 AND 28),
    CONSTRAINT chk_properties_grace_period_days CHECK (grace_period_days >= 0)
);

-- Geospatial index
CREATE INDEX idx_property_location_gist ON properties USING GIST (location);
-- Full-text search index
CREATE INDEX idx_property_ts_vector ON properties USING GIN (__ts_vector__);
-- Standard indexes
CREATE INDEX idx_property_filters ON properties (property_type, purpose, is_available);
CREATE INDEX idx_property_price ON properties (base_price);
CREATE INDEX idx_properties_owner_id ON properties (owner_id);
CREATE INDEX idx_properties_owner_managed ON properties (owner_id, is_managed);
CREATE INDEX idx_properties_listing_preferences_gin ON properties USING GIN (listing_preferences);
CREATE INDEX idx_properties_phys_listing ON properties (full_address, latitude, longitude, bedrooms)
    WHERE full_address IS NOT NULL AND latitude IS NOT NULL AND longitude IS NOT NULL;

-- FTS trigger
CREATE TRIGGER ts_vector_update
    BEFORE INSERT OR UPDATE OF title, description, search_keywords, full_address, city, locality
    ON properties FOR EACH ROW
    EXECUTE FUNCTION properties_ts_vector_update();

-- Location auto-populate trigger
CREATE TRIGGER properties_set_location_trigger
    BEFORE INSERT OR UPDATE OF latitude, longitude ON properties
    FOR EACH ROW EXECUTE FUNCTION trg_properties_set_location();

-- Owner name auto-set trigger
CREATE TRIGGER trg_properties_set_owner_name
    BEFORE INSERT OR UPDATE OF owner_id ON properties
    FOR EACH ROW EXECUTE FUNCTION public.set_property_owner_name();

CREATE TRIGGER update_properties_updated_at
    BEFORE UPDATE ON properties FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Property images
-- ============================================================
CREATE TABLE property_images (
    id BIGSERIAL PRIMARY KEY,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    image_url VARCHAR NOT NULL,
    caption VARCHAR,
    display_order INTEGER DEFAULT 0,
    is_main_image BOOLEAN DEFAULT FALSE,
    image_category image_category NOT NULL DEFAULT 'others',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_property_images_property_id ON property_images(property_id);
CREATE INDEX idx_property_images_category ON property_images(image_category);
CREATE TRIGGER update_property_images_updated_at
    BEFORE UPDATE ON property_images FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Amenities + property_amenities (timestamptz from start)
-- ============================================================
CREATE TABLE amenities (
    id SERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL UNIQUE,
    icon VARCHAR(100),
    category VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE TABLE property_amenities (
    id SERIAL PRIMARY KEY,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    amenity_id INTEGER NOT NULL REFERENCES amenities(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_amenities_category ON amenities(category);
CREATE INDEX idx_amenities_is_active ON amenities(is_active);
CREATE INDEX idx_property_amenities_property ON property_amenities(property_id);
CREATE INDEX idx_property_amenities_amenity ON property_amenities(amenity_id);
CREATE UNIQUE INDEX idx_property_amenity_unique ON property_amenities(property_id, amenity_id);

CREATE TRIGGER update_amenities_updated_at
    BEFORE UPDATE ON amenities FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed predefined amenities
INSERT INTO amenities (title, icon, category) VALUES
('Security', 'shield-check', 'safety'),
('CCTV', 'camera', 'safety'),
('Gated Community', 'gate', 'safety'),
('24/7 Security', 'clock', 'safety'),
('Intercom', 'phone', 'safety'),
('Fire Safety', 'fire', 'safety'),
('Swimming Pool', 'pool', 'recreation'),
('Gym', 'dumbbell', 'recreation'),
('Fitness Center', 'fitness', 'recreation'),
('Clubhouse', 'building', 'recreation'),
('Children''s Play Area', 'playground', 'recreation'),
('Sports Court', 'tennis-ball', 'recreation'),
('Jogging Track', 'running', 'recreation'),
('Garden', 'tree', 'recreation'),
('Park', 'park', 'recreation'),
('Parking', 'car', 'convenience'),
('Covered Parking', 'garage', 'convenience'),
('Lift', 'elevator', 'convenience'),
('Elevator', 'elevator', 'convenience'),
('Power Backup', 'battery', 'utilities'),
('Generator', 'generator', 'utilities'),
('Water Supply', 'water', 'utilities'),
('Borewell', 'drill', 'utilities'),
('Rainwater Harvesting', 'droplets', 'utilities'),
('Waste Management', 'trash', 'utilities'),
('Maintenance', 'tools', 'services'),
('WiFi', 'wifi', 'convenience'),
('Internet', 'internet', 'convenience'),
('Cable TV', 'tv', 'convenience'),
('Air Conditioning', 'ac', 'convenience'),
('Central AC', 'ac-central', 'convenience'),
('Heating', 'thermometer', 'convenience'),
('Concierge', 'user-tie', 'services'),
('Housekeeping', 'broom', 'services'),
('Laundry', 'washing-machine', 'services'),
('Grocery Store', 'shopping-cart', 'services'),
('Medical Center', 'medical', 'services'),
('Wheelchair Accessible', 'wheelchair', 'accessibility'),
('Senior Friendly', 'elderly', 'accessibility'),
('Pet Friendly', 'pet', 'accessibility'),
('Metro Connectivity', 'train', 'convenience'),
('Bus Stop Nearby', 'bus', 'convenience'),
('Airport Nearby', 'plane', 'convenience'),
('Mall Nearby', 'shopping-bag', 'convenience'),
('School Nearby', 'school', 'convenience'),
('Hospital Nearby', 'hospital', 'convenience')
ON CONFLICT (title) DO NOTHING;

-- ============================================================
-- User swipes (with flatmates extensions)
-- ============================================================
CREATE TABLE user_swipes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    property_id BIGINT REFERENCES properties(id) ON DELETE CASCADE,
    target_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    context_property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    target_type VARCHAR(20) NOT NULL DEFAULT 'property',
    swipe_action VARCHAR(20) NOT NULL DEFAULT 'like',
    is_liked BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_user_swipes_unique ON user_swipes (user_id, property_id);
CREATE INDEX idx_user_swipes_user_id ON user_swipes (user_id);
CREATE INDEX idx_user_swipes_property_id ON user_swipes (property_id);
CREATE INDEX idx_user_swipes_target_user ON user_swipes (user_id, target_user_id);
CREATE INDEX idx_user_swipes_target_type ON user_swipes (user_id, target_type);
CREATE UNIQUE INDEX idx_user_swipes_unique_target_user
    ON user_swipes (user_id, target_user_id) WHERE target_user_id IS NOT NULL;
CREATE INDEX idx_user_swipes_created_at ON user_swipes (created_at);
CREATE TRIGGER update_user_swipes_updated_at
    BEFORE UPDATE ON user_swipes FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Visits (with flatmates extensions; conversation_id FK added later)
-- ============================================================
CREATE TABLE visits (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    agent_id BIGINT REFERENCES agents(id),
    counterparty_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    conversation_id BIGINT,   -- FK to conversations added in migration 07
    match_id BIGINT,          -- FK to user_matches added in migration 08
    visit_context VARCHAR(32) NOT NULL DEFAULT 'property_tour',
    scheduled_date TIMESTAMPTZ NOT NULL,
    actual_date TIMESTAMPTZ,
    status visit_status DEFAULT 'scheduled',
    special_requirements TEXT,
    visit_notes TEXT,
    visitor_feedback TEXT,
    interest_level VARCHAR,
    follow_up_required BOOLEAN DEFAULT FALSE,
    follow_up_date TIMESTAMPTZ,
    cancellation_reason TEXT,
    rescheduled_from TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_visits_user_id ON visits (user_id);
CREATE INDEX idx_visits_property_id ON visits (property_id);
CREATE INDEX idx_visits_agent_id ON visits (agent_id);
CREATE INDEX idx_visits_scheduled_date ON visits (scheduled_date);
CREATE INDEX idx_visits_status ON visits (status);
CREATE TRIGGER update_visits_updated_at
    BEFORE UPDATE ON visits FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Bookings (with razorpay_order_id)
-- ============================================================
CREATE TABLE bookings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    booking_reference VARCHAR UNIQUE NOT NULL,
    check_in_date TIMESTAMPTZ NOT NULL,
    check_out_date TIMESTAMPTZ NOT NULL,
    nights INTEGER NOT NULL,
    guests INTEGER NOT NULL,
    base_amount REAL NOT NULL,
    taxes_amount REAL NOT NULL,
    service_charges REAL NOT NULL,
    discount_amount REAL NOT NULL,
    total_amount REAL NOT NULL,
    booking_status booking_status NOT NULL,
    payment_status payment_status NOT NULL,
    primary_guest_name VARCHAR NOT NULL,
    primary_guest_phone VARCHAR NOT NULL,
    primary_guest_email VARCHAR NOT NULL,
    guest_details JSONB,
    special_requests TEXT,
    internal_notes TEXT,
    actual_check_in TIMESTAMPTZ,
    actual_check_out TIMESTAMPTZ,
    early_check_in BOOLEAN DEFAULT FALSE,
    late_check_out BOOLEAN DEFAULT FALSE,
    cancellation_date TIMESTAMPTZ,
    cancellation_reason TEXT,
    refund_amount REAL,
    payment_method VARCHAR,
    transaction_id VARCHAR,
    payment_date TIMESTAMPTZ,
    razorpay_order_id VARCHAR,
    guest_rating INTEGER,
    guest_review TEXT,
    host_rating INTEGER,
    host_review TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_bookings_user_id ON bookings (user_id);
CREATE INDEX idx_bookings_property_id ON bookings (property_id);
CREATE INDEX idx_bookings_reference ON bookings (booking_reference);
CREATE INDEX idx_bookings_razorpay_order_id ON bookings (razorpay_order_id) WHERE razorpay_order_id IS NOT NULL;
CREATE TRIGGER update_bookings_updated_at
    BEFORE UPDATE ON bookings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- User search history
-- ============================================================
CREATE TABLE user_search_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    search_query VARCHAR,
    search_filters JSONB,
    search_location VARCHAR,
    search_radius INTEGER,
    results_count INTEGER,
    user_location_lat REAL,
    user_location_lng REAL,
    search_type VARCHAR,
    session_id VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_user_search_history_user_id ON user_search_history (user_id);

-- ============================================================
-- Payment methods (NEW — was missing, ORM model exists)
-- ============================================================
CREATE TABLE payment_methods (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    method_type VARCHAR NOT NULL,
    brand VARCHAR,
    last4 VARCHAR(4),
    razorpay_token VARCHAR,
    razorpay_payment_id VARCHAR,
    nickname VARCHAR,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_payment_methods_user_id ON payment_methods (user_id);

-- ============================================================
-- FAQs
-- ============================================================
CREATE TABLE faqs (
    id SERIAL PRIMARY KEY,
    question VARCHAR(500) NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(100),
    tags JSONB,
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_faqs_category ON faqs(category);
CREATE INDEX idx_faqs_is_active ON faqs(is_active);
CREATE INDEX idx_faqs_display_order ON faqs(display_order);
CREATE TRIGGER update_faqs_updated_at
    BEFORE UPDATE ON faqs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Pages (with is_private)
-- ============================================================
CREATE TABLE pages (
    id SERIAL PRIMARY KEY,
    unique_name VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    format page_format DEFAULT 'html',
    custom_config JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    is_draft BOOLEAN DEFAULT FALSE,
    is_private BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id),
    updated_by INTEGER REFERENCES users(id),
    view_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_pages_unique_name ON pages(unique_name);
CREATE INDEX idx_pages_is_active ON pages(is_active);
CREATE INDEX idx_pages_is_draft ON pages(is_draft);
CREATE INDEX idx_pages_is_private ON pages(is_private);
CREATE TRIGGER update_pages_updated_at
    BEFORE UPDATE ON pages FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Bug reports
-- ============================================================
CREATE TABLE bug_reports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    source VARCHAR(50) NOT NULL,
    bug_type bug_type NOT NULL,
    severity bug_severity NOT NULL,
    status bug_status DEFAULT 'open',
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    steps_to_reproduce TEXT,
    expected_behavior TEXT,
    actual_behavior TEXT,
    device_info JSONB,
    app_version VARCHAR(50),
    media_urls JSONB,
    tags JSONB,
    assigned_to INTEGER REFERENCES users(id),
    resolution TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_bug_reports_user_id ON bug_reports(user_id);
CREATE INDEX idx_bug_reports_status ON bug_reports(status);
CREATE INDEX idx_bug_reports_bug_type ON bug_reports(bug_type);
CREATE INDEX idx_bug_reports_created_at ON bug_reports(created_at);
CREATE TRIGGER update_bug_reports_updated_at
    BEFORE UPDATE ON bug_reports FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- App versions (renamed from app_updates, with app column)
-- ============================================================
CREATE TABLE app_versions (
    id SERIAL PRIMARY KEY,
    app VARCHAR NOT NULL,
    platform VARCHAR(20) NOT NULL,
    version VARCHAR(20) NOT NULL,
    build_number INTEGER,
    release_notes TEXT,
    download_url VARCHAR(500),
    is_mandatory BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    min_supported_version VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_app_versions_platform ON app_versions(platform);
CREATE INDEX idx_app_versions_is_active ON app_versions(is_active);
CREATE INDEX idx_app_versions_created_at ON app_versions(created_at);
CREATE INDEX idx_app_versions_app ON app_versions(app);
CREATE INDEX idx_app_versions_app_platform ON app_versions(app, platform);
CREATE TRIGGER update_app_versions_updated_at
    BEFORE UPDATE ON app_versions FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Agent interactions
-- ============================================================
CREATE TABLE agent_interactions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    response TEXT,
    response_time_seconds INTEGER,
    user_satisfaction INTEGER CHECK (user_satisfaction >= 1 AND user_satisfaction <= 5),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_agent_interactions_agent_id ON agent_interactions(agent_id);
CREATE INDEX idx_agent_interactions_user_id ON agent_interactions(user_id);
CREATE INDEX idx_agent_interactions_created_at ON agent_interactions(created_at);
CREATE INDEX idx_agent_interactions_agent_created ON agent_interactions(agent_id, created_at);

-- ============================================================
-- AI conversations (user ↔ AI agent; separate from generic conversations)
-- ============================================================
CREATE TABLE ai_conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_conversations_user ON ai_conversations (user_id, updated_at DESC);
CREATE TRIGGER update_ai_conversations_updated_at
    BEFORE UPDATE ON ai_conversations FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE ai_conversation_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT,
    tool_name VARCHAR(100),
    tool_args JSONB,
    tool_result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_messages_conv ON ai_conversation_messages (conversation_id, created_at);

-- Auto-update conversation timestamp when a message is inserted
CREATE OR REPLACE FUNCTION update_ai_conversation_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE ai_conversations SET updated_at = NOW() WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ai_message_update_conv_ts
    AFTER INSERT ON ai_conversation_messages
    FOR EACH ROW EXECUTE FUNCTION update_ai_conversation_timestamp();

COMMENT ON TABLE agents IS '360Ghar employee agents who assist users';
COMMENT ON TABLE users IS 'User accounts linked to Supabase Auth';
COMMENT ON TABLE properties IS 'Real estate properties available for buy/rent/short-stay';
COMMENT ON COLUMN properties.__ts_vector__ IS 'Pre-computed tsvector for full-text search on property details';
COMMENT ON COLUMN properties.location IS 'Geospatial location of the property as a PostGIS geography point (SRID 4326)';
COMMENT ON TABLE property_images IS 'Images associated with properties';
COMMENT ON TABLE user_swipes IS 'User swipe interactions with properties and other users';
COMMENT ON TABLE visits IS 'Scheduled property visits and flatmate meets';
COMMENT ON TABLE bookings IS 'Short-stay property bookings';
