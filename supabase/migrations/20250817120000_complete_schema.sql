-- 360Ghar Complete Schema Migration
-- This migration recreates the entire database schema based on the latest SQLAlchemy models
-- Drop and recreate all tables to ensure consistency

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Drop existing tables in dependency order (if they exist)
DROP TABLE IF EXISTS public.user_search_history CASCADE;
DROP TABLE IF EXISTS public.bookings CASCADE;
DROP TABLE IF EXISTS public.visits CASCADE;
DROP TABLE IF EXISTS public.user_swipes CASCADE;
DROP TABLE IF EXISTS public.property_images CASCADE;
DROP TABLE IF EXISTS public.properties CASCADE;
DROP TABLE IF EXISTS public.users CASCADE;
DROP TABLE IF EXISTS public.agents CASCADE;

-- Drop existing custom types
DROP TYPE IF EXISTS response_style CASCADE;
DROP TYPE IF EXISTS experience_level CASCADE;
DROP TYPE IF EXISTS agent_type CASCADE;
DROP TYPE IF EXISTS visit_status CASCADE;
DROP TYPE IF EXISTS payment_status CASCADE;
DROP TYPE IF EXISTS booking_status CASCADE;
DROP TYPE IF EXISTS property_status CASCADE;
DROP TYPE IF EXISTS property_purpose CASCADE;
DROP TYPE IF EXISTS property_type CASCADE;

-- Create custom ENUM types based on models/enums.py
CREATE TYPE property_type AS ENUM ('house', 'apartment', 'builder_floor', 'room');
CREATE TYPE property_purpose AS ENUM ('buy', 'rent', 'short_stay');
CREATE TYPE property_status AS ENUM ('available', 'sold', 'rented', 'under_offer', 'maintenance');
CREATE TYPE booking_status AS ENUM ('pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed');
CREATE TYPE payment_status AS ENUM ('pending', 'partial', 'paid', 'refunded', 'failed');
CREATE TYPE visit_status AS ENUM ('scheduled', 'confirmed', 'completed', 'cancelled', 'rescheduled');
CREATE TYPE agent_type AS ENUM ('general', 'specialist', 'senior');
CREATE TYPE experience_level AS ENUM ('beginner', 'intermediate', 'expert');

-- Agents table (created first due to foreign key in users)
CREATE TABLE public.agents (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
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
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- Users table
CREATE TABLE public.users (
    id BIGSERIAL PRIMARY KEY,
    supabase_user_id VARCHAR UNIQUE NOT NULL,
    email VARCHAR UNIQUE NOT NULL,
    phone VARCHAR,
    full_name VARCHAR,
    date_of_birth TIMESTAMPTZ,
    profile_image_url VARCHAR,
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    preferences JSONB DEFAULT '{}',
    current_latitude REAL,
    current_longitude REAL,
    notification_settings JSONB DEFAULT '{}',
    privacy_settings JSONB DEFAULT '{}',
    agent_id BIGINT REFERENCES public.agents(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- Properties table
CREATE TABLE public.properties (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR NOT NULL,
    description TEXT,
    property_type property_type NOT NULL,
    purpose property_purpose NOT NULL,
    status property_status DEFAULT 'available',
    
    -- Location
    latitude REAL,
    longitude REAL,
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
    
    -- Features
    amenities JSONB,
    features JSONB,
    main_image_url VARCHAR,
    virtual_tour_url VARCHAR,
    tags JSONB,
    search_keywords TEXT,
    
    -- Owner info
    owner_id BIGINT NOT NULL REFERENCES public.users(id),
    owner_name VARCHAR,
    owner_contact VARCHAR,
    builder_name VARCHAR,
    
    -- Meta
    is_available BOOLEAN DEFAULT TRUE,
    available_from TIMESTAMPTZ,
    calendar_data JSONB,
    view_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    interest_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- Property images table
CREATE TABLE public.property_images (
    id BIGSERIAL PRIMARY KEY,
    property_id BIGINT NOT NULL REFERENCES public.properties(id) ON DELETE CASCADE,
    image_url VARCHAR NOT NULL,
    caption VARCHAR,
    display_order INTEGER DEFAULT 0,
    is_main_image BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- User swipes table
CREATE TABLE public.user_swipes (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES public.properties(id) ON DELETE CASCADE,
    is_liked BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- Visits table
CREATE TABLE public.visits (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES public.properties(id) ON DELETE CASCADE,
    agent_id BIGINT REFERENCES public.agents(id),
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

-- Bookings table
CREATE TABLE public.bookings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    property_id BIGINT NOT NULL REFERENCES public.properties(id) ON DELETE CASCADE,
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
    guest_rating INTEGER,
    guest_review TEXT,
    host_rating INTEGER,
    host_review TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- User search history table
CREATE TABLE public.user_search_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
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

-- Create indexes for performance based on model definitions
CREATE INDEX idx_property_location ON public.properties (latitude, longitude);
CREATE INDEX idx_property_filters ON public.properties (property_type, purpose, is_available);
CREATE INDEX idx_property_price ON public.properties (base_price);
CREATE UNIQUE INDEX idx_user_swipes_unique ON public.user_swipes (user_id, property_id);

-- Additional indexes for foreign keys and common queries
CREATE INDEX idx_users_supabase_user_id ON public.users (supabase_user_id);
CREATE INDEX idx_users_email ON public.users (email);
CREATE INDEX idx_users_agent_id ON public.users (agent_id);
CREATE INDEX idx_properties_owner_id ON public.properties (owner_id);
CREATE INDEX idx_property_images_property_id ON public.property_images (property_id);
CREATE INDEX idx_user_swipes_user_id ON public.user_swipes (user_id);
CREATE INDEX idx_user_swipes_property_id ON public.user_swipes (property_id);
CREATE INDEX idx_visits_user_id ON public.visits (user_id);
CREATE INDEX idx_visits_property_id ON public.visits (property_id);
CREATE INDEX idx_visits_agent_id ON public.visits (agent_id);
CREATE INDEX idx_bookings_user_id ON public.bookings (user_id);
CREATE INDEX idx_bookings_property_id ON public.bookings (property_id);
CREATE INDEX idx_bookings_reference ON public.bookings (booking_reference);
CREATE INDEX idx_user_search_history_user_id ON public.user_search_history (user_id);

-- Create triggers for updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_properties_updated_at BEFORE UPDATE ON public.properties FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_property_images_updated_at BEFORE UPDATE ON public.property_images FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_user_swipes_updated_at BEFORE UPDATE ON public.user_swipes FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_agents_updated_at BEFORE UPDATE ON public.agents FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_visits_updated_at BEFORE UPDATE ON public.visits FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_bookings_updated_at BEFORE UPDATE ON public.bookings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Add comments for documentation
COMMENT ON TABLE public.agents IS '360Ghar employee agents who assist users';
COMMENT ON TABLE public.users IS 'User accounts linked to Supabase Auth';
COMMENT ON TABLE public.properties IS 'Real estate properties available for buy/rent/short-stay';
COMMENT ON TABLE public.property_images IS 'Images associated with properties';
COMMENT ON TABLE public.user_swipes IS 'User swipe interactions with properties';
COMMENT ON TABLE public.visits IS 'Scheduled property visits';
COMMENT ON TABLE public.bookings IS 'Short-stay property bookings';
COMMENT ON TABLE public.user_search_history IS 'User search activity tracking';