-- ============================================================
-- 360Ghar Schema — 02: 360 Virtual Tours and media
-- ============================================================
-- tours, scenes, hotspots, floor_plans, tour_analytics_events,
-- ai_jobs, media_files, custom_domains
-- ============================================================

CREATE TYPE tour_status AS ENUM ('draft', 'published', 'archived');
CREATE TYPE hotspot_type AS ENUM ('navigation', 'info', 'audio', 'video', 'link', 'custom');
CREATE TYPE tour_visibility AS ENUM ('private', 'unlisted', 'public');
CREATE TYPE ai_job_status AS ENUM ('pending', 'processing', 'completed', 'failed', 'cancelled');

-- ============================================================
-- Tours (with visibility enum from start)
-- ============================================================
CREATE TABLE tours (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status tour_status DEFAULT 'draft' NOT NULL,
    is_public BOOLEAN DEFAULT FALSE,   -- deprecated, kept for backward compat
    visibility tour_visibility NOT NULL DEFAULT 'private',
    is_featured BOOLEAN DEFAULT FALSE,
    view_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    settings JSONB,
    thumbnail_url VARCHAR(500),
    published_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_tours_user_id ON tours(user_id);
CREATE INDEX idx_tours_status ON tours(status);
CREATE INDEX idx_tours_user_status ON tours(user_id, status);
CREATE INDEX idx_tours_is_public ON tours(is_public) WHERE is_public = TRUE;
CREATE INDEX idx_tours_is_featured ON tours(is_featured) WHERE is_featured = TRUE;
CREATE INDEX idx_tours_visibility ON tours(visibility);
CREATE INDEX idx_tours_status_visibility ON tours(status, visibility) WHERE deleted_at IS NULL;
CREATE INDEX idx_tours_deleted_at ON tours(deleted_at) WHERE deleted_at IS NULL;
CREATE TRIGGER update_tours_updated_at
    BEFORE UPDATE ON tours FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON COLUMN tours.is_public IS 'DEPRECATED: Use visibility column instead.';
COMMENT ON COLUMN tours.visibility IS 'Tour access control: private, unlisted, public';

-- ============================================================
-- Scenes
-- ============================================================
CREATE TABLE scenes (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tour_id VARCHAR(36) NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    title VARCHAR(255),
    description TEXT,
    image_url VARCHAR(500) NOT NULL,
    thumbnail_url VARCHAR(500),
    vr_url VARCHAR(500),
    order_index INTEGER DEFAULT 0,
    scene_metadata JSONB,
    is_processed BOOLEAN DEFAULT FALSE,
    processing_error VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_scenes_tour_id ON scenes(tour_id);
CREATE INDEX idx_scenes_order ON scenes(tour_id, order_index);
CREATE TRIGGER update_scenes_updated_at
    BEFORE UPDATE ON scenes FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Hotspots (with 'link' type and icon_name/content columns)
-- ============================================================
CREATE TABLE hotspots (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    scene_id VARCHAR(36) NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    type hotspot_type DEFAULT 'info' NOT NULL,
    position JSONB NOT NULL,
    target_scene_id VARCHAR(36),
    title VARCHAR(255),
    description TEXT,
    icon VARCHAR(50),
    icon_color VARCHAR(7),
    icon_size INTEGER DEFAULT 32,
    icon_name VARCHAR(100),
    content JSONB,
    custom_data JSONB,
    order_index INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_hotspots_scene_id ON hotspots(scene_id);
CREATE INDEX idx_hotspots_target_scene ON hotspots(target_scene_id) WHERE target_scene_id IS NOT NULL;
CREATE TRIGGER update_hotspots_updated_at
    BEFORE UPDATE ON hotspots FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Floor plans (VARCHAR(36) PK from start — no UUID conversion)
-- ============================================================
CREATE TABLE floor_plans (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tour_id VARCHAR(36) NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'Floor Plan',
    image_url VARCHAR(512) NOT NULL,
    floor_number INTEGER DEFAULT 1,
    markers JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_floor_plans_tour_id ON floor_plans(tour_id);
CREATE TRIGGER update_floor_plans_updated_at
    BEFORE UPDATE ON floor_plans FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Tour analytics events (with all columns from start)
-- ============================================================
CREATE TABLE tour_analytics_events (
    id BIGSERIAL PRIMARY KEY,
    tour_id VARCHAR(36) NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    scene_id VARCHAR(36),
    hotspot_id VARCHAR(36),
    event_type VARCHAR(50) NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    user_agent TEXT,
    ip_address VARCHAR(45),
    country VARCHAR(2),
    city VARCHAR(100),
    device_type VARCHAR(20),
    browser VARCHAR(50),
    os VARCHAR(50),
    screen_resolution VARCHAR(20),
    session_id VARCHAR(255),
    event_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_analytics_tour_id ON tour_analytics_events(tour_id);
CREATE INDEX idx_analytics_created_at ON tour_analytics_events(created_at);
CREATE INDEX idx_analytics_event_type ON tour_analytics_events(tour_id, event_type);
CREATE INDEX idx_analytics_user_id ON tour_analytics_events(user_id);

-- ============================================================
-- AI jobs (with retry_count)
-- ============================================================
CREATE TABLE ai_jobs (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tour_id VARCHAR(36),
    scene_id VARCHAR(36),
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    progress INTEGER DEFAULT 0,
    result JSONB,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX idx_ai_jobs_user_id ON ai_jobs(user_id);
CREATE INDEX idx_ai_jobs_status ON ai_jobs(status);
CREATE INDEX idx_ai_jobs_tour_id ON ai_jobs(tour_id) WHERE tour_id IS NOT NULL;
CREATE INDEX idx_ai_jobs_scene_id ON ai_jobs(scene_id) WHERE scene_id IS NOT NULL;
CREATE INDEX idx_ai_jobs_created_at ON ai_jobs(created_at);
CREATE TRIGGER update_ai_jobs_updated_at
    BEFORE UPDATE ON ai_jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Media files (with upload tracking columns)
-- ============================================================
CREATE TABLE media_files (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tour_id VARCHAR(36) REFERENCES tours(id) ON DELETE SET NULL,
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255),
    file_url VARCHAR(512) NOT NULL,
    thumbnail_url VARCHAR(512),
    cdn_url VARCHAR(512),
    file_size BIGINT NOT NULL DEFAULT 0,
    mime_type VARCHAR(100) NOT NULL,
    width INTEGER,
    height INTEGER,
    duration INTEGER,
    folder VARCHAR(255),
    visibility VARCHAR(20) DEFAULT 'private',
    is_processed BOOLEAN DEFAULT FALSE,
    processing_metadata JSONB,
    upload_status VARCHAR(20) NOT NULL DEFAULT 'complete',
    bucket_name VARCHAR(100) DEFAULT '360ghar-storage',
    storage_path VARCHAR(512),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMPTZ
);
CREATE INDEX idx_media_files_user_id ON media_files(user_id);
CREATE INDEX idx_media_files_tour_id ON media_files(tour_id);
CREATE INDEX idx_media_files_mime_type ON media_files(mime_type);
CREATE INDEX idx_media_files_folder ON media_files(folder);
CREATE INDEX idx_media_files_visibility ON media_files(visibility);
CREATE INDEX idx_media_files_processed ON media_files(is_processed);
CREATE INDEX idx_media_files_created_at ON media_files(created_at);
CREATE INDEX idx_media_files_expires_at ON media_files(expires_at);
CREATE INDEX idx_media_files_upload_status ON media_files(upload_status) WHERE upload_status != 'complete';
CREATE INDEX idx_media_files_bucket_name ON media_files(bucket_name);

-- ============================================================
-- Custom domains
-- ============================================================
CREATE TABLE custom_domains (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain VARCHAR(255) NOT NULL UNIQUE,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    ssl_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    verification_token VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_custom_domains_user_id ON custom_domains(user_id);
CREATE INDEX idx_custom_domains_domain ON custom_domains(domain);
CREATE INDEX idx_custom_domains_verification_status ON custom_domains(verification_status);
CREATE TRIGGER update_custom_domains_updated_at
    BEFORE UPDATE ON custom_domains FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE tours IS '360 virtual tours created by users';
COMMENT ON TABLE scenes IS 'Individual 360 panorama scenes within a tour';
COMMENT ON TABLE hotspots IS 'Interactive elements placed within scenes';
COMMENT ON TABLE tour_analytics_events IS 'Analytics tracking for tour views and interactions';
COMMENT ON TABLE ai_jobs IS 'AI processing jobs for scene analysis, hotspot suggestions, etc.';
