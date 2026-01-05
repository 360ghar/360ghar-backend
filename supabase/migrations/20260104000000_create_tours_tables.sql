-- 360 Virtual Tours Migration
-- Creates tables for tours, scenes, hotspots, and analytics events

-- Create enum types for tour status and hotspot types
DO $$ BEGIN
    CREATE TYPE tour_status AS ENUM ('draft', 'published', 'archived');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE hotspot_type AS ENUM ('navigation', 'info', 'audio', 'video', 'custom');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Tours table
CREATE TABLE IF NOT EXISTS tours (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status tour_status DEFAULT 'draft' NOT NULL,
    is_public BOOLEAN DEFAULT FALSE,
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

-- Scenes table
CREATE TABLE IF NOT EXISTS scenes (
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

-- Hotspots table
CREATE TABLE IF NOT EXISTS hotspots (
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
    custom_data JSONB,
    order_index INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Tour analytics events table
CREATE TABLE IF NOT EXISTS tour_analytics_events (
    id BIGSERIAL PRIMARY KEY,
    tour_id VARCHAR(36) NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    scene_id VARCHAR(36),
    hotspot_id VARCHAR(36),
    event_type VARCHAR(50) NOT NULL,
    user_agent TEXT,
    ip_address VARCHAR(45),
    country VARCHAR(2),
    device_type VARCHAR(20),
    session_id VARCHAR(36),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Create indexes for tours
CREATE INDEX IF NOT EXISTS idx_tours_user_id ON tours(user_id);
CREATE INDEX IF NOT EXISTS idx_tours_status ON tours(status);
CREATE INDEX IF NOT EXISTS idx_tours_user_status ON tours(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tours_is_public ON tours(is_public) WHERE is_public = TRUE;
CREATE INDEX IF NOT EXISTS idx_tours_is_featured ON tours(is_featured) WHERE is_featured = TRUE;
CREATE INDEX IF NOT EXISTS idx_tours_deleted_at ON tours(deleted_at) WHERE deleted_at IS NULL;

-- Create indexes for scenes
CREATE INDEX IF NOT EXISTS idx_scenes_tour_id ON scenes(tour_id);
CREATE INDEX IF NOT EXISTS idx_scenes_order ON scenes(tour_id, order_index);

-- Create indexes for hotspots
CREATE INDEX IF NOT EXISTS idx_hotspots_scene_id ON hotspots(scene_id);
CREATE INDEX IF NOT EXISTS idx_hotspots_target_scene ON hotspots(target_scene_id) WHERE target_scene_id IS NOT NULL;

-- Create indexes for analytics
CREATE INDEX IF NOT EXISTS idx_analytics_tour_id ON tour_analytics_events(tour_id);
CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON tour_analytics_events(created_at);
CREATE INDEX IF NOT EXISTS idx_analytics_event_type ON tour_analytics_events(tour_id, event_type);

-- Create updated_at trigger function if not exists
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Add triggers for updated_at
DROP TRIGGER IF EXISTS update_tours_updated_at ON tours;
CREATE TRIGGER update_tours_updated_at
    BEFORE UPDATE ON tours
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_scenes_updated_at ON scenes;
CREATE TRIGGER update_scenes_updated_at
    BEFORE UPDATE ON scenes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_hotspots_updated_at ON hotspots;
CREATE TRIGGER update_hotspots_updated_at
    BEFORE UPDATE ON hotspots
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add comments for documentation
COMMENT ON TABLE tours IS '360 virtual tours created by users';
COMMENT ON TABLE scenes IS 'Individual 360° panorama scenes within a tour';
COMMENT ON TABLE hotspots IS 'Interactive elements (navigation, info, media) placed within scenes';
COMMENT ON TABLE tour_analytics_events IS 'Analytics tracking for tour views and interactions';

COMMENT ON COLUMN tours.settings IS 'Tour configuration: auto_rotate, initial_scene_id, branding, etc.';
COMMENT ON COLUMN scenes.scene_metadata IS 'Scene config: initial_view (yaw, pitch, zoom), camera settings, GPS, EXIF';
COMMENT ON COLUMN hotspots.position IS 'Position in 3D space: {yaw, pitch, radius?}';
COMMENT ON COLUMN hotspots.custom_data IS 'Additional data for custom hotspot types';
